"""Store the recording site's hourly weather (Loughborough, ERA5 through Open-Meteo, no key) for a
demo home, moved onto database time with the home's REFIT shift, like its readings.

    docker compose exec -T api python -m scripts.import_refit_weather --house 2
    docker compose exec -T api python -m scripts.import_refit_weather --house 5-heat
"""

import argparse
import asyncio
import os
from datetime import timedelta
from pathlib import Path

import httpx
import pandas as pd
from sqlalchemy import text

from app.database import SessionLocal
from scripts import refit

URL = "https://archive-api.open-meteo.com/v1/archive"
SITE = {"latitude": 52.7721, "longitude": -1.2062}  # Loughborough, where REFIT recorded
HOURLY = {
    "temperature_2m": "temp_c",
    "relative_humidity_2m": "humidity_pct",
    "apparent_temperature": "apparent_c",
    "cloud_cover": "cloud_pct",
    "shortwave_radiation": "radiation_wm2",
    "precipitation": "precip_mm",
    "is_day": "is_day",
    "wind_speed_10m": "wind_ms",
}
BATCH = 5000


def fetch(start: str, end: str) -> pd.DataFrame:
    params = {
        **SITE,
        "start_date": start,
        "end_date": end,
        "hourly": ",".join(HOURLY),
        "timezone": "UTC",
        "wind_speed_unit": "ms",
    }
    r = httpx.get(URL, params=params, timeout=120)
    r.raise_for_status()
    hourly = r.json()["hourly"]
    frame = pd.DataFrame({HOURLY[k]: hourly[k] for k in HOURLY})
    frame["wall"] = pd.to_datetime(hourly["time"])  # naive UTC, the CSV's clock
    return frame


async def main(key: str) -> None:
    house = int(key.split("-")[0])
    data_dir = Path(os.environ.get("REFIT_SEED_DIR") or "dataset")
    df = refit.load(data_dir / f"CLEAN_House{house}.csv")
    first, last = df["wall"].iloc[0] - timedelta(days=1), df["wall"].iloc[-1] + timedelta(days=1)
    async with SessionLocal() as s:
        row = (
            await s.execute(
                text(
                    "SELECT m.home_id, w.shift_days FROM etl.tb_watermark w "
                    "JOIN public.tb_meter m ON m.serial = :m "
                    "WHERE w.source = :src AND w.segment = :seg"
                ),
                {
                    "m": refit.meter(house, key),
                    "src": refit.source(house, key),
                    "seg": refit.SEGMENT,
                },
            )
        ).first()
    if row is None:
        raise SystemExit(f"home {key} is not seeded: run scripts.seed_demo_homes first")
    weather = fetch(f"{first:%Y-%m-%d}", f"{last:%Y-%m-%d}")
    weather["ts"] = refit.db_time(weather["wall"].to_numpy(), row.shift_days)
    weather["is_day"] = weather["is_day"].astype(bool)
    records = [
        {
            "h": row.home_id,
            "ts": r.ts.to_pydatetime(),
            **{c: (None if pd.isna(getattr(r, c)) else getattr(r, c)) for c in HOURLY.values()},
        }
        for r in weather.itertuples()
    ]
    cols = ", ".join(HOURLY.values())
    sql = text(
        f"INSERT INTO public.tb_home_weather_hourly (home_id, ts, {cols}) "
        f"VALUES (:h, :ts, {', '.join(':' + c for c in HOURLY.values())}) "
        "ON CONFLICT (home_id, ts) DO UPDATE SET "
        + ", ".join(f"{c} = EXCLUDED.{c}" for c in HOURLY.values())
    )
    for i in range(0, len(records), BATCH):
        async with SessionLocal() as s, s.begin():
            await s.execute(sql, records[i : i + BATCH])
    print(f"home {key}: {len(records)} hours, {weather['wall'].min()} .. {weather['wall'].max()}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--house", required=True, help='the home key in demo_homes.toml: "2", "5-heat"')
    asyncio.run(main(p.parse_args().house))
