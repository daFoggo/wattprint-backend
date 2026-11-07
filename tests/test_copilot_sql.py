"""The Copilot's SQL builder and guard, without a database.

The numbers the built queries return are checked through the API in tests/db/test_copilot_ask.py;
here: values never enter the SQL text, and the guard refuses what generated SQL must never be.
"""

import datetime as dt
import uuid

import pytest

from app.copilot.agents.state import QueryGoal
from app.copilot.tools import catalog
from app.copilot.tools import sql_builder as sql
from tests.db.conftest import load_revision

TZ = "Asia/Ho_Chi_Minh"
WM = uuid.UUID("9b3c5376-cb1c-4619-aad3-05fbde448893")


def test_whole_home_energy_of_one_local_day_uses_positional_parameters():
    goal = QueryGoal(measure="energy", target="whole_home", source="measured",
                     start=dt.date(2026, 11, 4), end=dt.date(2026, 11, 4))
    text, params = sql.build(goal, TZ)
    utc = dt.UTC
    assert dt.datetime(2026, 11, 3, 17, tzinfo=utc) in params  # local midnight of 4 Nov
    assert dt.datetime(2026, 11, 4, 17, tzinfo=utc) in params
    assert "main" in params
    for i in range(1, len(params) + 1):
        assert f"${i}" in text
    assert "2026" not in text and "'main'" not in text
    assert "copilot_ro.reading_1d" in text


GOALS = {
    "device by name": QueryGoal(target="devices", device_ids=[WM], source="estimated",
                                start=dt.date(2026, 11, 4), end=dt.date(2026, 11, 4)),
    "top day": QueryGoal(start=dt.date(2026, 10, 29), end=dt.date(2026, 11, 4), grain="day",
                         order="desc", top_n=1),
    "previous period": QueryGoal(start=dt.date(2026, 11, 1), end=dt.date(2026, 11, 4),
                                 compare_to="previous_period"),
    "hour of day": QueryGoal(target="devices", device_ids=[WM], source="estimated",
                             start=dt.date(2026, 10, 29), end=dt.date(2026, 11, 4),
                             group_by="hour_of_day", order="desc", top_n=3),
    "cycles": QueryGoal(measure="cycles", target="devices", device_ids=[WM],
                        start=dt.date(2026, 10, 29), end=dt.date(2026, 11, 4), grain="day"),
}


@pytest.mark.parametrize("name", GOALS)
def test_built_queries_pass_the_guard_and_hold_no_values(name):
    text, params = sql.build(GOALS[name], TZ)
    sql.check_text(text, "execute")
    assert f"${len(params)}" in text and f"${len(params) + 1}" not in text
    assert str(WM) not in text and "2026" not in text and TZ not in text


def test_top_n_becomes_the_limit():
    text, _ = sql.build(GOALS["top day"], TZ)
    assert text.endswith("LIMIT 1")


SAFE = "SELECT v.energy_wh FROM copilot_ro.reading_1d AS v LIMIT 10"
HOSTILE = {
    "two statements": SAFE + "; SELECT 1 FROM copilot_ro.device LIMIT 1",
    "set_config": "SELECT set_config('app.copilot_token', 'x', true) FROM copilot_ro.device "
                  "LIMIT 1",
    "pg_sleep": "SELECT pg_sleep(10) FROM copilot_ro.device LIMIT 1",
    "pg_cancel_backend": "SELECT pg_cancel_backend(1) FROM copilot_ro.device LIMIT 1",
    "base table": "SELECT * FROM energy.reading LIMIT 10",
    "other schema view": "SELECT * FROM copilot_ro.suggestion LIMIT 10",
    "users": "SELECT hashed_password FROM users LIMIT 1",
    "no limit": "SELECT v.energy_wh FROM copilot_ro.reading_1d AS v",
    "limit too high": "SELECT v.energy_wh FROM copilot_ro.reading_1d AS v LIMIT 100000",
    "limit parameter": "SELECT v.energy_wh FROM copilot_ro.reading_1d AS v LIMIT $1",
    "insert in cte": "WITH x AS (INSERT INTO copilot.term (phrase) VALUES ('a') RETURNING id) "
                     "SELECT * FROM x LIMIT 1",
    "delete": "DELETE FROM copilot.suggestion",
    "set": "SET ROLE postgres",
    "subquery on base table": "SELECT (SELECT count(*) FROM core.home) FROM copilot_ro.device "
                              "LIMIT 1",
    "select into": "SELECT * INTO evil FROM copilot_ro.device LIMIT 1",
    "for update": "SELECT * FROM copilot_ro.device LIMIT 1 FOR UPDATE",
    "table function": "SELECT * FROM generate_series(1, 10) LIMIT 1",
}


@pytest.mark.parametrize("name", HOSTILE)
def test_guard_refuses_hostile_sql(name):
    with pytest.raises(sql.UnsafeSqlError):
        sql.check_text(HOSTILE[name], "execute")


def test_guard_accepts_plain_select_and_scopes_tables_per_node():
    sql.check_text(SAFE, "execute")
    with pytest.raises(sql.UnsafeSqlError):
        sql.check_text(SAFE, "evaluate_rules")  # rules read motif instances only


def test_question_syllables_match_the_database_function():
    migration = load_revision("20261106_6c2e8f1a4b90")
    assert catalog.QUESTION_SYLLABLES == migration.QUESTION_SYLLABLES
    assert all(f"'{s}'" in migration.MATCH_KEY_FN for s in catalog.QUESTION_SYLLABLES)
