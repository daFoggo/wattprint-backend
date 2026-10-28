from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_me_requires_auth():
    assert client.get("/api/v1/me").status_code == 401


def test_openapi_served():
    assert client.get("/openapi.json").json()["info"]["title"] == "Wattprint API"
