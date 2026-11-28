"""Tiered retention (spec R1.1-R1.6). Policies are applied to the test database only."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.common import notify
from app.config import settings
from app.database import SessionLocal, engine
from app.modules.billing.services import device_forecast
from app.modules.energy.api import backfill_aggregates
from app.modules.insight.services import cycles, detectors, jobs
from scripts import apply_retention

WANT = {
    "tb_reading": 30,
    "tb_device_estimate": 30,
    "reading_1m": 90,
    "device_estimate_1m": 90,
    "reading_1h": 400,
    "device_estimate_1h": 400,
    "reading_1d": 800,
    "device_estimate_1d": 800,
    "tb_device_cycle": 90,
}
JOBS = text(
    "SELECT COALESCE(c.view_name, j.hypertable_name) AS rel, j.proc_name AS proc, "
    "(extract(epoch FROM (j.config->>'drop_after')::interval) / 86400)::int AS keep, "
    "(extract(epoch FROM (j.config->>'start_offset')::interval) / 86400)::int AS start "
    "FROM timescaledb_information.jobs j "
    "LEFT JOIN timescaledb_information.continuous_aggregates c "
    "ON c.materialization_hypertable_name = j.hypertable_name "
    "WHERE j.proc_name IN ('policy_retention', 'policy_refresh_continuous_aggregate')"
)


async def _jobs() -> tuple[dict, dict]:
    async with engine.connect() as c:
        rows = (await c.execute(JOBS)).all()
    return (
        {r.rel: r.keep for r in rows if r.proc == "policy_retention"},
        {r.rel: r.start for r in rows if r.proc != "policy_retention"},
    )


async def test_apply_sets_the_tiers_keeps_the_refresh_invariants_and_revert_restores():
    before = (await _jobs())[0]
    try:
        async with engine.begin() as c:
            await apply_retention.apply(c)
        keep, refresh = await _jobs()
        assert keep == WANT
        # R1.6: a refresh never reaches back past what its source still has.
        for family in ("reading", "device_estimate"):
            raw = f"tb_{family}"
            for level, source in (("1m", raw), ("1h", f"{family}_1m"), ("1d", f"{family}_1h")):
                assert refresh[f"{family}_{level}"] < keep[source]
        assert keep["reading_1d"] >= 25 * 31  # 25 bill cycles
    finally:
        async with engine.begin() as c:
            await apply_retention.revert(c)
    assert (await _jobs())[0] == before


async def test_the_dry_run_counts_and_changes_nothing():
    before = await _jobs()
    async with engine.connect() as c:
        report = await apply_retention.dry_run(c)
    assert [r.relation for r in report] == list(WANT)
    assert all(r.chunks <= r.total and r.rows >= 0 for r in report)
    assert {r.relation: r.now_days for r in report} == {x: before[0].get(x) for x in WANT}
    assert await _jobs() == before


async def _old_rows(home_id) -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as s, s.begin():
        for days, tag in ((450, "old"), (10, "new")):
            p = {"h": home_id, "t": now - timedelta(days=days), "k": f"tiers:{tag}:{home_id}"}
            await s.execute(
                text(
                    "INSERT INTO public.tb_alert (home_id, kind, severity, ts, dedup_key) "
                    "VALUES (:h, 'standby_high', 'info', :t, :k)"
                ),
                p,
            )
            await s.execute(
                text(
                    "INSERT INTO public.tb_ingest_batch (source, home_id, started_at) "
                    "VALUES ('tiers', :h, :t)"
                ),
                p,
            )
        for days in (200, 100):  # both past 90 days: only the newer one is the home's last
            await s.execute(
                text(
                    "INSERT INTO public.tb_inference_run (home_id, model_name, model_version, "
                    "window_start, window_end, started_at, status) "
                    "VALUES (:h, 'm', '1', :t, :t, :t, 'ok')"
                ),
                {"h": home_id, "t": now - timedelta(days=days)},
            )


async def _left(home_id) -> list[int]:
    async with SessionLocal() as s:
        return [
            await s.scalar(
                text(f"SELECT count(*) FROM public.{t} WHERE home_id = :h"), {"h": home_id}
            )
            for t in ("tb_alert", "tb_ingest_batch", "tb_inference_run")
        ]


async def test_the_nightly_cleanup_is_off_until_asked(make_member, monkeypatch):
    home = (await make_member("owner")).home_id
    await _old_rows(home)

    await jobs.cleanup(datetime.now(UTC))
    assert settings.retention_tiers is False
    assert await _left(home) == [2, 2, 2]

    monkeypatch.setattr(settings, "retention_tiers", True)
    await jobs.cleanup(datetime.now(UTC))
    assert await _left(home) == [1, 1, 1]  # the last good run stays: it says how far NILM got


async def test_old_tool_calls_go_and_the_messages_stay(make_member, monkeypatch):
    m = await make_member("owner")
    now = datetime.now(UTC)
    async with SessionLocal() as s, s.begin():
        conv = await s.scalar(
            text("INSERT INTO ai.ai_conversation (home_id, user_id) VALUES (:h, :u) RETURNING id"),
            {"h": m.home_id, "u": m.user_id},
        )
        for days in (40, 1):
            msg = await s.scalar(
                text(
                    "INSERT INTO ai.ai_message (conversation_id, role, content, created_at) "
                    "VALUES (:c, 'assistant', 'a', :t) RETURNING id"
                ),
                {"c": conv, "t": now - timedelta(days=days)},
            )
            await s.execute(
                text("INSERT INTO ai.ai_tool_call (message_id, tool, ok) VALUES (:m, 't', true)"),
                {"m": msg},
            )
    monkeypatch.setattr(settings, "retention_tiers", True)
    await jobs.cleanup(now)
    async with SessionLocal() as s:
        row = (
            await s.execute(
                text(
                    "SELECT count(*) AS messages, count(t.id) AS calls FROM ai.ai_message m "
                    "LEFT JOIN ai.ai_tool_call t ON t.message_id = m.id "
                    "WHERE m.conversation_id = :c"
                ),
                {"c": conv},
            )
        ).one()
    assert (row.messages, row.calls) == (2, 1)


async def test_a_window_older_than_the_minutes_kept_comes_back_hourly(client, make_member):
    m = await make_member("owner")
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    old, recent = now - timedelta(days=450), now - timedelta(days=2)
    async with SessionLocal() as s, s.begin():
        sid = await s.scalar(
            text(
                "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
                "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
            ),
            {"h": m.home_id},
        )
        for at in (old, recent):
            await s.execute(
                text("INSERT INTO public.tb_reading (series_id, ts, value) VALUES (:s, :t, 100)"),
                {"s": sid, "t": at + timedelta(minutes=1)},
            )
    async with engine.connect() as c:
        c = await c.execution_options(isolation_level="AUTOCOMMIT")
        for at in (old, recent):
            await backfill_aggregates(c, at - timedelta(days=1), at + timedelta(days=1))

    async def series(at):
        r = await client.get(
            "/api/v1/energy/series",
            params={"since": at.isoformat(), "until": (at + timedelta(hours=1)).isoformat()},
            headers=m.headers,
        )
        assert r.status_code == 200, r.text
        return [(datetime.fromisoformat(p["ts"]), p["coarsened"]) for p in r.json()]

    assert await series(old) == [(old, True)]  # the hour, not the minute
    assert await series(recent) == [(recent + timedelta(minutes=1), False)]


async def test_maintainers_hear_of_a_home_whose_nilm_lags(make_member, monkeypatch):
    now = datetime.now(UTC)
    homes = []
    async with SessionLocal() as s, s.begin():
        # a shared model, so the homes are NILM targets
        await s.execute(
            text(
                "INSERT INTO public.tb_nilm_model (name, version, artifact, active) "
                "VALUES ('tiers', '1', 'x', true) ON CONFLICT DO NOTHING"
            )
        )
    for behind in (25, 5):
        home = (await make_member("owner")).home_id
        homes.append(home)
        async with SessionLocal() as s, s.begin():
            sid = await s.scalar(
                text(
                    "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
                    "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
                ),
                {"h": home},
            )
            await s.execute(
                text("INSERT INTO public.tb_reading (series_id, ts, value) VALUES (:s, :t, 1)"),
                {"s": sid, "t": now},
            )
            await s.execute(
                text(
                    "INSERT INTO public.tb_ingest_checkpoint (source, series_id, last_ts) "
                    "VALUES ('nilm', :s, :t)"
                ),
                {"s": sid, "t": now - timedelta(days=behind)},
            )
    told = []

    async def tell(message, data=None, **_):
        told.append(message)

    monkeypatch.setattr(notify, "tell_maintainers", tell)
    try:
        await jobs.nilm_lag(now)
    finally:
        async with SessionLocal() as s, s.begin():
            await s.execute(text("DELETE FROM public.tb_nilm_model WHERE name = 'tiers'"))
    assert len(told) == 1
    assert str(homes[0]) in told[0] and str(homes[1]) not in told[0]


def test_rebuild_and_detectors_read_no_further_than_the_runs_are_kept():
    """R1.4: the runs and the minutes are kept 90 days."""
    kept = timedelta(days=WANT["tb_device_cycle"])
    now = datetime.now(UTC)
    for oldest, newest in ((None, None), (now - timedelta(days=500), now - timedelta(days=400))):
        assert now - cycles.since_for(oldest, newest, now) <= kept
    assert detectors.HISTORY <= kept
    # the usual of the night standby and of the unexplained load, on one-minute buckets
    assert timedelta(days=detectors.BASE_DAYS + detectors.RECENT_DAYS + 1) <= kept
    assert timedelta(weeks=device_forecast.RUN_WEEKS) <= kept
