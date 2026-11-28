from datetime import datetime, timedelta

from test_erase_history import ICT, KEPT, OLD, seed


async def test_the_page_says_what_is_kept_and_since_when(client, make_member):
    owner, other = await make_member("owner"), await make_member("owner")
    await seed(owner.home_id)

    r = await client.get("/api/v1/homes/current/privacy", headers=owner.headers)

    assert r.status_code == 200, r.text
    body = r.json()
    kept = {level["level"]: level for level in body["levels"]}
    assert list(kept) == ["raw", "1m", "1h", "1d"]
    assert all(k["oldest"] == OLD.date().isoformat() for k in kept.values()), kept
    assert kept["raw"]["keep_days"] == 400  # read from the database's own retention policy
    assert kept["1d"]["keep_days"] is None  # nothing drops it yet
    assert body["can_erase"] is True

    empty = (await client.get("/api/v1/homes/current/privacy", headers=other.headers)).json()
    assert [k["oldest"] for k in empty["levels"]] == [None] * 4  # only its own home's data


async def test_a_member_sees_it_but_cannot_erase(client, make_member):
    owner = await make_member("owner")
    cut = datetime.now(ICT) - timedelta(days=1)
    r = await client.delete(
        f"/api/v1/homes/current/history?before={cut.date()}", headers=owner.headers
    )
    assert r.status_code == 204
    member = await make_member("member", home_id=owner.home_id)
    body = (await client.get("/api/v1/homes/current/privacy", headers=member.headers)).json()
    assert body["can_erase"] is False
    assert body["erased_before"] == cut.date().isoformat() > KEPT.date().isoformat()
