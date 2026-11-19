from sqlalchemy import text

from app.database import SessionLocal


async def test_cohort_is_404_until_a_cohort_is_stored(client, make_member):
    me = await make_member("member", home_type="house")
    r = await client.get("/api/v1/insights/cohort", headers=me.headers)
    assert (r.status_code, r.json()["code"]) == (404, "cohort_too_small")

    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO public.tb_cohort_stat VALUES "
                "('all', '2026-11-09', 100, 200, 300, 400, 12)"
            )
        )
    try:
        r = await client.get("/api/v1/insights/cohort", headers=me.headers)
        assert r.status_code == 200
        body = r.json()
        assert (body["cohort_key"], body["homes"], body["p10"], body["kwh"]) == (
            "all",
            12,
            72.0,
            None,  # 100 W over 30 days; this home has no readings
        )
    finally:
        async with SessionLocal() as s, s.begin():
            await s.execute(text("DELETE FROM public.tb_cohort_stat WHERE cohort_key = 'all'"))


async def _alert(home_id, kind="unexplained_load", ts="now()", **cols):
    async with SessionLocal() as s, s.begin():
        return await s.scalar(
            text(
                "INSERT INTO public.tb_alert "
                "(home_id, kind, severity, ts, payload, dedup_key, status) "
                f"VALUES (:h, :k, :sev, {ts}, :p, :k, :st) RETURNING id"
            ),
            {
                "h": home_id,
                "k": kind,
                "sev": cols.get("severity", "warning"),
                "p": '{"watts": 900, "usual_w": 200, "minutes": 45}',
                "st": cols.get("status", "open"),
            },
        )


async def test_alerts_list_and_acknowledge_stay_inside_the_home(client, make_member):
    me = await make_member("member")
    other = await make_member("owner")
    mine = await _alert(me.home_id)
    old = await _alert(me.home_id, "standby_high", "now() - interval '2 days'", status="resolved")
    theirs = await _alert(other.home_id)

    r = await client.get("/api/v1/insights/alerts", headers=me.headers)
    assert r.status_code == 200
    assert [a["id"] for a in r.json()] == [str(mine), str(old)]
    assert r.json()[0]["payload"] == {"watts": 900, "usual_w": 200, "minutes": 45}
    assert r.json()[0]["device"] is None

    url = f"/api/v1/insights/alerts/{mine}"
    assert (
        await client.patch(url, json={"status": "resolved"}, headers=me.headers)
    ).status_code == 422
    assert (
        await client.patch(url, json={"status": "acknowledged"}, headers=me.headers)
    ).status_code == 204
    r = await client.get("/api/v1/insights/alerts?status=acknowledged", headers=me.headers)
    assert [a["id"] for a in r.json()] == [str(mine)]
    r = await client.patch(
        f"/api/v1/insights/alerts/{theirs}", json={"status": "acknowledged"}, headers=me.headers
    )
    assert (r.status_code, r.json()["code"]) == (404, "alert_not_found")


async def test_new_alerts_are_mailed_once_to_members_who_want_them(make_member, monkeypatch):
    from datetime import UTC, datetime

    from app.modules.insight.services import mail

    sent = []

    async def fake_send(to, subject, body):
        sent.append((to, subject))

    monkeypatch.setattr(mail, "send", fake_send)
    owner = await make_member("owner")
    quiet = await make_member("member", home_id=owner.home_id)
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO public.tb_user_preference (user_id, notify_anomaly) VALUES (:u, false)"
            ),
            {"u": quiet.user_id},
        )
        email = await s.scalar(
            text("SELECT email FROM public.tb_users WHERE id = :u"), {"u": owner.user_id}
        )
    fresh = await _alert(owner.home_id)
    stale = await _alert(owner.home_id, "longer_than_usual", "now() - interval '3 days'")
    info = await _alert(owner.home_id, "standby_high", severity="info")

    await mail.mail_alerts(datetime.now(UTC))
    await mail.mail_alerts(datetime.now(UTC))
    assert sent == [(email, "WattPrint: Có tải lạ đang chạy")]
    async with SessionLocal() as s:
        notified = dict(
            (
                await s.execute(
                    text(
                        "SELECT id, notified_at IS NOT NULL FROM public.tb_alert WHERE home_id = :h"
                    ),
                    {"h": owner.home_id},
                )
            ).all()
        )
    assert notified == {fresh: True, stale: True, info: False}  # stale: marked, not mailed late


async def test_weekly_summary_goes_out_on_monday_morning_once(make_member, monkeypatch):
    from datetime import UTC, datetime

    from app.modules.insight.services import mail

    sent = []

    async def fake_send(to, subject, body):
        sent.append(body)

    monkeypatch.setattr(mail, "send", fake_send)
    me = await make_member("owner")
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO public.tb_user_preference (user_id, weekly_summary) VALUES (:u, true)"
            ),
            {"u": me.user_id},
        )
    monday_7am = datetime(2026, 11, 16, 0, tzinfo=UTC)  # 07:00 in Vietnam
    await mail.mail_weekly(monday_7am)
    assert sent == []
    await mail.mail_weekly(monday_7am.replace(hour=2))
    await mail.mail_weekly(monday_7am.replace(hour=5))
    assert len(sent) == 1 and sent[0].startswith("Tuần qua nhà dùng 0,0 kWh.")


async def test_an_alert_raised_again_the_same_day_is_not_mailed_again(make_member, monkeypatch):
    from datetime import UTC, datetime

    from app.modules.insight.services import mail

    sent = []

    async def fake_send(to, subject, body):
        sent.append(subject)

    monkeypatch.setattr(mail, "send", fake_send)
    me = await make_member("owner")
    await _alert(me.home_id)
    await mail.mail_alerts(datetime.now(UTC))
    async with SessionLocal() as s, s.begin():  # the cause goes, then comes back
        await s.execute(
            text("UPDATE public.tb_alert SET status = 'resolved' WHERE home_id = :h"),
            {"h": me.home_id},
        )
    await _alert(me.home_id)
    await mail.mail_alerts(datetime.now(UTC))
    assert sent == ["WattPrint: Có tải lạ đang chạy"]


async def test_a_refused_address_does_not_re_mail_the_others(make_member, monkeypatch):
    from datetime import UTC, datetime

    from app.modules.insight.services import mail

    owner = await make_member("owner")
    other = await make_member("member", home_id=owner.home_id)
    async with SessionLocal() as s:
        bad = await s.scalar(
            text("SELECT email FROM public.tb_users WHERE id = :u"), {"u": other.user_id}
        )
    sent, refuse = [], {bad}

    async def fake_send(to, subject, body):
        if to in refuse:
            raise OSError("550 mailbox unavailable")
        sent.append(to)

    monkeypatch.setattr(mail, "send", fake_send)
    alert = await _alert(owner.home_id)
    await mail.mail_alerts(datetime.now(UTC))
    await mail.mail_alerts(datetime.now(UTC))  # retried for the refused member only
    assert len(sent) == 1
    refuse.clear()
    await mail.mail_alerts(datetime.now(UTC))
    assert sorted(sent) == sorted([sent[0], bad])
    async with SessionLocal() as s:
        done = await s.scalar(
            text("SELECT notified_at IS NOT NULL FROM public.tb_alert WHERE id = :a"), {"a": alert}
        )
    assert done
