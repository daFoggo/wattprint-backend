import pytest

from app.config import settings
from app.modules.energy.services import weather as svc

CURRENT = {
    "dt": 1_763_500_000,
    "main": {"temp": 27.4, "feels_like": 30.1, "humidity": 78},
    "wind": {"speed": 2.6},
    "weather": [{"description": "mây rải rác", "icon": "03d"}],
}
FORECAST = {
    "list": [
        {
            "dt": 1_763_500_000 + 10_800 * i,
            "main": {"temp": 26 + i},
            "pop": i / 10,
            "weather": [{"description": "mưa nhẹ", "icon": "10d"}],
        }
        for i in range(10)
    ]
}


@pytest.fixture
def openweather(monkeypatch):
    calls = []

    async def fake(lat, lon, lang):
        calls.append((lat, lon, lang))
        return svc.parse(CURRENT, FORECAST)

    monkeypatch.setattr(settings, "openweather_api_key", "test-key")
    monkeypatch.setattr(svc, "_fetch", fake)
    svc._cache.clear()
    return calls


async def test_weather_at_the_home_province_cached(client, make_member, openweather):
    owner = await make_member("owner", province_code="79")
    r = await client.get("/api/v1/energy/weather?lang=vi", headers=owner.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["province"] == "Hồ Chí Minh"
    assert body["now"] == {
        "dt": 1_763_500_000,
        "temp": 27.4,
        "feels_like": 30.1,
        "humidity": 78,
        "wind_speed": 2.6,
        "sky": {"description": "mây rải rác", "icon": "03d"},
    }
    assert len(body["next"]) == 8 and body["next"][1]["pop"] == 0.1
    await client.get("/api/v1/energy/weather?lang=vi", headers=owner.headers)
    assert len(openweather) == 1  # second call served from the cache
    assert str(openweather[0][0]) == "10.77690"


async def test_weather_needs_a_province(client, make_member, openweather):
    owner = await make_member("owner")
    r = await client.get("/api/v1/energy/weather", headers=owner.headers)
    assert r.status_code == 404 and r.json()["code"] == "home_location_unset"


async def test_weather_without_a_key_is_503(client, make_member, monkeypatch):
    monkeypatch.setattr(settings, "openweather_api_key", "")
    owner = await make_member("owner", province_code="01")
    r = await client.get("/api/v1/energy/weather", headers=owner.headers)
    assert r.status_code == 503 and r.json()["code"] == "weather_unavailable"


def test_an_unexpected_answer_is_unavailable_not_a_crash():
    with pytest.raises(svc.WeatherUnavailableError):
        svc.parse({"dt": 1}, FORECAST)
    with pytest.raises(svc.WeatherUnavailableError):
        svc.parse(CURRENT, {"list": []})
