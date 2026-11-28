import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.database import SessionLocal

PERIOD = {
    "since": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
    "until": datetime.now(UTC).isoformat(),
}


async def person(client, make_token):
    """A signed-in account with no home."""
    import uuid

    token = make_token(sub=str(uuid.uuid4()))
    headers = {"Authorization": f"Bearer {token}"}
    me = (await client.get("/api/v1/users/me", headers=headers)).json()
    return headers, me["id"]


async def invite(client, owner) -> str:
    r = await client.post("/api/v1/homes/current/invites", headers=owner.headers)
    assert r.status_code == 201, r.text
    return r.json()["code"]


async def accept(client, headers, code):
    return await client.post("/api/v1/homes/invites/accept", json={"code": code}, headers=headers)


async def row(user_id):
    async with SessionLocal() as s:
        return (
            await s.execute(
                text("SELECT home_id, role, detail FROM public.tb_home_member WHERE user_id = :u"),
                {"u": user_id},
            )
        ).one_or_none()


async def test_an_invited_person_joins_seeing_days_only_and_the_code_works_once(
    client, make_member, make_token
):
    owner = await make_member("owner")
    code = await invite(client, owner)
    headers, user = await person(client, make_token)

    r = await accept(client, headers, f" {code.lower()} ")

    assert r.status_code == 200, r.text
    assert tuple(await row(user)) == (owner.home_id, "member", "daily")
    late, _ = await person(client, make_token)
    again = await accept(client, late, code)
    assert (again.status_code, again.json()["code"]) == (404, "invite_invalid")
    async with SessionLocal() as s:  # the code itself is not stored
        stored = await s.scalar(
            text("SELECT code_hash FROM public.tb_home_invite WHERE home_id = :h"),
            {"h": owner.home_id},
        )
    assert code not in stored


async def test_an_expired_or_wrong_code_is_refused_and_guessing_stops(
    client, make_member, make_token
):
    owner = await make_member("owner")
    code = await invite(client, owner)
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text("UPDATE public.tb_home_invite SET expires_at = now() WHERE home_id = :h"),
            {"h": owner.home_id},
        )
    headers, user = await person(client, make_token)
    assert (await accept(client, headers, code)).status_code == 404
    got = [(await accept(client, headers, "WRONGCODE2")).status_code for _ in range(10)]
    assert got[-1] == 429
    assert await row(user) is None


async def test_a_member_of_a_home_cannot_take_an_invite_but_a_demo_viewer_can(client, make_member):
    owner, other = await make_member("owner"), await make_member("owner")
    code = await invite(client, owner)
    r = await accept(client, other.headers, code)
    assert (r.status_code, r.json()["code"]) == (409, "already_has_home")
    viewer = await make_member("viewer", home_id=other.home_id)
    assert (await accept(client, viewer.headers, code)).status_code == 200  # still unused
    assert tuple(await row(viewer.user_id)) == (owner.home_id, "member", "daily")


async def test_only_the_owner_invites_lists_emails_and_changes_members(client, make_member):
    owner = await make_member("owner")
    member = await make_member("member", home_id=owner.home_id)
    viewer = await make_member("viewer", home_id=owner.home_id)

    listed = (await client.get("/api/v1/homes/current/members", headers=owner.headers)).json()
    assert [m["role"] for m in listed] == ["owner", "member"]  # demo visitors are not members
    assert all(m["email"] for m in listed)
    seen = (await client.get("/api/v1/homes/current/members", headers=member.headers)).json()
    assert [m["email"] for m in seen] == [None, None]
    r = await client.get("/api/v1/homes/current/members", headers=viewer.headers)
    assert r.status_code == 403

    one = f"/api/v1/homes/current/members/{member.user_id}"
    for who in (member, viewer):
        assert (
            await client.post("/api/v1/homes/current/invites", headers=who.headers)
        ).status_code == 403
        r = await client.patch(one, json={"detail": "full"}, headers=who.headers)
        assert r.status_code == 403
        assert (await client.delete(one, headers=who.headers)).status_code == 403
    own = f"/api/v1/homes/current/members/{owner.user_id}"
    assert (await client.delete(own, headers=owner.headers)).status_code == 404
    r = await client.patch(own, json={"detail": "daily"}, headers=owner.headers)
    assert r.status_code == 404


async def seed_own_things(member):
    async with SessionLocal() as s, s.begin():
        p = {"h": member.home_id, "u": member.user_id}
        await s.execute(
            text("INSERT INTO ai.ai_conversation (home_id, user_id) VALUES (:h, :u)"), p
        )
        await s.execute(
            text(
                "INSERT INTO public.tb_savings_plan (user_id, home_id, start_on, end_on, "
                "model_version, forecast_kwh, actions) VALUES (:u, :h, current_date, "
                "current_date, 'v', 1, '[]'::jsonb)"
            ),
            p,
        )


async def own_things(home_id, user_id) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            text(
                "SELECT (SELECT count(*) FROM ai.ai_conversation WHERE home_id = :h AND "
                "user_id = :u) + (SELECT count(*) FROM public.tb_savings_plan WHERE "
                "home_id = :h AND user_id = :u)"
            ),
            {"h": home_id, "u": user_id},
        )


async def test_removing_or_leaving_takes_the_persons_things_with_it(client, make_member):
    owner = await make_member("owner")
    removed = await make_member("member", home_id=owner.home_id)
    leaving = await make_member("member", home_id=owner.home_id)
    for m in (removed, leaving):
        await seed_own_things(m)
        assert await own_things(owner.home_id, m.user_id) == 2

    r = await client.delete(
        f"/api/v1/homes/current/members/{removed.user_id}", headers=owner.headers
    )
    assert r.status_code == 204, r.text
    r = await client.delete("/api/v1/homes/current/membership", headers=leaving.headers)
    assert r.status_code == 204, r.text

    for m in (removed, leaving):
        assert await row(m.user_id) is None
        assert await own_things(owner.home_id, m.user_id) == 0
    r = await client.delete("/api/v1/homes/current/membership", headers=owner.headers)
    assert r.status_code == 403


async def test_a_daily_member_gets_no_figure_finer_than_a_day(client, make_member):
    owner = await make_member("owner")
    member = await make_member("member", home_id=owner.home_id)
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO public.tb_alert (home_id, kind, severity, ts, dedup_key, payload) "
                "VALUES (:h, 'device_anomaly', 'warning', '2026-11-20 02:13+07', 'x', "
                "CAST(:p AS jsonb))"
            ),
            {
                "h": owner.home_id,
                "p": json.dumps({"signal": "odd_hour", "value": 2.0, "at": "02:13"}),
            },
        )
    r = await client.patch(
        f"/api/v1/homes/current/members/{member.user_id}",
        json={"detail": "daily"},
        headers=owner.headers,
    )
    assert r.status_code == 204, r.text

    for path in ("/api/v1/energy/series", "/api/v1/energy/activity", "/api/v1/expected"):
        params = PERIOD if path.endswith("series") else None
        if path.endswith("expected"):
            params = {"from": PERIOD["since"], "to": PERIOD["until"]}
        r = await client.get(path, params=params, headers=member.headers)
        assert (r.status_code, r.json()["code"]) == (403, "detail_restricted"), path
    r = await client.get("/api/v1/energy/stream", headers=member.headers)
    assert r.status_code == 403
    assert (await client.get("/api/v1/energy/overview", headers=member.headers)).json()[
        "live"
    ] is None
    (alert,) = (await client.get("/api/v1/insights/alerts", headers=member.headers)).json()
    assert alert["ts"].startswith(("2026-11-19T17:00", "2026-11-20T00:00"))
    assert alert["payload"] == {"signal": "odd_hour"}
    (full,) = (await client.get("/api/v1/insights/alerts", headers=owner.headers)).json()
    assert full["payload"]["value"] == 2.0
    home = (await client.get("/api/v1/homes/current", headers=member.headers)).json()
    assert (home["detail"], home["ai_detail_effective"]) == ("daily", "daily")


async def test_a_daily_member_sets_no_watch_on_the_moment(client, make_member):
    owner = await make_member("owner", ai_detail="hourly")
    member = await make_member("member", home_id=owner.home_id)
    body = {"metric": "power_w", "op": "gt", "threshold": 99999, "label": "x"}
    made = await client.post("/api/v1/insights/watches", json=body, headers=member.headers)
    assert made.status_code == 201, made.text
    one = f"/api/v1/homes/current/members/{member.user_id}"
    await client.patch(one, json={"detail": "daily"}, headers=owner.headers)
    left = (await client.get("/api/v1/insights/watches", headers=member.headers)).json()
    assert [w for w in left if w["status"] == "active"] == []  # the old one stops
    r = await client.post("/api/v1/insights/watches", json=body, headers=member.headers)
    assert r.status_code >= 400 and r.json()["code"] == "needs_hourly", r.text


async def test_wappi_answers_a_daily_member_by_day(client, make_member):
    from app.modules.home.api import Home, HomeMember, ai_detail

    owner = await make_member("owner", ai_detail="hourly")
    member = await make_member("member", home_id=owner.home_id)
    async with SessionLocal() as s, s.begin():
        home = await s.get(Home, owner.home_id)
        mine = await s.get(HomeMember, (owner.home_id, member.user_id))
        assert ai_detail(home, mine) == "hourly"
        mine.detail = "daily"
        assert ai_detail(home, mine) == "daily"
