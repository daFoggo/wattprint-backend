import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.nilm.services import runner, windows

W = 16
HISTORY = timedelta(days=30)


@dataclass
class FakeBundle:
    """Output depends on the bin's place in its window, so slicing differences would show."""

    labels = ["Fridge", "Kettle"]
    window = W

    def predict(self, x: np.ndarray) -> np.ndarray:
        agg = x[:, 0]  # (B, W)
        ramp = 1.0 + np.arange(W) / W
        return np.stack([0.4 * agg * ramp, 0.5 * agg / ramp], axis=1)


def samples(start: datetime, minutes: int, gaps: list[tuple[int, int]]) -> list[tuple]:
    """8 s readings with a slow wave, minus [a, b) second ranges."""
    out = []
    for s in range(0, minutes * 60, 8):
        if any(a <= s < b for a, b in gaps):
            continue
        out.append((start + timedelta(seconds=s), 300 + 200 * np.sin(s / 600) + (s % 97)))
    return out


@pytest.fixture
async def engine(throwaway_dsn):
    eng = create_async_engine(throwaway_dsn)
    try:
        yield eng
    finally:
        await eng.dispose()


async def make_home(engine, name: str, rows: list[tuple]) -> runner.Target:
    async with engine.begin() as c:
        home = await c.scalar(
            text("INSERT INTO public.tb_home (name) VALUES (:n) RETURNING id"), {"n": name}
        )
        series = await c.scalar(
            text(
                "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
                "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
            ),
            {"h": home},
        )
        await c.execute(
            text(
                "INSERT INTO public.tb_nilm_model (home_id, name, version, artifact) "
                "VALUES (:h, 'fake', 'v1', 'fake.pt')"
            ),
            {"h": home},
        )
    await add_readings(engine, series, rows)
    return runner.Target(home, "Asia/Ho_Chi_Minh", series, "fake", "v1", "fake.pt")


async def add_readings(engine, series: uuid.UUID, rows: list[tuple]) -> None:
    async with engine.begin() as c:
        await c.execute(
            text("INSERT INTO public.tb_reading (ts, series_id, value) VALUES (:t, :s, :v)"),
            [{"t": t, "s": series, "v": float(v)} for t, v in rows],
        )


async def estimates(engine, home: uuid.UUID) -> pd.DataFrame:
    async with engine.connect() as c:
        rows = (
            await c.execute(
                text(
                    "SELECT e.ts, d.device_type_code AS code, e.value "
                    "FROM public.tb_device_estimate e JOIN public.tb_series s USING (series_id) "
                    "JOIN public.tb_device d ON d.id = s.device_id "
                    "WHERE s.home_id = :h ORDER BY 1, 2"
                ),
                {"h": home},
            )
        ).all()
    return pd.DataFrame(rows, columns=["ts", "code", "value"]).pivot(index="ts", columns="code")


async def checkpoint(engine, series: uuid.UUID):
    async with engine.connect() as c:
        return await c.scalar(
            text(
                "SELECT last_ts FROM public.tb_ingest_checkpoint "
                "WHERE source = 'nilm' AND series_id = :s"
            ),
            {"s": series},
        )


def run(engine, t, load=lambda _p: FakeBundle()):
    return runner.run_home(engine, t, load, Path("/models"), HISTORY)


async def test_catch_up_in_pieces_equals_one_pass_and_balances(engine, monkeypatch):
    monkeypatch.setattr(runner, "CHUNK", timedelta(minutes=20))
    start = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(hours=4)  # 15 s aligned
    rows = samples(start, 120, gaps=[(1800, 1830), (3600, 3900)])  # a 30 s gap and a 5 min gap
    whole = await make_home(engine, "whole", rows)
    pieces = await make_home(engine, "pieces", rows[: len(rows) // 2])

    assert await run(engine, whole) > 0
    assert await run(engine, pieces) > 0
    first_cp = await checkpoint(engine, pieces.main_series)
    await add_readings(engine, pieces.main_series, rows[len(rows) // 2 :])
    assert await run(engine, pieces) > 0
    assert await checkpoint(engine, pieces.main_series) > first_cp

    a, b = await estimates(engine, whole.home_id), await estimates(engine, pieces.home_id)
    assert len(a) > 0 and list(a.index) == list(b.index)
    assert np.allclose(a.to_numpy(), b.to_numpy(), atol=1e-3)  # float4 storage

    ts = pd.DatetimeIndex([t for t, _ in rows])
    agg = windows.fill_short_gaps(windows.grid(ts, np.array([v for _, v in rows])))
    total = a.sum(axis=1).to_numpy()
    expected = agg.reindex(pd.DatetimeIndex(a.index).tz_convert(UTC)).to_numpy()
    assert np.allclose(total, expected, rtol=1e-5, atol=1e-2)  # devices + other == aggregate
    gap = (a.index >= start + timedelta(seconds=3615)) & (a.index < start + timedelta(seconds=3885))
    assert not gap.any()  # the 5 min gap stays without estimates


async def test_rerun_without_new_readings_is_a_no_op(engine):
    rows = samples(datetime.now(UTC) - timedelta(hours=2), 30, [])
    t = await make_home(engine, "idle", rows)
    assert await run(engine, t) > 0
    assert await run(engine, t) == 0
    async with engine.connect() as c:
        runs = await c.scalar(
            text("SELECT count(*) FROM public.tb_inference_run WHERE home_id = :h"),
            {"h": t.home_id},
        )
    assert runs == 1


async def test_failure_marks_the_run_and_leaves_checkpoint_and_readings(engine):
    rows = samples(datetime.now(UTC) - timedelta(hours=2), 30, [])
    t = await make_home(engine, "broken", rows)

    class Boom(FakeBundle):
        def predict(self, x):
            raise RuntimeError("model blew up")

    with pytest.raises(RuntimeError):
        await run(engine, t, load=lambda _p: Boom())
    async with engine.connect() as c:
        status, error = (
            await c.execute(
                text("SELECT status, error FROM public.tb_inference_run WHERE home_id = :h"),
                {"h": t.home_id},
            )
        ).one()
        n = await c.scalar(
            text("SELECT count(*) FROM public.tb_reading WHERE series_id = :s"),
            {"s": t.main_series},
        )
    assert status == "failed" and "model blew up" in error
    assert n == len(rows)
    assert await checkpoint(engine, t.main_series) is None
    assert await run(engine, t) > 0  # recovers on the next pass


async def test_a_home_held_by_another_worker_is_skipped(engine):
    t = await make_home(engine, "locked", samples(datetime.now(UTC) - timedelta(hours=2), 30, []))
    async with engine.connect() as other:
        assert await other.scalar(runner.LOCK, {"k": f"nilm:{t.home_id}"})
        assert await run(engine, t) == 0
        await other.execute(runner.UNLOCK, {"k": f"nilm:{t.home_id}"})
    assert await run(engine, t) > 0
