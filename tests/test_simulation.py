"""Tests of the NILM replay that need no database."""

import datetime as dt
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.ml import NILM_APPLIANCES, WINDOW
from app.services.disaggregation import accuracy_pct, local_day_start, local_today
from app.services.simulation import Item, Job, job_out, load_day, replay_shift

SAMPLE = Path(__file__).parent / "data" / "refit_sample.csv"
UTC = dt.UTC


def test_local_day_starts_at_17_utc_the_day_before():
    assert local_day_start(dt.date(2026, 11, 2)) == dt.datetime(2026, 11, 1, 17, tzinfo=UTC)


def test_local_today_follows_utc_plus_7():
    assert local_today(dt.datetime(2026, 11, 1, 16, 59, tzinfo=UTC)) == dt.date(2026, 11, 1)
    assert local_today(dt.datetime(2026, 11, 1, 17, 0, tzinfo=UTC)) == dt.date(2026, 11, 2)


def test_replay_shift_maps_source_midnight_to_local_midnight():
    shift = replay_shift(dt.date(2015, 1, 5), dt.date(2026, 11, 2))
    assert dt.datetime(2015, 1, 5, tzinfo=UTC) + shift == local_day_start(dt.date(2026, 11, 2))
    # whole days plus the UTC+7 offset: weekday and time of day only move by that offset
    assert (shift + dt.timedelta(hours=7)) % dt.timedelta(days=1) == dt.timedelta(0)


def test_accuracy_pct():
    assert accuracy_pct(0.0, 100.0) == 100.0
    assert accuracy_pct(100.0, 100.0) == 50.0
    assert accuracy_pct(200.0, 100.0) == 0.0
    assert accuracy_pct(500.0, 100.0) == 0.0  # clipped, never negative
    assert accuracy_pct(10.0, 0.0) is None  # no sub-meter signal, no accuracy


def test_load_day_builds_a_context_plus_day_grid_with_gaps():
    channels = {"kettle": "Appliance8", "washing_machine": "Appliance2"}
    data = load_day(SAMPLE, dt.date(2013, 10, 9), channels)

    assert len(data.grid) == (WINDOW - 1) + 24 * 60
    assert data.grid[0] == pd.Timestamp("2013-10-08 19:45", tz="UTC")  # 255 minutes of context
    assert len(data.aggregate) == len(data.grid)
    # the sample holds 300 readings of that day, 13:06-13:36: 31 contiguous minutes with a value
    present = ~np.isnan(data.aggregate)
    first, last = np.flatnonzero(present)[[0, -1]]
    assert data.grid[first] == pd.Timestamp("2013-10-09 13:06", tz="UTC")
    assert data.grid[last] == pd.Timestamp("2013-10-09 13:36", tz="UTC")
    assert present.sum() == last - first + 1 == 31  # no hole inside the span
    assert not present[: WINDOW - 1].any()  # the context before the day is empty in the sample
    assert 0 <= data.aggregate[present].min() and data.aggregate[present].max() <= 10_000
    assert set(data.truth) == set(channels)
    for series in data.truth.values():
        assert len(series) == len(data.grid)
        assert not np.isnan(series).any()  # missing sub-meter minutes are 0
    assert data.truth["washing_machine"].max() > 0  # Appliance2 draws power in the sample
    assert data.truth["kettle"].max() == 0  # Appliance8 never does


def test_load_day_without_data_raises():
    with pytest.raises(ValueError, match="no data"):
        load_day(SAMPLE, dt.date(2020, 1, 1), {"kettle": "Appliance8"})


def test_job_out_reports_progress():
    job = Job(
        run_id=7,
        home_id=uuid.uuid4(),
        house=2,
        source_date=dt.date(2015, 1, 5),
        replay_date=dt.date(2026, 11, 1),
        rows_per_second=10.0,
        csv_path=SAMPLE,
        meter="REFIT-H2",
        main_series=1,
        items=[Item("kettle", uuid.uuid4(), "Appliance8", 2, 3)],
        shift=dt.timedelta(0),
        status="running",
        total_minutes=200,
        done_minutes=50,
    )
    out = job_out(job)
    assert (out.id, out.status, out.progress_pct) == (7, "running", 25.0)


def test_nilm_appliances_match_the_checkpoints():
    pytest.importorskip("torch")
    from app.ml.nilm import CKPT_FILES

    assert tuple(CKPT_FILES) == NILM_APPLIANCES


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/simulations"),
        ("get", "/api/v1/simulations/1"),
        ("delete", "/api/v1/simulations/1"),
        ("get", "/api/v1/simulations/1/result"),
        ("get", "/api/v1/disaggregation?date=2026-11-01"),
        ("get", "/api/v1/disaggregation/latest"),
    ],
)
async def test_endpoints_require_a_token(client, method, path):
    kwargs = {"json": {"date": "2015-01-05"}} if method == "post" else {}
    r = await getattr(client, method)(path, **kwargs)
    assert r.status_code == 401


async def test_openapi_lists_the_replay_endpoints(client):
    paths = (await client.get("/openapi.json")).json()["paths"]
    assert {"get", "delete"} <= set(paths["/api/v1/simulations/{simulation_id}"])
    assert "/api/v1/simulations" in paths
    assert "/api/v1/simulations/{simulation_id}/result" in paths
    assert "/api/v1/disaggregation" in paths
    assert "/api/v1/disaggregation/latest" in paths
