import json
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


# --- Guest accounts: one click from the sign-in page into a demo home (POST .../guest) ---

GUEST_HEADERS = {"X-Demo-Secret": "web-secret", "X-Demo-Visitor": "203.0.113.7"}


@pytest.fixture
def keycloak(monkeypatch, make_token):
    """Keycloak admin API and token endpoint, recorded; `refuse_grant` fails the password grant."""
    import httpx

    from app.modules.auth.services import demo

    class Kc:
        calls: list = []
        created: list = []
        deleted: list = []
        refuse_grant = False

    def handle(request: httpx.Request) -> httpx.Response:
        Kc.calls.append(request)
        url = str(request.url)
        if url.endswith("/token"):
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            if form["grant_type"] == "client_credentials":
                return httpx.Response(200, json={"access_token": "admin-token"})
            if Kc.refuse_grant:
                return httpx.Response(401, json={"error": "invalid_grant"})
            sub, email = Kc.created[-1]
            access = make_token(sub=sub, email=email, email_verified=True, name="Khách demo")
            return httpx.Response(
                200,
                json={
                    "access_token": access,
                    "refresh_token": "ref",
                    "id_token": "idt",
                    "expires_in": 300,
                    "refresh_expires_in": 1800,
                },
            )
        if request.method == "POST" and url.endswith("/users"):
            body = json.loads(request.content)
            sub = str(uuid.uuid4())
            Kc.created.append((sub, body["email"]))
            return httpx.Response(201, headers={"Location": f"{url}/{sub}"})
        if request.method == "DELETE" and "/users/" in url:
            Kc.deleted.append(url.rsplit("/", 1)[-1])
            return httpx.Response(204)
        return httpx.Response(404)

    Kc.calls, Kc.created, Kc.deleted = [], [], []
    monkeypatch.setattr(demo, "_transport", httpx.MockTransport(handle))
    monkeypatch.setattr(settings, "wattprint_web_client_secret", "web-secret")
    monkeypatch.setattr(settings, "demo_admin_client_secret", "admin-secret")
    demo._sessions.clear()
    yield Kc
    demo._sessions.clear()


async def _drop_guests():
    from app.database import SessionLocal

    async with SessionLocal() as s, s.begin():
        await s.execute(
            text("DELETE FROM public.tb_users WHERE email LIKE '%@guest.wattprint.local'")
        )


@pytest.fixture
async def no_guests():
    await _drop_guests()
    yield
    await _drop_guests()


async def test_a_guest_is_made_and_signed_in_as_a_viewer_of_the_home(
    client, seeded, keycloak, no_guests
):
    r = await client.post("/api/v1/demo/homes/2/guest", headers=GUEST_HEADERS)
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert set(tokens) == {
        "access_token",
        "refresh_token",
        "id_token",
        "expires_in",
        "refresh_expires_in",
    }
    [(sub, email)] = keycloak.created
    assert email.endswith("@guest.wattprint.local")
    created = json.loads(next(c for c in keycloak.calls if c.url.path.endswith("/users")).content)
    password = created["credentials"][0]["value"]
    assert password not in r.text
    assert created["emailVerified"] is True
    me = {"Authorization": f"Bearer {tokens['access_token']}"}
    current = await client.get("/api/v1/homes/current", headers=me)
    assert (current.json()["id"], current.json()["role"]) == (str(seeded[0].home_id), "viewer")
    assert keycloak.deleted == []


@pytest.mark.parametrize("headers", [{}, {"X-Demo-Secret": "wrong"}])
async def test_a_guest_needs_the_dashboard_secret(client, seeded, keycloak, headers):
    r = await client.post("/api/v1/demo/homes/2/guest", headers=headers)
    assert r.status_code == 403
    assert keycloak.calls == []


async def test_a_guest_for_an_unknown_home_404(client, seeded, keycloak):
    r = await client.post("/api/v1/demo/homes/9/guest", headers=GUEST_HEADERS)
    assert r.status_code == 404
    assert keycloak.created == []


async def test_a_refused_grant_deletes_the_new_account(client, seeded, keycloak, no_guests):
    keycloak.refuse_grant = True
    r = await client.post("/api/v1/demo/homes/2/guest", headers=GUEST_HEADERS)
    assert r.status_code == 503
    assert keycloak.deleted == [keycloak.created[0][0]]


async def test_guests_older_than_a_day_are_deleted(client, seeded, keycloak, no_guests):
    from app.database import SessionLocal

    old_sub = str(uuid.uuid4())
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO public.tb_users (keycloak_sub, email, created_at) "
                "VALUES (:s, :e, now() - interval '25 hours')"
            ),
            {"s": old_sub, "e": f"guest-old{old_sub[:6]}@guest.wattprint.local"},
        )
    r = await client.post("/api/v1/demo/homes/2/guest", headers=GUEST_HEADERS)
    assert r.status_code == 200
    assert old_sub in keycloak.deleted
    async with SessionLocal() as s:
        left = await s.scalar(
            text("SELECT count(*) FROM public.tb_users WHERE keycloak_sub = :s"), {"s": old_sub}
        )
    assert left == 0


async def test_guests_are_capped(client, seeded, keycloak, no_guests, monkeypatch):
    from app.modules.auth.services import demo

    monkeypatch.setattr(demo, "GUESTS_MAX", 0)
    r = await client.post("/api/v1/demo/homes/2/guest", headers=GUEST_HEADERS)
    assert (r.status_code, r.json()["code"]) == (503, "demo_full")
    assert keycloak.created == []


async def test_guests_are_rate_limited_per_visitor(
    client, seeded, keycloak, no_guests, monkeypatch
):
    from app.modules.auth.services import demo

    monkeypatch.setattr(demo, "GUESTS_PER_VISITOR", 1)
    r = await client.post("/api/v1/demo/homes/2/guest", headers=GUEST_HEADERS)
    assert r.status_code == 200
    r = await client.post("/api/v1/demo/homes/2/guest", headers=GUEST_HEADERS)
    assert r.status_code == 429
    other = {**GUEST_HEADERS, "X-Demo-Visitor": "198.51.100.9"}
    assert (await client.post("/api/v1/demo/homes/2/guest", headers=other)).status_code == 200


async def test_a_refused_token_check_answers_503_and_deletes_the_account(
    client, seeded, keycloak, no_guests, monkeypatch
):
    import jwt

    from app.modules.auth.services import demo

    def refuse(_token):
        raise jwt.InvalidIssuerError("issuer drift")

    monkeypatch.setattr(demo, "decode_access_token", refuse)
    r = await client.post("/api/v1/demo/homes/2/guest", headers=GUEST_HEADERS)
    assert (r.status_code, r.json()["code"]) == (503, "demo_unavailable")
    assert keycloak.deleted == [keycloak.created[0][0]]
