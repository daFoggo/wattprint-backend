from collections import defaultdict, deque
from urllib.parse import parse_qs

import httpx
import pytest

from app.config import settings
from app.modules.auth.services import demo

TOKENS = {
    "access_token": "acc",
    "refresh_token": "ref",
    "id_token": "idt",
    "expires_in": 300,
    "refresh_expires_in": 1800,
}


@pytest.fixture
async def seeded(tmp_path, monkeypatch, client, make_member):
    """A toml with house 2 (its owner is a member of a home) and house 5 (owner never seeded)."""
    owner = await make_member()
    email = (await client.get("/api/v1/users/me", headers=owner.headers)).json()["email"]
    toml = tmp_path / "demo_homes.toml"
    toml.write_text(
        f"""
[[home]]
house = 2
owner = {{ email = "{email}", name = "REFIT House 2" }}
devices = {{ Fridge = "Fridge-Freezer", Kettle = "Kettle", Other = "Other" }}

[[home]]
house = 5
key = "5-heat"
name = "REFIT House 5 heat"
owner = {{ email = "nobody.{owner.user_id}@wattprint.local", name = "x" }}
devices = {{ Kettle = "Kettle" }}
"""
    )
    monkeypatch.setattr(settings, "demo_homes_file", str(toml))
    monkeypatch.setattr(settings, "demo_password", "Demo-pass-123")
    monkeypatch.setattr(settings, "wattprint_web_client_secret", "web-secret")
    monkeypatch.setattr(demo, "_sessions", defaultdict(deque))  # the rate windows are process-wide
    monkeypatch.setattr(settings, "demo_admin_client_secret", "")
    return email


def dashboard(visitor: str = "203.0.113.7") -> dict[str, str]:
    """Headers the dashboard sends: its client secret and the visitor's address."""
    return {"X-Demo-Secret": "web-secret", "X-Demo-Visitor": visitor}


async def sign_in(client, house: str = "2", **headers):
    return await client.post(
        "/api/v1/demo/session", json={"house": house}, headers=headers or dashboard()
    )


def keycloak(monkeypatch, handler):
    """Replaces Keycloak with `handler`; returns the list of requests it got."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(demo, "_transport", httpx.MockTransport(record))
    return seen


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
        }
    ]
    assert "@" not in r.text


async def test_session_posts_password_grant_for_owner(client, seeded, monkeypatch):
    seen = keycloak(monkeypatch, lambda _: httpx.Response(200, json={**TOKENS, "scope": "x"}))
    r = await sign_in(client)
    assert r.status_code == 200
    assert r.json() == TOKENS
    assert len(seen) == 1
    assert str(seen[0].url) == settings.token_url
    form = {k: v[0] for k, v in parse_qs(seen[0].content.decode()).items()}
    assert form == {
        "grant_type": "password",
        "client_id": "wattprint-web",
        "client_secret": "web-secret",
        "username": seeded,
        "password": "Demo-pass-123",
        "scope": "openid profile email roles",
    }


@pytest.mark.parametrize("house", ["9", "5-heat"])
async def test_session_unknown_or_unseeded_404(client, seeded, monkeypatch, house):
    seen = keycloak(monkeypatch, lambda _: httpx.Response(200, json=TOKENS))
    r = await sign_in(client, house)
    assert r.status_code == 404
    assert seen == []


async def test_session_keycloak_rejects_503(client, seeded, monkeypatch):
    body = {"error": "invalid_grant", "error_description": "Invalid user credentials"}
    keycloak(monkeypatch, lambda _: httpx.Response(401, json=body))
    r = await sign_in(client)
    assert r.status_code == 503
    assert "invalid_grant" not in r.text


async def test_session_keycloak_unreachable_503(client, seeded, monkeypatch):
    def down(request):
        raise httpx.ConnectError("refused", request=request)

    keycloak(monkeypatch, down)
    r = await sign_in(client)
    assert r.status_code == 503


async def test_session_unconfigured_503(client, seeded, monkeypatch):
    seen = keycloak(monkeypatch, lambda _: httpx.Response(200, json=TOKENS))
    monkeypatch.setattr(settings, "demo_password", "")
    r = await sign_in(client)
    assert r.status_code == 503
    assert seen == []


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Demo-Visitor": "203.0.113.7"},
        {"X-Demo-Secret": "wrong", "X-Demo-Visitor": "203.0.113.7"},
    ],
)
async def test_session_needs_the_dashboard_secret_403(client, seeded, monkeypatch, headers):
    seen = keycloak(monkeypatch, lambda _: httpx.Response(200, json=TOKENS))
    r = await client.post("/api/v1/demo/session", json={"house": "2"}, headers=headers)
    assert r.status_code == 403
    assert r.json()["code"] == "demo_forbidden"
    assert seen == []


async def test_session_rate_limited_per_visitor_429(client, seeded, monkeypatch):
    seen = keycloak(monkeypatch, lambda _: httpx.Response(200, json=TOKENS))
    for _ in range(demo.SESSIONS_PER_VISITOR):
        assert (await sign_in(client)).status_code == 200
    r = await sign_in(client)
    assert r.status_code == 429
    assert r.json()["code"] == "demo_rate_limited"
    assert r.headers["Retry-After"] == "60"
    # Another visitor is not held back by the first one.
    assert (await sign_in(client, **dashboard("198.51.100.4"))).status_code == 200
    assert len(seen) == demo.SESSIONS_PER_VISITOR + 1


async def test_session_rate_limited_globally_429(client, seeded, monkeypatch):
    # The backstop: many addresses together still open at most this many Keycloak sessions a minute.
    seen = keycloak(monkeypatch, lambda _: httpx.Response(200, json=TOKENS))
    for i in range(demo.SESSIONS_PER_MINUTE):
        assert (await sign_in(client, **dashboard(f"10.0.0.{i}"))).status_code == 200
    r = await sign_in(client, **dashboard("10.0.1.1"))
    assert r.status_code == 429
    assert len(seen) == demo.SESSIONS_PER_MINUTE


async def test_session_unknown_visitor_only_hits_the_global_cap(client, seeded, monkeypatch):
    # No proxy headers reached the dashboard: visitor "" must not alias the global window.
    keycloak(monkeypatch, lambda _: httpx.Response(200, json=TOKENS))
    for _ in range(demo.SESSIONS_PER_MINUTE):
        assert (await sign_in(client, **dashboard(""))).status_code == 200
    assert (await sign_in(client, **dashboard(""))).status_code == 429


def locked_keycloak(monkeypatch, *, user_id="kc-owner-id"):
    """Keycloak where the owner is locked (brute-force protection) until the admin API clears it."""
    state = {"locked": True}

    def handler(request: httpx.Request) -> httpx.Response:
        form = (
            {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if request.content
            else {}
        )
        if request.url.path.endswith("/token") and form.get("grant_type") == "client_credentials":
            assert form["client_id"] == "wattprint-demo-admin"
            assert form["client_secret"] == "admin-secret"
            return httpx.Response(200, json={"access_token": "admin-token"})
        if request.url.path.endswith("/token"):
            if state["locked"]:
                return httpx.Response(401, json={"error": "invalid_grant"})
            return httpx.Response(200, json=TOKENS)
        assert request.headers["Authorization"] == "Bearer admin-token"
        if request.method == "GET" and request.url.path == "/admin/realms/wattprint/users":
            return httpx.Response(200, json=[{"id": user_id, "email": request.url.params["email"]}])
        if (
            request.method == "DELETE"
            and request.url.path
            == f"/admin/realms/wattprint/attack-detection/brute-force/users/{user_id}"
        ):
            state["locked"] = False
            return httpx.Response(204)
        return httpx.Response(404)

    return keycloak(monkeypatch, handler), state


async def test_session_clears_a_lockout_and_retries(client, seeded, monkeypatch):
    monkeypatch.setattr(settings, "demo_admin_client_secret", "admin-secret")
    seen, state = locked_keycloak(monkeypatch)
    r = await sign_in(client)
    assert r.status_code == 200
    assert r.json() == TOKENS
    assert state["locked"] is False
    lookup = next(q for q in seen if q.method == "GET")
    assert lookup.url.params["email"] == seeded
    assert lookup.url.params["exact"] == "true"
    assert [q.method for q in seen] == ["POST", "POST", "GET", "DELETE", "POST"]


async def test_session_without_admin_client_does_not_unlock_503(client, seeded, monkeypatch):
    seen, state = locked_keycloak(monkeypatch)
    r = await sign_in(client)
    assert r.status_code == 503
    assert state["locked"] is True
    assert len(seen) == 1


async def test_session_unlock_failure_503(client, seeded, monkeypatch):
    monkeypatch.setattr(settings, "demo_admin_client_secret", "admin-secret")
    keycloak(monkeypatch, lambda _: httpx.Response(401, json={"error": "invalid_client"}))
    r = await sign_in(client)
    assert r.status_code == 503
