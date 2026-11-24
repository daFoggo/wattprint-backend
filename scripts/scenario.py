"""Start, stop and list demo scenarios on a demo home (applied by scripts.replay_refit).

    docker compose exec -T api python -m scripts.scenario start --house 5-heat --name cold_spell \\
        --hours 48 --param delta_c=8
    docker compose exec -T api python -m scripts.scenario stop --house 2 --name forgotten_load
    docker compose exec -T api python -m scripts.scenario list
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.database import SessionLocal
from scripts import refit

EVENTS = (
    "forgotten_load",
    "base_up",
    "away",
    "cold_spell",
    "echo_run",
)  # the heater comes from the seed


async def _home(s, key: str):
    house = int(key.split("-")[0])
    home_id = await s.scalar(
        text("SELECT home_id FROM public.tb_meter WHERE serial = :m"),
        {"m": refit.meter(house, key)},
    )
    if home_id is None:
        raise SystemExit(f"no demo home {key}")
    return home_id


async def _shape(s, home_id, device_type: str) -> list[float]:
    """The main meter's watts over the base, per minute, of the device's latest run lasting
    about its median: what the meter saw while that device ran."""
    run = (
        await s.execute(
            text(
                "WITH r AS (SELECT c.start_ts, c.end_ts, c.end_ts - c.start_ts AS len "
                "FROM public.tb_device_cycle c JOIN public.tb_device d ON d.id = c.device_id "
                "WHERE c.home_id = :h AND d.device_type_code = :t), "
                "m AS (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM len)) "
                "AS med FROM r) "
                "SELECT start_ts, end_ts FROM r, m ORDER BY abs(extract(epoch FROM len) - m.med), "
                "start_ts DESC LIMIT 1"
            ),
            {"h": home_id, "t": device_type},
        )
    ).first()
    if run is None:
        raise SystemExit(f"no run of a {device_type!r} in this home yet")
    minutes = (
        (
            await s.execute(
                text(
                    "SELECT r.avg_w FROM public.reading_1m r "
                    "JOIN public.tb_series x USING (series_id) WHERE x.home_id = :h "
                    "AND x.kind = 'main' AND r.bucket >= :a AND r.bucket < :b "
                    "ORDER BY r.bucket"
                ),
                {"h": home_id, "a": run.start_ts, "b": run.end_ts},
            )
        )
        .scalars()
        .all()
    )
    if not minutes:
        raise SystemExit("no meter readings for that run")
    base = min(minutes)
    return [round(float(w) - float(base)) for w in minutes]


async def main(a: argparse.Namespace) -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as s, s.begin():
        if a.cmd == "start":
            raw = dict(p.split("=", 1) for p in a.param)
            params = {k: float(v) for k, v in raw.items() if k != "device"}
            if a.name == "echo_run":
                params["shape"] = await _shape(s, await _home(s, a.house), raw.get("device", ""))
            await s.execute(
                text(
                    "INSERT INTO public.tb_demo_scenario "
                    "(home_id, name, starts_at, ends_at, params, "
                    "train) VALUES (:h, :n, :a, :b, CAST(:p AS jsonb), false)"
                ),
                {
                    "h": await _home(s, a.house),
                    "n": a.name,
                    "a": now,
                    "b": now + timedelta(hours=a.hours) if a.hours else None,
                    "p": json.dumps(params),
                },
            )
            print(f"{a.name} on home {a.house} from {now:%Y-%m-%d %H:%M} UTC")
        elif a.cmd == "stop":
            n = await s.execute(
                text(
                    "UPDATE public.tb_demo_scenario SET ends_at = :t WHERE home_id = :h "
                    "AND name = :n AND train = false AND starts_at < :t "
                    "AND (ends_at IS NULL OR ends_at > :t)"
                ),
                {"h": await _home(s, a.house), "n": a.name, "t": now},
            )
            print(f"stopped {n.rowcount}")
        else:
            for r in await s.execute(
                text(
                    "SELECT m.serial, d.name, d.starts_at, d.ends_at, d.params, d.train "
                    "FROM public.tb_demo_scenario d JOIN public.tb_meter m USING (home_id) "
                    "ORDER BY d.starts_at"
                )
            ):
                print(r.serial, r.name, r.starts_at, r.ends_at, dict(r.params), r.train)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["start", "stop", "list"])
    p.add_argument("--house")
    p.add_argument("--name", choices=EVENTS)
    p.add_argument("--hours", type=float)
    p.add_argument("--param", action="append", default=[], help="k=v; echo_run: device=<type>")
    asyncio.run(main(p.parse_args()))
