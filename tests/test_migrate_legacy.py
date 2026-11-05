"""Tests of the legacy data migration that need no database."""

import datetime as dt

import pytest

from app.cli.migrate_legacy import Legacy, main, make_plan, parse_ts, read_legacy
from app.services.disaggregation import local_day_start

UTC = dt.UTC
TODAY = dt.date(2026, 11, 5)


def _write(path, header, rows):
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_parse_ts_reads_psql_timestamptz():
    assert parse_ts("2015-01-05 00:00:00+00") == dt.datetime(2015, 1, 5, tzinfo=UTC)
    assert parse_ts("2015-01-05 07:00:00+07") == dt.datetime(2015, 1, 5, tzinfo=UTC)
    assert parse_ts("2015-01-05 00:00:00+00:00") == dt.datetime(2015, 1, 5, tzinfo=UTC)
    with pytest.raises(ValueError, match="time zone"):
        parse_ts("2015-01-05 00:00:00")


def test_read_legacy_merges_houses_and_the_highest_id_wins(tmp_path):
    _write(
        tmp_path / "aggregate_power.csv",
        "ts,house_id,watts",
        [
            "2015-01-05 00:00:00+00,99,11",  # listed first on purpose: ids decide, not order
            "2015-01-05 00:00:00+00,2,10",
            "2015-01-05 00:01:00+00,2,20",
        ],
    )
    _write(
        tmp_path / "appliance_power.csv",
        "ts,house_id,appliance,watts",
        ["2015-01-05 00:00:00+00,2,kettle,1", "2015-01-05 00:00:00+00,99,kettle,2"],
    )
    _write(
        tmp_path / "appliance_truth.csv",
        "ts,house_id,appliance,watts",
        ["2015-01-05 00:00:00+00,99,kettle,5"],
    )
    legacy = read_legacy(tmp_path)

    t0 = dt.datetime(2015, 1, 5, tzinfo=UTC)
    assert legacy.houses == [2, 99]
    assert legacy.aggregate == {t0: 11.0, t0 + dt.timedelta(minutes=1): 20.0}
    assert legacy.estimates == {(t0, "kettle"): 2.0}
    assert legacy.truth == {(t0, "kettle"): 5.0}


def _legacy(first: dt.date, last: dt.date) -> Legacy:
    at = lambda d: dt.datetime.combine(d, dt.time(12), tzinfo=UTC)  # noqa: E731
    return Legacy(aggregate={at(first): 1.0, at(last): 2.0}, houses=[2])


def test_plan_stores_the_last_source_day_under_replay_end():
    legacy = _legacy(dt.date(2015, 1, 5), dt.date(2015, 1, 11))
    replay_end = dt.date(2026, 11, 4)
    plan = make_plan(legacy, replay_end, TODAY)

    assert (plan.first_day, plan.last_day) == (dt.date(2015, 1, 5), dt.date(2015, 1, 11))
    assert (plan.first_target, plan.last_target) == (dt.date(2026, 10, 29), replay_end)
    # the last source day starts, once shifted, at local midnight of replay_end
    assert dt.datetime(2015, 1, 11, tzinfo=UTC) + plan.shift == local_day_start(replay_end)
    # and the first one 6 days earlier
    assert dt.datetime(2015, 1, 5, tzinfo=UTC) + plan.shift == local_day_start(
        dt.date(2026, 10, 29)
    )


def test_plan_refuses_a_future_replay_end_and_data_the_retention_would_drop():
    legacy = _legacy(dt.date(2015, 1, 5), dt.date(2015, 1, 11))
    with pytest.raises(ValueError, match="future"):
        make_plan(legacy, TODAY + dt.timedelta(days=1), TODAY)
    with pytest.raises(ValueError, match="retention"):
        make_plan(legacy, TODAY - dt.timedelta(days=400), TODAY)
    with pytest.raises(ValueError, match="no data"):
        make_plan(Legacy(), TODAY, TODAY)


async def test_dry_run_prints_the_plan_and_needs_no_database(tmp_path, capsys):
    _write(tmp_path / "aggregate_power.csv", "ts,house_id,watts", ["2015-01-05 00:00:00+00,2,10"])
    _write(tmp_path / "appliance_power.csv", "ts,house_id,appliance,watts", [])
    _write(tmp_path / "appliance_truth.csv", "ts,house_id,appliance,watts", [])

    code = await main(["--dump", str(tmp_path), "--owner-email", "a@example.com", "--dry-run"])

    assert code == 0
    out = capsys.readouterr().out
    assert "old houses [2]" in out and "1 aggregate minutes" in out
    assert "2015-01-05 .. 2015-01-05" in out


async def test_missing_files_are_reported(tmp_path, capsys):
    assert await main(["--dump", str(tmp_path), "--owner-email", "a@example.com"]) == 2
    assert "aggregate_power.csv" in capsys.readouterr().err
