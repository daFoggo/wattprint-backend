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
