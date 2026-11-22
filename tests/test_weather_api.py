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


async def test_demo_home_weather_comes_from_the_recording_site(client, make_member):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    from app.database import SessionLocal

    owner = await make_member("owner")
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    async with SessionLocal() as s, s.begin():
        for i in range(-1, 26):
            await s.execute(
                text(
                    "INSERT INTO public.tb_home_weather_hourly (home_id, ts, temp_c, humidity_pct, "
                    "apparent_c, cloud_pct, radiation_wm2, precip_mm, is_day, wind_ms) "
                    "VALUES (:h, :t, :c, 81, :c, 90, 0, :p, false, 4.5)"
                ),
                {
                    "h": owner.home_id,
                    "t": hour + timedelta(hours=i),
                    "c": 5.0 + i,
                    "p": 1.0 if i == 3 else 0.0,
                },
            )
    r = await client.get("/api/v1/energy/weather?lang=vi", headers=owner.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["province"] == "Nơi ghi dữ liệu (Loughborough, Anh)"
    assert body["now"]["temp"] == 5.0 and body["now"]["humidity"] == 81
    assert body["now"]["wind_speed"] == 4.5
    assert body["now"]["sky"]["icon"] == "04n"
    assert len(body["next"]) == 8
    assert body["next"][0]["sky"]["icon"] == "10n" and body["next"][0]["pop"] == 1.0
    en = await client.get("/api/v1/energy/weather?lang=en", headers=owner.headers)
    assert en.json()["province"] == "Recording site (Loughborough, UK)"


async def test_the_card_shows_the_cold_spell_the_model_uses(client, make_member):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    from app.database import SessionLocal

    owner = await make_member("owner")
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    async with SessionLocal() as s, s.begin():
        for i in range(0, 26):
            await s.execute(
                text(
                    "INSERT INTO public.tb_home_weather_hourly (home_id, ts, temp_c, humidity_pct, "
                    "apparent_c, cloud_pct, radiation_wm2, precip_mm, is_day, wind_ms) "
                    "VALUES (:h, :t, 10, 80, 10, 0, 0, 0, true, 1)"
                ),
                {"h": owner.home_id, "t": hour + timedelta(hours=i)},
            )
        await s.execute(
            text(
                "INSERT INTO public.tb_demo_scenario (home_id, name, starts_at, ends_at, params, "
                "train) VALUES (:h, 'cold_spell', :a, :b, '{\"delta_c\": 8}', false)"
            ),
            {"h": owner.home_id, "a": hour - timedelta(hours=1), "b": hour + timedelta(days=2)},
        )
    body = (await client.get("/api/v1/energy/weather", headers=owner.headers)).json()
    assert body["now"]["temp"] == 2.0 and body["next"][0]["temp"] == 2.0
