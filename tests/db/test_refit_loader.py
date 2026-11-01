import csv
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.cli.load_refit import first_timestamp, load_house, main
from app.cli.provision_refit import METADATA, device_type_for, provision_house
from app.services import ingest as ingest_mod
from app.services.aggregates import backfill_aggregates

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "refit_sample.csv"
SAMPLE_ROWS = 320  # first 300 rows + 20 later rows with Issues=1
FLAGGED = 20
CHANNELS = ["Aggregate", *[f"Appliance{k}" for k in range(1, 10)]]


def email() -> str:
    return f"refit-{uuid.uuid4().hex[:8]}@example.invalid"


async def count(session, sql: str, **params):
    return await session.scalar(text(sql), params)


async def series_ids(session, home_id):
    rows = await session.execute(
        text("SELECT source_channel, series_id FROM energy.series WHERE home_id = :h"),
        {"h": home_id},
    )
    return dict(rows.all())


# ---------- provisioning ----------


async def test_provision_creates_home_meter_and_ten_series(session):
    addr = email()
    hid = await provision_house(session, 1, addr)
    home = (
        await session.execute(
            text(
                "SELECT name, home_type, occupants, year_built, tariff_plan_code, "
                "billing_cycle_day, timezone FROM core.home WHERE id = :h"
            ),
            {"h": hid},
        )
    ).one()
    assert tuple(home) == (
        "REFIT House 1", "house", 2, 1975, "vn_residential", 1, "Asia/Ho_Chi_Minh",
    )
    user = (
        await session.execute(
            text("SELECT id, hashed_password FROM users WHERE email = :e"), {"e": addr}
        )
    ).one()
    assert user.hashed_password is None
    role = await count(
        session,
        "SELECT role FROM core.home_member WHERE home_id = :h AND user_id = :u",
        h=hid, u=user.id,
    )
    assert role == "owner"
    meter = (
        await session.execute(
            text("SELECT serial, status, home_id FROM core.meter WHERE serial = 'REFIT-H1'")
        )
    ).one()
    assert tuple(meter) == ("REFIT-H1", "active", hid)
    rows = (
        await session.execute(
            text(
                "SELECT source_channel, kind, metric, unit, device_id IS NOT NULL AS has_dev, "
                "meter_id IS NOT NULL AS has_meter FROM energy.series WHERE home_id = :h"
            ),
            {"h": hid},
        )
    ).all()
    by = {r.source_channel: r for r in rows}
    assert sorted(by) == sorted(CHANNELS)
    assert (by["Aggregate"].kind, by["Aggregate"].has_dev) == ("main", False)
    assert (by["Aggregate"].metric, by["Aggregate"].unit) == ("power_w", "W")
    for k in range(1, 10):
        r = by[f"Appliance{k}"]
        assert (r.kind, r.metric, r.unit, r.has_dev, r.has_meter) == (
            "plug", "power_w", "W", True, True,
        )
    devs = (
        await session.execute(
            text("SELECT name, origin, device_type_code FROM core.device WHERE home_id = :h"),
            {"h": hid},
        )
    ).all()
    assert len(devs) == 9 and {d.origin for d in devs} == {"plug"}
    types = {d.name: d.device_type_code for d in devs}
    assert types["Washer Dryer"] == "washer_dryer"
    assert types["Washing Machine"] == "washing_machine"
    assert types["Television Site"] == "television"
    assert types["Electric Heater"] == "electric_heater"
    assert types["Computer"] == "computer"


async def test_provision_is_idempotent(session):
    addr = email()
    first = await provision_house(session, 2, addr)
    tables = ("core.home", "core.meter", "core.device", "energy.series", "core.home_member")
    before = [await count(session, f"SELECT count(*) FROM {t}") for t in tables]
    again = await provision_house(session, 2, addr)
    after = [await count(session, f"SELECT count(*) FROM {t}") for t in tables]
    assert again == first and before == after


async def test_provision_unknown_house_raises(session):
    with pytest.raises(ValueError):
        await provision_house(session, 14, email())
    with pytest.raises(ValueError):
        await provision_house(session, 99, email())


async def _snapshot(session):
    tables = ("users", "core.home", "core.meter", "core.device", "energy.series",
              "core.home_member")
    return [await count(session, f"SELECT count(*) FROM {t}") for t in tables]


async def test_provision_refuses_users_real_home(session):
    addr = email()
    uid = await session.scalar(
        text("INSERT INTO users (id, email) VALUES (gen_random_uuid(), :e) RETURNING id"),
        {"e": addr},
    )
    hid = await session.scalar(
        text("INSERT INTO core.home (name) VALUES ('My real home') RETURNING id")
    )
    await session.execute(
        text("INSERT INTO core.home_member (home_id, user_id, role) VALUES (:h, :u, 'owner')"),
        {"h": hid, "u": uid},
    )
    before = await _snapshot(session)
    with pytest.raises(ValueError, match="My real home"):
        await provision_house(session, 1, addr)
    assert await _snapshot(session) == before


async def test_provision_refuses_other_house_email(session):
    addr = email()
    await provision_house(session, 1, addr)
    before = await _snapshot(session)
    with pytest.raises(ValueError, match="REFIT House 1"):
        await provision_house(session, 2, addr)
    assert await _snapshot(session) == before


async def test_provision_refuses_existing_meter_of_other_home(session):
    await provision_house(session, 1, email())
    before = await _snapshot(session)
    with pytest.raises(ValueError):
        await provision_house(session, 1, email())  # new user, meter REFIT-H1 is taken
    assert await _snapshot(session) == before


async def test_device_names_unique_per_house(session):
    names = {}
    for h in (1, 4, 7, 16):
        hid = await provision_house(session, h, email())
        rows = await session.scalars(
            text("SELECT name FROM core.device WHERE home_id = :h"), {"h": hid}
        )
        names[h] = sorted(rows)
        assert len(names[h]) == 9 and len(set(names[h])) == 9, names[h]
    assert {"Freezer (1)", "Freezer (2)"} <= set(names[1])
    assert {"Washing Machine (1)", "Washing Machine (2)"} <= set(names[4])
    assert {"Freezer #1", "Freezer #2"} <= set(names[7])
    assert {"Fridge-Freezer #1", "Fridge-Freezer #2"} <= set(names[16])
    assert {"Electric Heater (1)", "Electric Heater (2)"} <= set(names[16])


async def test_provision_all_twenty_houses(session):
    codes = set(await session.scalars(text("SELECT code FROM catalog.device_type")))
    for h in sorted(int(k) for k in METADATA):
        hid = await provision_house(session, h, email())
        assert await count(
            session, "SELECT count(*) FROM energy.series WHERE home_id = :h", h=hid
        ) == 10
        devs = (
            await session.execute(
                text("SELECT device_type_code, name FROM core.device WHERE home_id = :h"),
                {"h": hid},
            )
        ).all()
        assert len(devs) == 9 and {d[0] for d in devs} <= codes
        assert len({d[1] for d in devs}) == 9, f"house {h}: duplicate device names"


def test_device_type_mapping():
    assert device_type_for("Fridge-Freezer") == "fridge_freezer"
    assert device_type_for("Fridge Freezer") == "fridge_freezer"
    assert device_type_for("Chest Freezer") == "freezer"
    assert device_type_for("Fridge") == "fridge"
    assert device_type_for("Tumble Dryer") == "tumble_dryer"
    assert device_type_for("TV Site") == "television"
    assert device_type_for("TV/Satellite") == "television"
    assert device_type_for("Desktop Computer") == "computer"
    assert device_type_for("Hi-Fi") == "hifi"
    assert device_type_for("unknown") == "other"
    assert device_type_for("Pond Pump") == "other"
    assert device_type_for("Vivarium") == "other"


async def test_unmapped_device_goes_to_other(session):
    hid = await provision_house(session, 21, email())  # Food Mixer, Vivarium, Pond Pump
    other = await count(
        session,
        "SELECT count(*) FROM core.device WHERE home_id = :h AND device_type_code = 'other'",
        h=hid,
    )
    expected = sum(
        device_type_for(c["name"]) == "other"
        for k, c in METADATA["21"]["channels"].items()
        if k != "Aggregate"
    )
    assert other == expected >= 3


# ---------- loader ----------


@pytest.fixture
async def home(session):
    await provision_house(session, 1, email())
    return await session.scalar(text("SELECT home_id FROM core.meter WHERE serial = 'REFIT-H1'"))


async def test_load_sample_counts(session, home):
    res = await load_house(session, 1, SAMPLE)
    assert (res.rows_in, res.rows_new, res.rows_dup, res.rows_bad) == (
        SAMPLE_ROWS * 10, SAMPLE_ROWS * 10, 0, 0,
    )
    stored = await count(
        session,
        "SELECT count(*) FROM energy.reading r JOIN energy.series s USING (series_id) "
        "WHERE s.home_id = :h",
        h=home,
    )
    assert stored == SAMPLE_ROWS * 10


async def test_reload_sample_is_all_dup(session, home):
    await load_house(session, 1, SAMPLE)
    res = await load_house(session, 1, SAMPLE)
    assert (res.rows_in, res.rows_new, res.rows_dup, res.rows_bad) == (
        SAMPLE_ROWS * 10, 0, SAMPLE_ROWS * 10, 0,
    )


async def test_issues_flag_sets_quality_bit(session, home):
    await load_house(session, 1, SAMPLE)
    sids = await series_ids(session, home)
    flagged_ts = set()
    with open(SAMPLE, newline="") as f:
        for row in csv.DictReader(f):
            if row["Issues"] == "1":
                flagged_ts.add(datetime.fromtimestamp(int(row["Unix"]), UTC))
    assert len(flagged_ts) == FLAGGED
    for ch in CHANNELS:
        rows = (
            await session.execute(
                text("SELECT ts, quality FROM energy.reading WHERE series_id = :s"),
                {"s": sids[ch]},
            )
        ).all()
        assert len(rows) == SAMPLE_ROWS
        for ts, q in rows:
            assert q == (1 if ts in flagged_ts else 0)


async def test_shift_days_moves_timestamps_not_values(session, home):
    await load_house(session, 1, SAMPLE, limit_rows=5)
    sids = await series_ids(session, home)
    q = text("SELECT ts, value FROM energy.reading WHERE series_id = :s ORDER BY ts")
    base = (await session.execute(q, {"s": sids["Aggregate"]})).all()
    await session.execute(text("DELETE FROM energy.reading"))
    res = await load_house(session, 1, SAMPLE, shift_days=30, limit_rows=5)
    assert res.rows_new == 50
    shifted = (await session.execute(q, {"s": sids["Aggregate"]})).all()
    assert [r.value for r in shifted] == [r.value for r in base]
    assert [r.ts - timedelta(days=30) for r in shifted] == [r.ts for r in base]
    assert shifted[0].ts == datetime(2013, 10, 9, 13, 6, 17, tzinfo=UTC) + timedelta(days=30)
    assert shifted[0].value == 523


async def test_time_is_utc(session, home):
    await load_house(session, 1, SAMPLE, limit_rows=3)
    sids = await series_ids(session, home)
    ts = await count(
        session, "SELECT min(ts) FROM energy.reading WHERE series_id = :s", s=sids["Aggregate"]
    )
    assert ts == datetime(2013, 10, 9, 13, 6, 17, tzinfo=UTC)


async def test_limit_rows_and_chunks_sum(session, home):
    res = await load_house(session, 1, SAMPLE, batch_rows=7, limit_rows=50)
    assert (res.rows_in, res.rows_new) == (500, 500)
    batches = await count(
        session, "SELECT count(*) FROM ops.ingest_batch WHERE home_id = :h", h=home
    )
    assert batches == 8  # ceil(50 / 7)


async def test_malformed_rows_counted_and_never_crash(session, home, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "Time,Unix,Aggregate,Appliance1,Appliance2,Appliance3,Appliance4,Appliance5,"
        "Appliance6,Appliance7,Appliance8,Appliance9,Issues\n"
        "2013-10-09 13:06:17,1381323977,523,74,0,69,0,0,0,0,0,1,0\n"
        "2013-10-09 13:06:31,1381323991,526,75\n"  # wrong column count
        "2013-10-09 13:06:46,notanumber,540,74,0,68,0,0,0,0,0,1,0\n"  # bad Unix
        "\n"  # blank line is ignored, not a row
        "2013-10-09 13:07:01,1381324021,abc,74,0,68,0,0,0,0,0,1,0\n"  # one bad value
        "2013-10-09 13:07:16,1381324036,540,74,0,68,0,0,0,0,0,1,x\n"  # bad Issues
        "2013-10-09 13:07:31,1381324051,541,74,0,68,0,0,0,0,0,1,0\n",
        encoding="utf-8",
    )
    res = await load_house(session, 1, bad)
    assert res.rows_in == res.rows_new + res.rows_dup + res.rows_bad
    assert res.rows_new == 10 + 9 + 10  # two good rows plus nine good channels of the abc row
    assert res.rows_bad == 4  # wrong column count, bad Unix, 'abc' value, bad Issues
    assert res.rows_dup == 0


# ---------- commits, CLI, aggregates (private committed database) ----------


@pytest.fixture
async def committed(throwaway_dsn):
    engine = create_async_engine(throwaway_dsn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        # history loads need the retention/compression policies off (see the guard tests below)
        async with engine.connect() as c:
            await c.execute(text("SELECT ops.set_policies(false)"))
            await c.commit()
        yield factory
    finally:
        await engine.dispose()


async def test_commits_per_chunk_so_progress_survives(committed, monkeypatch):
    async with committed() as s:
        await provision_house(s, 1, email())
        await s.commit()

    real = ingest_mod._write_readings
    calls = {"n": 0}

    async def flaky(session, valid, source):
        calls["n"] += 1
        result = await real(session, valid, source)
        if calls["n"] == 3:
            raise RuntimeError("boom inside the write of chunk 3")
        return result

    monkeypatch.setattr(ingest_mod, "_write_readings", flaky)
    async with committed() as s:
        with pytest.raises(RuntimeError, match="boom inside"):
            await load_house(s, 1, SAMPLE, batch_rows=40)
    async with committed() as s:
        stored = await count(s, "SELECT count(*) FROM energy.reading")
        batches = (
            await s.execute(
                text("SELECT status, rows_new, note FROM ops.ingest_batch ORDER BY started_at")
            )
        ).all()
    assert stored == 2 * 40 * 10  # chunks 1 and 2 committed, chunk 3 not stored
    assert [b.status for b in batches] == ["ok", "ok", "failed"]
    assert [b.rows_new for b in batches[:2]] == [400, 400]
    assert "boom inside the write of chunk 3" in batches[2].note


async def test_cli_main_loads_sample(committed, capsys):
    addr = email()
    argv = ["--house", "1", "--csv", str(SAMPLE), "--owner-email", addr]
    rc = await main([*argv, "--batch-rows", "100"], session_factory=committed)
    assert rc == 0
    out = capsys.readouterr().out
    assert "3200" in out and "readings/s" in out
    async with committed() as s:
        assert await count(s, "SELECT count(*) FROM energy.reading") == SAMPLE_ROWS * 10
        assert await count(s, "SELECT count(*) FROM users WHERE email = :e", e=addr) == 1
    # a second run provisions nothing new and loads only duplicates
    assert await main(argv, session_factory=committed) == 0
    async with committed() as s:
        assert await count(s, "SELECT count(*) FROM core.home WHERE name = 'REFIT House 1'") == 1
        assert await count(s, "SELECT count(*) FROM energy.reading") == SAMPLE_ROWS * 10


async def test_cli_missing_csv_returns_error(committed, tmp_path):
    rc = await main(
        ["--house", "1", "--csv", str(tmp_path / "nope.csv")], session_factory=committed
    )
    assert rc != 0


async def test_loaded_main_series_reads_back_through_reading_1m(throwaway_dsn):
    engine = create_async_engine(throwaway_dsn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            await provision_house(s, 1, email())
            await load_house(s, 1, SAMPLE, limit_rows=300)
            sid = await count(s, "SELECT series_id FROM energy.series WHERE kind = 'main'")
    finally:
        await engine.dispose()
    auto = create_async_engine(throwaway_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with auto.connect() as c:
            await backfill_aggregates(
                c, datetime(2013, 10, 1, tzinfo=UTC), datetime(2013, 11, 1, tzinfo=UTC)
            )
            rows = (
                await c.execute(
                    text(
                        "SELECT bucket, avg_w, n FROM energy.reading_1m "
                        "WHERE series_id = :s ORDER BY bucket"
                    ),
                    {"s": sid},
                )
            ).all()
    finally:
        await auto.dispose()
    assert rows and sum(r.n for r in rows) == 300
    assert rows[0].bucket == datetime(2013, 10, 9, 13, 6, tzinfo=UTC)
    assert 400 < rows[0].avg_w < 700


async def test_cli_rejects_unknown_house_before_path_check(committed, tmp_path, capsys):
    rc = await main(
        ["--house", "14", "--csv", str(tmp_path / "nope.csv")], session_factory=committed
    )
    assert rc == 2
    assert "unknown REFIT house" in capsys.readouterr().err


@pytest.mark.parametrize(
    "bad",
    [["--limit-rows", "0"], ["--batch-rows", "0"], ["--batch-rows", "-5"],
     ["--limit-rows", "-1"], ["--shift-days", "99999999999"]],
)
async def test_cli_rejects_meaningless_numbers(bad):
    with pytest.raises(SystemExit) as exc:
        await main(["--house", "1", *bad])
    assert exc.value.code == 2


# ---------- policy guard ----------


async def policies_on(factory):
    async with factory() as s:
        await s.execute(text("SELECT ops.set_policies(true)"))
        await s.commit()


def args_for(*extra: str) -> list[str]:
    return ["--house", "1", "--csv", str(SAMPLE), "--owner-email", email(), *extra]


async def test_cli_refuses_old_data_while_retention_policy_is_active(committed, capsys):
    await policies_on(committed)
    assert await main(args_for(), session_factory=committed) == 2  # 2013 data, 400 d retention
    err = capsys.readouterr().err
    assert "retention policy" in err and "--shift-days" in err and "set_policies(false)" in err
    assert "--allow-active-policies" in err
    async with committed() as s:
        assert await count(s, "SELECT count(*) FROM energy.reading") == 0


async def test_cli_refuses_data_the_compression_policy_would_compress(committed, capsys):
    await policies_on(committed)
    first = first_timestamp(SAMPLE, timedelta(0))
    shift = (datetime.now(UTC) - timedelta(days=100) - first).days  # inside retention, > 2 d old
    assert await main(args_for("--shift-days", str(shift)), session_factory=committed) == 2
    err = capsys.readouterr().err
    assert "compression policy" in err and "retention policy" not in err


async def test_cli_loads_recent_data_with_policies_on(committed):
    await policies_on(committed)
    first = first_timestamp(SAMPLE, timedelta(0))
    shift = (datetime.now(UTC) - timedelta(hours=6) - first).days  # first row < 1 day old
    assert await main(args_for("--shift-days", str(shift)), session_factory=committed) == 0
    async with committed() as s:
        assert await count(s, "SELECT count(*) FROM energy.reading") == SAMPLE_ROWS * 10


async def test_cli_override_loads_despite_active_policies(committed):
    await policies_on(committed)
    assert await main(args_for("--allow-active-policies"), session_factory=committed) == 0
    async with committed() as s:
        assert await count(s, "SELECT count(*) FROM energy.reading") == SAMPLE_ROWS * 10


async def test_cli_loads_old_data_when_policies_are_off(committed):
    assert await main(args_for(), session_factory=committed) == 0  # the fixture switched them off


async def test_paused_policy_jobs_do_not_block_the_load(committed):
    await policies_on(committed)
    async with committed() as s:
        await s.execute(text("SELECT alter_job(job_id, scheduled => false) FROM "
                             "timescaledb_information.jobs WHERE hypertable_name IS NOT NULL"))
        await s.commit()
    assert await main(args_for(), session_factory=committed) == 0


def test_first_timestamp_applies_the_shift(tmp_path):
    first = first_timestamp(SAMPLE, timedelta(0))
    assert first_timestamp(SAMPLE, timedelta(days=3)) == first + timedelta(days=3)
    empty = tmp_path / "e.csv"
    empty.write_text("Time,Unix\n", encoding="utf-8")
    assert first_timestamp(empty, timedelta(0)) is None
