import uuid

import pytest
from sqlalchemy import text

from app.config import settings


@pytest.fixture
async def seeded(tmp_path, monkeypatch, client, make_member):
    """Houses 2 and 3 (their owners are in homes) and 5 (owner never seeded); answers the owners."""
    owners = [await make_member(), await make_member()]
    emails = [
        (await client.get("/api/v1/users/me", headers=o.headers)).json()["email"] for o in owners
    ]
    toml = tmp_path / "demo_homes.toml"
    toml.write_text(
        f"""
[[home]]
house = 2
owner = {{ email = "{emails[0]}", name = "REFIT House 2" }}
devices = {{ Fridge = "Fridge-Freezer", Kettle = "Kettle", Other = "Other" }}

[[home]]
house = 3
owner = {{ email = "{emails[1]}", name = "REFIT House 3" }}
devices = {{ Kettle = "Kettle" }}

[[home]]
house = 5
key = "5-heat"
name = "REFIT House 5 heat"
owner = {{ email = "nobody.{owners[0].user_id}@wattprint.local", name = "x" }}
devices = {{ Kettle = "Kettle" }}
"""
    )
    monkeypatch.setattr(settings, "demo_homes_file", str(toml))
    return owners


@pytest.fixture
async def visitor(client, make_token):
    """A signed-in account that belongs to no home (a new sign-up); its row is removed after."""
    from app.database import SessionLocal

    headers = {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}
    me = (await client.get("/api/v1/users/me", headers=headers)).json()
    yield headers
    async with SessionLocal() as s, s.begin():
        await s.execute(text("DELETE FROM public.tb_users WHERE id = :u"), {"u": me["id"]})


async def test_homes_lists_only_seeded(client, seeded):
    r = await client.get("/api/v1/demo/homes")
    assert r.status_code == 200
    assert r.json() == [
        {
            "key": "2",
            "house": 2,
            "name": "REFIT House 2",
            "devices": [
                {"label": "Fridge", "name": "Fridge-Freezer"},
                {"label": "Kettle", "name": "Kettle"},
            ],
        },
        {
            "key": "3",
            "house": 3,
            "name": "REFIT House 3",
            "devices": [{"label": "Kettle", "name": "Kettle"}],
        },
    ]
    assert "@" not in r.text


async def test_a_visitor_views_a_demo_home_read_only_and_can_switch(client, seeded, visitor):
    r = await client.post("/api/v1/demo/homes/2/view", headers=visitor)
    assert r.status_code == 200
    assert r.json()["id"] == str(seeded[0].home_id)
    assert r.json()["role"] == "viewer"
    current = await client.get("/api/v1/homes/current", headers=visitor)
    assert (current.json()["id"], current.json()["role"]) == (str(seeded[0].home_id), "viewer")
    # Again on the same home: nothing changes; on another: the one viewer row moves there.
    assert (await client.post("/api/v1/demo/homes/2/view", headers=visitor)).status_code == 200
    r = await client.post("/api/v1/demo/homes/3/view", headers=visitor)
    assert r.json()["id"] == str(seeded[1].home_id)
    current = await client.get("/api/v1/homes/current", headers=visitor)
    assert current.json()["id"] == str(seeded[1].home_id)


async def test_two_tabs_viewing_at_once_both_succeed(client, seeded, visitor):
    import asyncio

    rs = await asyncio.gather(
        client.post("/api/v1/demo/homes/2/view", headers=visitor),
        client.post("/api/v1/demo/homes/3/view", headers=visitor),
    )
    assert [r.status_code for r in rs] == [200, 200]
    current = await client.get("/api/v1/homes/current", headers=visitor)
    assert current.json()["role"] == "viewer"


@pytest.mark.parametrize("key", ["5-heat", "9", "2;drop"])
async def test_view_unknown_or_unseeded_404(client, seeded, visitor, key):
    r = await client.post(f"/api/v1/demo/homes/{key}/view", headers=visitor)
    assert r.status_code == 404


async def test_a_member_of_a_real_home_is_not_made_a_viewer(client, seeded, make_member):
    member = await make_member(role="member")
    r = await client.post("/api/v1/demo/homes/2/view", headers=member.headers)
    assert r.status_code == 409
    assert r.json()["code"] == "demo_not_for_members"
    current = await client.get("/api/v1/homes/current", headers=member.headers)
    assert (current.json()["id"], current.json()["role"]) == (str(member.home_id), "member")


async def test_viewing_needs_a_token(client, seeded):
    assert (await client.post("/api/v1/demo/homes/2/view")).status_code == 401


async def test_the_password_grant_is_gone(client, seeded):
    r = await client.post("/api/v1/demo/session", json={"house": "2"})
    assert r.status_code in (404, 405)


WRITES = [
    ("PATCH", "/api/v1/homes/current", {"name": "Mine now"}),
    ("PATCH", f"/api/v1/insights/alerts/{uuid.uuid4()}", {"seen": True}),
    ("POST", f"/api/v1/insights/alerts/{uuid.uuid4()}/feedback", {"verdict": "useful"}),
    ("POST", "/api/v1/insights/watches", {}),
    ("DELETE", f"/api/v1/insights/watches/{uuid.uuid4()}", None),
    ("POST", f"/api/v1/copilot/plans/{uuid.uuid4()}/accept", None),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
async def test_a_viewer_cannot_change_the_home(client, seeded, visitor, method, path, body):
    await client.post("/api/v1/demo/homes/2/view", headers=visitor)
    r = await client.request(method, path, headers=visitor, json=body)
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "home_read_only"


@pytest.mark.parametrize(("method", "path", "body"), WRITES[1:])
async def test_a_member_still_can(client, make_member, method, path, body):
    member = await make_member(role="member")
    r = await client.request(method, path, headers=member.headers, json=body)
    assert r.status_code != 403 or r.json().get("code") != "home_read_only"


async def test_a_viewer_lists_no_watch_of_the_demo_home(client, seeded, visitor):
    # Watches are their setter's: a viewer's list is empty, so the web shows it no cancel button.
    owner = seeded[0]
    body = {"metric": "power_w", "op": "gt", "threshold": 100000, "label": "Công suất"}
    r = await client.post("/api/v1/insights/watches", headers=owner.headers, json=body)
    assert r.status_code == 201, r.text
    await client.post("/api/v1/demo/homes/2/view", headers=visitor)
    r = await client.get("/api/v1/insights/watches", headers=visitor)
    assert r.status_code == 200 and r.json() == []
    assert len((await client.get("/api/v1/insights/watches", headers=owner.headers)).json()) == 1


async def test_a_viewer_keeps_its_own_settings_and_chats(client, seeded, visitor):
    await client.post("/api/v1/demo/homes/2/view", headers=visitor)
    r = await client.patch(
        "/api/v1/users/me/preferences", headers=visitor, json={"weekly_summary": False}
    )
    assert r.status_code == 200
    assert (await client.get("/api/v1/copilot/conversations", headers=visitor)).status_code == 200
