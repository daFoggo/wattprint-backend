import time
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.modules.ops.services import ingest as ingest_mod
from app.modules.ops.services.ingest import (
    IngestResult,
    ReadingRow,
    ingest_estimates,
    ingest_readings,
)
from app.modules.ops.utils.exceptions import MeterNotFound

T0 = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
SOURCE = "test-src"


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest.fixture
async def rig(session):
    """A home with one meter and two mapped series (channels 'p' and 'v'); rolled back after."""
    hid = await session.scalar(
        text("INSERT INTO public.tb_home (name) VALUES ('Ingest') RETURNING id")
    )
    serial = f"SN-{uuid.uuid4().hex[:10]}"
    mid = await session.scalar(
        text("INSERT INTO public.tb_meter (serial, home_id) VALUES (:s, :h) RETURNING id"),
        {"s": serial, "h": hid},
    )
    sids = {}
    for channel, metric, unit in (("p", "power_w", "W"), ("v", "voltage_v", "V")):
        sids[channel] = await session.scalar(
            text(
                "INSERT INTO public.tb_series "
                "(home_id, kind, metric, unit, meter_id, source_channel) "
                "VALUES (:h, 'main', :m, :u, :mid, :c) RETURNING series_id"
            ),
            {"h": hid, "m": metric, "u": unit, "mid": mid, "c": channel},
        )
    return {"home": hid, "serial": serial, "meter": mid, "sids": sids}


async def stored(session, sid):
    r = await session.execute(
        text("SELECT ts, value, quality FROM public.tb_reading WHERE series_id = :s ORDER BY ts"),
        {"s": sid},
    )
    return r.all()


async def checkpoint(session, sid):
    return await session.scalar(
        text("SELECT last_ts FROM public.tb_ingest_checkpoint WHERE source = :src AND series_id = :s"),
        {"src": SOURCE, "s": sid},
    )


def assert_adds_up(res: IngestResult):
    assert res.rows_in == res.rows_new + res.rows_dup + res.rows_bad


async def test_ingest_counts_add_up(session, rig):
    rows = [ReadingRow(at(i), "p", 100.0 + i) for i in range(5)]
    rows += [ReadingRow(at(0), "v", 230.0), ReadingRow(at(1), "nope", 1.0)]
    res = await ingest_readings(session, rig["serial"], rows, SOURCE)
    assert (res.rows_in, res.rows_new, res.rows_dup, res.rows_bad) == (7, 6, 0, 1)
    assert_adds_up(res)
    assert len(await stored(session, rig["sids"]["p"])) == 5
    assert len(await stored(session, rig["sids"]["v"])) == 1


async def test_second_identical_batch_is_all_dup(session, rig):
    rows = [ReadingRow(at(i), "p", 1.0 * i) for i in range(4)]
    await ingest_readings(session, rig["serial"], rows, SOURCE)
    res = await ingest_readings(session, rig["serial"], rows, SOURCE)
    assert (res.rows_in, res.rows_new, res.rows_dup, res.rows_bad) == (4, 0, 4, 0)
    assert len(await stored(session, rig["sids"]["p"])) == 4


async def test_unknown_channel_counted_bad(session, rig):
    res = await ingest_readings(
        session,
        rig["serial"],
        [ReadingRow(at(0), "zzz", 1.0), ReadingRow(at(0), "p", 1.0)],
        SOURCE,
    )
    assert (res.rows_new, res.rows_bad) == (1, 1)
    assert_adds_up(res)


async def test_nan_and_inf_counted_bad(session, rig):
    rows = [
        ReadingRow(at(0), "p", float("nan")),
        ReadingRow(at(1), "p", float("inf")),
        ReadingRow(at(2), "p", float("-inf")),
        ReadingRow(at(3), "p", 5.0),
    ]
    res = await ingest_readings(session, rig["serial"], rows, SOURCE)
    assert (res.rows_new, res.rows_bad) == (1, 3)
    assert_adds_up(res)
    assert len(await stored(session, rig["sids"]["p"])) == 1


async def test_naive_ts_and_bad_quality_counted_bad(session, rig):
    rows = [
        ReadingRow(datetime(2026, 11, 1, 0, 0), "p", 1.0),  # naive
        ReadingRow(at(1), "p", 1.0, quality=-1),
        ReadingRow(at(2), "p", 1.0, quality=32768),
        ReadingRow(at(3), "p", 1.0, quality=32767),  # valid upper bound
        ReadingRow(at(4), "p", 1.0, quality=0),  # valid lower bound
    ]
    res = await ingest_readings(session, rig["serial"], rows, SOURCE)
    assert (res.rows_new, res.rows_bad) == (2, 3)
    assert_adds_up(res)


async def test_duplicate_inside_one_batch_counts_dup_first_wins(session, rig):
    # The same instant expressed in two time zones is still a duplicate.
    ict = timezone(timedelta(hours=7))
    rows = [
        ReadingRow(at(0), "p", 10.0),
        ReadingRow(at(0).astimezone(ict), "p", 99.0),
        ReadingRow(at(1), "p", 11.0),
    ]
    res = await ingest_readings(session, rig["serial"], rows, SOURCE)
    assert (res.rows_in, res.rows_new, res.rows_dup, res.rows_bad) == (3, 2, 1, 0)
    got = await stored(session, rig["sids"]["p"])
    assert [r.value for r in got] == [10.0, 11.0]


async def test_out_of_order_rows_accepted(session, rig):
    rows = [ReadingRow(at(m), "p", float(m)) for m in (5, 1, 3, 2, 4)]
    res = await ingest_readings(session, rig["serial"], rows, SOURCE)
    assert res.rows_new == 5
    got = await stored(session, rig["sids"]["p"])
    assert [r.ts for r in got] == [at(m) for m in (1, 2, 3, 4, 5)]


async def test_checkpoint_advances_to_max_ts_and_never_goes_back(session, rig):
    sid = rig["sids"]["p"]
    await ingest_readings(
        session, rig["serial"], [ReadingRow(at(m), "p", 1.0) for m in (3, 9, 5)], SOURCE
    )
    assert await checkpoint(session, sid) == at(9)
    await ingest_readings(
        session, rig["serial"], [ReadingRow(at(m), "p", 1.0) for m in (1, 2)], SOURCE
    )
    assert await checkpoint(session, sid) == at(9)
    await ingest_readings(session, rig["serial"], [ReadingRow(at(12), "p", 1.0)], SOURCE)
    assert await checkpoint(session, sid) == at(12)
    # no checkpoint for a series that got no valid row, and none for another source
    assert await checkpoint(session, rig["sids"]["v"]) is None
    other = await session.scalar(
        text("SELECT count(*) FROM public.tb_ingest_checkpoint WHERE source <> :s AND series_id = :i"),
        {"s": SOURCE, "i": sid},
    )
    assert other == 0


async def test_batch_row_is_recorded_ok_with_counts(session, rig):
    rows = [ReadingRow(at(0), "p", 1.0), ReadingRow(at(0), "p", 2.0), ReadingRow(at(1), "x", 1.0)]
    res = await ingest_readings(session, rig["serial"], rows, SOURCE)
    b = (
        await session.execute(
            text("SELECT * FROM public.tb_ingest_batch WHERE id = :i"), {"i": res.batch_id}
        )
    ).one()
    assert b.status == "ok" and b.source == SOURCE and b.home_id == rig["home"]
    assert (b.rows_in, b.rows_new, b.rows_dup, b.rows_bad) == (3, 1, 1, 1)
    assert b.finished_at is not None and b.note is None


async def test_failed_write_marks_batch_failed_and_reraises(session, rig, monkeypatch):
    real = ingest_mod._write_readings

    async def write_then_fail(sess, valid, source):
        await real(sess, valid, source)  # data + checkpoint really written, then rolled back
        raise RuntimeError("boom")

    monkeypatch.setattr(ingest_mod, "_write_readings", write_then_fail)
    with pytest.raises(RuntimeError, match="boom"):
        await ingest_readings(session, rig["serial"], [ReadingRow(at(0), "p", 1.0)], SOURCE)
    b = (
        await session.execute(
            text("SELECT status, note, finished_at FROM public.tb_ingest_batch WHERE source = :s"),
            {"s": SOURCE},
        )
    ).one()
    assert b.status == "failed" and b.note == "RuntimeError: boom" and b.finished_at is not None
    assert await stored(session, rig["sids"]["p"]) == []  # data write rolled back
    assert await checkpoint(session, rig["sids"]["p"]) is None
    monkeypatch.undo()
    res = await ingest_readings(session, rig["serial"], [ReadingRow(at(0), "p", 1.0)], SOURCE)
    assert res.rows_new == 1  # the session is still usable


async def test_db_error_note_is_dbapi_text(session, rig, monkeypatch):
    async def bad_write(sess, valid, source):
        await sess.execute(text("SELECT 1/0"))

    monkeypatch.setattr(ingest_mod, "_write_readings", bad_write)
    with pytest.raises(Exception, match="division by zero"):
        await ingest_readings(session, rig["serial"], [ReadingRow(at(0), "p", 1.0)], SOURCE)
    note = await session.scalar(
        text("SELECT note FROM public.tb_ingest_batch WHERE source = :s"), {"s": SOURCE}
    )
    assert "division by zero" in note and "SELECT" not in note


async def test_out_of_range_value_counted_bad(session, rig):
    rows = [
        ReadingRow(at(0), "p", 1e300),
        ReadingRow(at(1), "p", -1e39),
        ReadingRow(at(2), "p", 3.4028234e38),  # largest REAL: valid
        ReadingRow(at(3), "p", 1.0),
    ]
    res = await ingest_readings(session, rig["serial"], rows, SOURCE)
    assert (res.rows_new, res.rows_bad) == (2, 2)
    assert_adds_up(res)


async def test_non_datetime_ts_and_bool_quality_counted_bad(session, rig):
    rows = [
        ReadingRow("2026-11-01T00:00:00+00:00", "p", 1.0),  # type: ignore[arg-type]
        ReadingRow(at(1), "p", 1.0, quality=True),
        ReadingRow(at(2), "p", "abc"),  # type: ignore[arg-type]
        ReadingRow(at(3), "p", 1.0),
    ]
    res = await ingest_readings(session, rig["serial"], rows, SOURCE)
    assert (res.rows_new, res.rows_bad) == (1, 3)
    assert_adds_up(res)


async def test_unknown_meter_raises_and_writes_no_batch(session, rig):
    with pytest.raises(MeterNotFound):
        await ingest_readings(session, "no-such-serial", [ReadingRow(at(0), "p", 1.0)], SOURCE)
    assert isinstance(MeterNotFound("x"), LookupError)
    n = await session.scalar(
        text("SELECT count(*) FROM public.tb_ingest_batch WHERE source = :s"), {"s": SOURCE}
    )
    assert n == 0


async def test_meter_without_home_is_allowed_all_rows_bad(session):
    serial = f"SN-{uuid.uuid4().hex[:10]}"
    await session.execute(text("INSERT INTO public.tb_meter (serial) VALUES (:s)"), {"s": serial})
    res = await ingest_readings(session, serial, [ReadingRow(at(0), "p", 1.0)], SOURCE)
    assert (res.rows_in, res.rows_new, res.rows_bad) == (1, 0, 1)


async def test_empty_batch(session, rig):
    res = await ingest_readings(session, rig["serial"], [], SOURCE)
    assert (res.rows_in, res.rows_new, res.rows_dup, res.rows_bad) == (0, 0, 0, 0)


async def _est_series(session, rig):
    dev = await session.scalar(
        text(
            "INSERT INTO public.tb_device (home_id, device_type_code, name, origin) "
            "VALUES (:h, 'fridge', 'Fridge', 'nilm') RETURNING id"
        ),
        {"h": rig["home"]},
    )
    return await session.scalar(
        text(
            "INSERT INTO public.tb_series (home_id, kind, device_id, metric, unit) "
            "VALUES (:h, 'device', :d, 'power_w', 'W') RETURNING series_id"
        ),
        {"h": rig["home"], "d": dev},
    )


async def test_estimates_upsert_latest_run_wins(session, rig):
    sid = await _est_series(session, rig)
    n1 = await ingest_estimates(session, 1, [(at(0), sid, 10.0), (at(1), sid, 20.0)])
    n2 = await ingest_estimates(session, 2, [(at(1), sid, 25.0), (at(2), sid, 30.0)])
    assert (n1, n2) == (2, 2)
    got = (
        await session.execute(
            text(
                "SELECT ts, value, run_id FROM public.tb_device_estimate WHERE series_id = :s "
                "ORDER BY ts"
            ),
            {"s": sid},
        )
    ).all()
    assert [(r.value, r.run_id) for r in got] == [(10.0, 1), (25.0, 2), (30.0, 2)]


async def test_estimates_skip_non_finite(session, rig):
    sid = await _est_series(session, rig)
    n = await ingest_estimates(
        session, 1, [(at(0), sid, float("nan")), (at(1), sid, float("inf")), (at(2), sid, 3.0)]
    )
    assert n == 1
    assert await ingest_estimates(session, 1, []) == 0


async def test_quality_bit_is_stored(session, rig):
    await ingest_readings(session, rig["serial"], [ReadingRow(at(0), "p", 1.0, quality=1)], SOURCE)
    got = await stored(session, rig["sids"]["p"])
    assert got[0].quality == 1


async def test_two_batches_in_one_transaction(session, rig):
    a = await ingest_readings(session, rig["serial"], [ReadingRow(at(0), "p", 1.0)], SOURCE)
    b = await ingest_readings(session, rig["serial"], [ReadingRow(at(1), "p", 2.0)], "other")
    assert a.batch_id != b.batch_id
    assert (a.rows_new, b.rows_new) == (1, 1)
    t = {r.id: r for r in (await session.execute(text("SELECT * FROM public.tb_ingest_batch"))).all()}
    ba, bb = t[a.batch_id], t[b.batch_id]
    assert ba.started_at < bb.started_at
    assert ba.finished_at >= ba.started_at and bb.finished_at >= bb.started_at
    assert ba.finished_at <= bb.started_at
    assert len(await stored(session, rig["sids"]["p"])) == 2


async def test_ingest_runs_with_ingest_role_privileges(session, rig):
    sid = await _est_series(session, rig)
    await session.execute(text("SET LOCAL ROLE wattprint_ingest"))
    rows = [ReadingRow(at(0), "p", 1.0), ReadingRow(at(1), "v", 2.0)]
    res = await ingest_readings(session, rig["serial"], rows, SOURCE)
    assert (res.rows_new, res.rows_bad) == (2, 0)
    # second batch: checkpoint DO UPDATE path (and a duplicate)
    res = await ingest_readings(
        session, rig["serial"], [ReadingRow(at(1), "v", 2.0), ReadingRow(at(5), "p", 3.0)], SOURCE
    )
    assert (res.rows_new, res.rows_dup) == (1, 1)
    assert await ingest_estimates(session, 1, [(at(0), sid, 5.0)]) == 1
    assert await ingest_estimates(session, 2, [(at(0), sid, 6.0)]) == 1  # DO UPDATE path
    await session.execute(text("RESET ROLE"))
    assert await checkpoint(session, rig["sids"]["p"]) == at(5)
    run = await session.scalar(
        text("SELECT run_id FROM public.tb_device_estimate WHERE series_id = :s"), {"s": sid}
    )
    assert run == 2


async def test_throughput_100k_rows(session, rig, monkeypatch):
    n = 100_000
    rows = [ReadingRow(at(i), "p" if i % 2 else "v", float(i % 5000)) for i in range(n)]
    real, spent = ingest_mod._write_readings, []

    async def timed(sess, valid, source):
        t0 = time.perf_counter()
        try:
            return await real(sess, valid, source)
        finally:
            spent.append(time.perf_counter() - t0)

    monkeypatch.setattr(ingest_mod, "_write_readings", timed)
    t = time.perf_counter()
    res = await ingest_readings(session, rig["serial"], rows, SOURCE)
    dt = time.perf_counter() - t
    print(
        f"THROUGHPUT ingest_readings: {n} rows in {dt:.2f}s = {n / dt:,.0f} rows/s; "
        f"COPY+INSERT {spent[0]:.2f}s, rest (classification, bookkeeping) {dt - spent[0]:.2f}s"
    )
    assert (res.rows_in, res.rows_new, res.rows_dup, res.rows_bad) == (n, n, 0, 0)
    b = (
        await session.execute(
            text("SELECT finished_at - started_at AS d FROM public.tb_ingest_batch WHERE id = :i"),
            {"i": res.batch_id},
        )
    ).one()
    assert b.d > timedelta(0)
