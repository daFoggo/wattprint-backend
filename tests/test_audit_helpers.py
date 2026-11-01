import json
from datetime import UTC, date, datetime, timedelta

from tests.audit import results
from tests.audit.run import shift_days_for_csv


def test_record_merges_and_load_roundtrips(tmp_path):
    p = tmp_path / "r.json"
    assert results.load(p) == {}
    results.record("load", "a", 1, p)
    results.record("load", "b", {"x": [1, 2]}, p)
    results.record("stats", "c", 3.5, p)
    results.record("load", "a", 2, p)
    assert results.load(p) == {"load": {"a": 2, "b": {"x": [1, 2]}}, "stats": {"c": 3.5}}
    assert json.loads(p.read_text())["stats"]["c"] == 3.5


def test_shift_puts_last_reading_on_yesterday(tmp_path):
    last = int(datetime(2015, 5, 24, 23, 59, 58, tzinfo=UTC).timestamp())
    csv = tmp_path / "CLEAN_House9.csv"
    csv.write_text(
        "Time,Unix,Aggregate,Appliance1,Appliance2,Appliance3,Appliance4,Appliance5,"
        "Appliance6,Appliance7,Appliance8,Appliance9,Issues\n"
        f"x,{last - 8},1,0,0,0,0,0,0,0,0,0,0\n"
        f"x,{last},1,0,0,0,0,0,0,0,0,0,0\n\n",
        encoding="utf-8",
    )
    today = date(2026, 11, 1)
    shift = shift_days_for_csv(csv, today=today)
    moved = datetime.fromtimestamp(last, UTC) + timedelta(days=shift)
    assert moved.date() == today - timedelta(days=1)
    assert moved.time() == datetime.fromtimestamp(last, UTC).time()


def test_guard_refuses_non_audit_database():
    import pytest

    from tests.audit.support import NotAuditTarget, check_target

    admin = "postgresql+asyncpg://u:p@db/postgres"
    ok = "postgresql+asyncpg://u:p@db:5432/wattprint_audit"
    assert check_target(ok, admin) == "wattprint_audit"
    assert check_target(ok.replace("wattprint_audit", "wattprint_audit_b"), admin)
    for bad in ("wattprint", "postgres", "audit_wattprint", "wattprint_test_ab12"):
        with pytest.raises(NotAuditTarget, match="refusing"):
            check_target(f"postgresql+asyncpg://u:p@db/{bad}", admin)
    with pytest.raises(NotAuditTarget, match="AUDIT_ADMIN_URL"):
        check_target(ok, None)
    with pytest.raises(NotAuditTarget):
        check_target(ok, "")


def test_scratch_names_never_name_the_audit_database(monkeypatch):
    import pytest

    from app.config import settings
    from tests.audit import support

    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://u:p@db/wattprint_audit")
    monkeypatch.setenv("AUDIT_ADMIN_URL", "postgresql+asyncpg://u:p@db/postgres")
    assert support.scratch_url("wattprint_audit_x").endswith("/wattprint_audit_x")
    for bad in ("wattprint_audit", "wattprint", "other_audit_x", "wattprint_auditx"):
        with pytest.raises(support.NotAuditTarget):
            support.scratch_url(bad)


def test_summarize_ms_and_trim_plan():
    from tests.audit.part_b import summarize_ms, trim_plan

    s = summarize_ms([float(i) for i in range(1, 101)])
    assert (s["n"], s["p50_ms"], s["p95_ms"], s["max_ms"]) == (100, 50.5, 95.0, 100.0)
    plan = [{"Execution Time": 1.5, "Planning Time": 0.5, "Plan": {
        "Node Type": "Append", "Actual Rows": 3, "Shared Hit Blocks": 7, "Shared Read Blocks": 1,
        "Plans": [{"Node Type": "Index Scan", "Relation Name": "_hyper_1_2_chunk"},
                  {"Node Type": "Seq Scan", "Relation Name": "series"}]}}]
    t = trim_plan(plan)
    assert t["chunk_relations_scanned"] == 1 and t["relations_scanned"] == 2
    assert (t["execution_ms"], t["shared_hit"], t["shared_read"]) == (1.5, 7, 1)


def test_extrapolation_arithmetic():
    from tests.audit.part_b2 import extrapolate

    data = {
        "stats": {
            "home_years": 2.0, "bytes_per_reading_raw": 5.0, "bytes_per_device_estimate_raw": 5.0,
            "bytes": {"aggregates": {"reading_1m": 1500.0, "reading_1h": 20.0, "reading_1d": 2.0,
                                     "device_estimate_1m": 1000.0, "device_estimate_1h": 9.0,
                                     "device_estimate_1d": 9.0}},
            "rows": {"aggregates": {"reading_1m": 10, "device_estimate_1m": 10}},
        },
        "cagg_compression": {"reading_1m": {"ratio": 10.0}, "device_estimate_1m": {"ratio": 20.0}},
        "load": {"house1": {"readings_per_s": 50_000}},
    }
    one_hz = extrapolate(data)["scenario_main_meter_only_1hz"]
    assert one_hz["readings_per_home_day"] == 86_400
    assert one_hz["daily_ingest_rows_10k_homes"] == 864_000_000
    assert one_hz["required_avg_rows_per_second"] == 10_000
    assert one_hz["average_rate_as_fraction_of_bulk_load_figure"] == 0.2
    # 1 m row costs 150 bytes, one per minute per series per year
    assert one_hz["agg_1m_uncompressed_gb_per_home_year"] == round(525_600 * 150 / 1e9, 4)
    assert one_hz["agg_1m_compressed_gb_per_home_year"] == round(525_600 * 15 / 1e9, 4)
    plugs = extrapolate(data)["scenario_main_plus_9_devices_30s_with_estimates"]
    # 9 estimate series x 525,600 minutes x 100 bytes/row, 20x compressed
    assert plugs["device_estimate_agg_1m_uncompressed_gb_per_home_year"] == round(
        9 * 525_600 * 100 / 1e9, 4)
    assert plugs["device_estimate_agg_1m_compressed_gb_per_home_year"] == round(
        9 * 525_600 * 5 / 1e9, 4)
