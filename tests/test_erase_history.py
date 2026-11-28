import json
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import text

from app.database import SessionLocal, engine
from app.modules.energy.services.aggregates import backfill_aggregates

ICT = timezone(timedelta(hours=7))
TODAY = datetime.now(ICT).replace(hour=0, minute=0, second=0, microsecond=0)
OLD, KEPT = TODAY - timedelta(days=40), TODAY - timedelta(days=3)
RAW = ("tb_reading", "tb_device_estimate")
VIEWS = tuple(
    f"{family}_{res}" for family in ("reading", "device_estimate") for res in ("1m", "1h", "1d")
)


async def seed(home_id) -> int:
    """A main series with readings and estimates on an old day and a kept day, aggregated, plus
    one alert and one device run on each."""
    async with SessionLocal() as s, s.begin():
        sid = await s.scalar(
            text(
                "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
                "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
            ),
            {"h": home_id},
        )
        device = await s.scalar(
            text(
                "INSERT INTO public.tb_device (home_id, device_type_code, name, origin) "
                "VALUES (:h, 'kettle', 'Kettle', 'nilm') RETURNING id"
            ),
            {"h": home_id},
        )
        for day in (OLD, KEPT):
            for table in RAW:
                await s.execute(
                    text(f"INSERT INTO {table} (series_id, ts, value) VALUES (:s, :t, 100)"),
                    {"s": sid, "t": day + timedelta(hours=1)},
                )
            await s.execute(
                text(
                    "INSERT INTO public.tb_alert (home_id, kind, severity, ts, dedup_key) "
                    "VALUES (:h, 'standby_high', 'info', :t, :k)"
                ),
                {"h": home_id, "t": day + timedelta(hours=2), "k": f"erase:{day.date()}:{sid}"},
            )
            await s.execute(
                text(
                    "INSERT INTO public.tb_device_cycle (home_id, device_id, start_ts, end_ts, "
                    "energy_wh, peak_w) VALUES (:h, :d, :s, :e, 5, 100)"
                ),
                {
                    "h": home_id,
                    "d": device,
                    "s": day + timedelta(hours=3),
                    "e": day + timedelta(hours=3, minutes=3),
                },
            )
    async with engine.connect() as c:
        c = await c.execution_options(isolation_level="AUTOCOMMIT")
        for day in (OLD, KEPT):
            await backfill_aggregates(c, day, day + timedelta(days=1))
    return sid


async def counts(home_id, sid) -> dict[str, int]:
    out = {}
    async with SessionLocal() as s:
        for name in RAW + VIEWS:
            out[name] = await s.scalar(
                text(f"SELECT count(*) FROM public.{name} WHERE series_id = :s"), {"s": sid}
            )
        for table in ("tb_alert", "tb_device_cycle"):
            out[table] = await s.scalar(
                text(f"SELECT count(*) FROM public.{table} WHERE home_id = :h"), {"h": home_id}
            )
    return out


async def test_erasing_before_a_day_leaves_nothing_older_and_no_other_home_changes(
    client, make_member
):
    owner, other = await make_member("owner"), await make_member("owner")
    mine, theirs = await seed(owner.home_id), await seed(other.home_id)
    both = await counts(owner.home_id, mine)
    assert set(both.values()) == {2}, both
    before_other = await counts(other.home_id, theirs)

    cut = (KEPT - timedelta(days=1)).date().isoformat()
    r = await client.delete(f"/api/v1/homes/current/history?before={cut}", headers=owner.headers)

    assert r.status_code == 204, r.text
    assert set((await counts(owner.home_id, mine)).values()) == {1}  # the kept day only
    assert await counts(other.home_id, theirs) == before_other
    async with SessionLocal() as s:
        mark = await s.scalar(
            text("SELECT history_erased_before FROM public.tb_home WHERE id = :h"),
            {"h": owner.home_id},
        )
    assert mark.astimezone(ICT).date().isoformat() == cut


async def test_erasing_everything_leaves_no_measurement(client, make_member):
    owner = await make_member("owner")
    sid = await seed(owner.home_id)
    r = await client.delete("/api/v1/homes/current/history", headers=owner.headers)
    assert r.status_code == 204, r.text
    assert set((await counts(owner.home_id, sid)).values()) == {0}
    async with SessionLocal() as s:  # the home and its device stay
        assert await s.scalar(
            text("SELECT count(*) FROM public.tb_device WHERE home_id = :h"), {"h": owner.home_id}
        )


async def test_only_the_owner_erases(client, make_member):
    owner = await make_member("owner")
    sid = await seed(owner.home_id)
    for role in ("member", "viewer"):
        person = await make_member(role, home_id=owner.home_id)
        r = await client.delete("/api/v1/homes/current/history", headers=person.headers)
        assert r.status_code == 403, role
    assert set((await counts(owner.home_id, sid)).values()) == {2}


async def test_a_demo_home_refuses(client, make_member, monkeypatch, tmp_path):
    from app.config import settings

    owner = await make_member("owner")
    sid = await seed(owner.home_id)
    async with SessionLocal() as s:
        email = await s.scalar(
            text("SELECT email FROM public.tb_users WHERE id = :u"), {"u": owner.user_id}
        )
    toml = tmp_path / "demo.toml"
    toml.write_text(
        f'[[home]]\nhouse = 99\nowner = {{ email = "{email}", name = "x" }}\ndevices = {{}}\n'
    )
    monkeypatch.setattr(settings, "demo_homes_file", str(toml))
    r = await client.delete("/api/v1/homes/current/history", headers=owner.headers)
    assert (r.status_code, r.json()["code"]) == (403, "demo_home_read_only")
    assert set((await counts(owner.home_id, sid)).values()) == {2}


async def test_a_meter_cannot_send_the_erased_readings_again(client, make_member):
    from app.modules.ops.services.ingest import ReadingRow, ingest_readings

    owner = await make_member("owner")
    async with SessionLocal() as s, s.begin():
        meter = await s.scalar(
            text("INSERT INTO public.tb_meter (serial, home_id) VALUES (:s, :h) RETURNING id"),
            {"s": f"erase-{owner.home_id}", "h": owner.home_id},
        )
        await s.execute(
            text(
                "INSERT INTO public.tb_series (home_id, meter_id, source_channel, kind, metric, "
                "unit) VALUES (:h, :m, 'agg', 'main', 'power_w', 'W')"
            ),
            {"h": owner.home_id, "m": meter},
        )
    cut = TODAY.date().isoformat()
    r = await client.delete(f"/api/v1/homes/current/history?before={cut}", headers=owner.headers)
    assert r.status_code == 204, r.text
    rows = [
        ReadingRow((TODAY - timedelta(days=1)).astimezone(UTC), "agg", 100.0),
        ReadingRow((TODAY + timedelta(minutes=1)).astimezone(UTC), "agg", 100.0),
    ]
    try:
        async with SessionLocal() as s, s.begin():
            got = await ingest_readings(s, f"erase-{owner.home_id}", rows, "test")
        assert (got.rows_new, got.rows_bad) == (1, 1)
    finally:  # a meter keeps its home from being deleted
        async with SessionLocal() as s, s.begin():
            await s.execute(text("DELETE FROM public.tb_series WHERE meter_id = :m"), {"m": meter})
            await s.execute(text("DELETE FROM public.tb_meter WHERE id = :m"), {"m": meter})


async def test_all_my_chats_go_at_once(client, make_member):
    me = await make_member("owner")
    other = await make_member("member", home_id=me.home_id)
    async with SessionLocal() as s, s.begin():
        for user in (me, me, other):
            await s.execute(
                text("INSERT INTO ai.ai_conversation (home_id, user_id) VALUES (:h, :u)"),
                {"h": me.home_id, "u": user.user_id},
            )
    r = await client.delete("/api/v1/copilot/conversations", headers=me.headers)
    assert r.status_code == 204
    async with SessionLocal() as s:
        left = (
            await s.execute(
                text("SELECT user_id FROM ai.ai_conversation WHERE home_id = :h"), {"h": me.home_id}
            )
        ).scalars()
        assert list(left) == [other.user_id]


async def test_bills_follow_the_daily_totals(client, make_member):
    owner = await make_member("owner", tariff_plan_code="vn_residential")
    await seed(owner.home_id)
    async with SessionLocal() as s, s.begin():
        from app.modules.billing.api import refresh_bills

        await refresh_bills(s, owner.home_id)

    async def periods():
        async with SessionLocal() as s:
            rows = await s.execute(
                text(
                    "SELECT period_start, period_end, status FROM public.tb_bill "
                    "WHERE home_id = :h ORDER BY period_start"
                ),
                {"h": owner.home_id},
            )
            return rows.all()

    before = await periods()
    assert any(p.period_end < KEPT.date() for p in before), before  # a cycle wholly older
    r = await client.delete(
        f"/api/v1/homes/current/history?before={(KEPT - timedelta(days=1)).date()}",
        headers=owner.headers,
    )
    assert r.status_code == 204
    after = await periods()
    assert all(p.period_end >= (KEPT - timedelta(days=1)).date() for p in after)  # older gone
    cut = [p for p in after if p.period_start < KEPT.date() <= p.period_end]
    assert all(p.status != "final" for p in cut), cut  # a cut cycle is not presented as complete


async def test_deleting_the_account_leaves_no_row_about_the_home(client, make_member, monkeypatch):
    import httpx

    from app.config import settings
    from app.modules.auth.services import demo

    def keycloak(request):
        if request.method == "POST":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(204)

    monkeypatch.setattr(settings, "demo_admin_client_secret", "s")
    monkeypatch.setattr(demo, "_transport", httpx.MockTransport(keycloak))
    owner = await make_member("owner")
    async with SessionLocal() as s, s.begin():
        meter = await s.scalar(
            text(
                "INSERT INTO public.tb_meter (serial, home_id, last_seen_at) "
                "VALUES (:s, :h, now()) RETURNING id"
            ),
            {"s": f"gone-{owner.home_id}", "h": owner.home_id},
        )
        await s.execute(
            text(
                "INSERT INTO public.tb_ingest_batch (source, home_id, status, started_at) "
                "VALUES ('test', :h, 'ok', now())"
            ),
            {"h": owner.home_id},
        )
    async with SessionLocal() as s:  # the copy a trigger keeps for the AI schema
        assert await s.scalar(
            text("SELECT count(*) FROM ai.dim_home WHERE source_home_id = :h"), {"h": owner.home_id}
        )
    try:
        assert (await client.delete("/api/v1/users/me", headers=owner.headers)).status_code == 204
        async with SessionLocal() as s:
            for sql in (
                "SELECT count(*) FROM ai.dim_home WHERE source_home_id = :h",
                "SELECT count(*) FROM public.tb_ingest_batch WHERE home_id = :h",
            ):
                assert await s.scalar(text(sql), {"h": owner.home_id}) == 0, sql
            assert (
                await s.scalar(
                    text("SELECT last_seen_at FROM public.tb_meter WHERE id = :m"), {"m": meter}
                )
                is None
            )
    finally:
        async with SessionLocal() as s, s.begin():
            await s.execute(text("DELETE FROM public.tb_meter WHERE id = :m"), {"m": meter})


async def seed_derived(home_id, user_id) -> None:
    """A suggestion, an expected hour and a forecast on each side of the cut, and a plan started
    on the old day (made today) that holds both days."""
    days = {d.date().isoformat(): {"expected": 1.0, "kwh": 1.0} for d in (OLD, KEPT)}
    async with SessionLocal() as s, s.begin():
        for day in (OLD, KEPT):
            p = {"h": home_id, "t": day + timedelta(hours=4)}
            await s.execute(
                text(
                    "INSERT INTO public.tb_suggestion (home_id, kind, title, body, created_at) "
                    "VALUES (:h, 'tip', 't', 'b', :t)"
                ),
                p,
            )
            await s.execute(
                text(
                    "INSERT INTO public.tb_expect_hourly (home_id, ts, p05, p10, p50, p90, p95, "
                    "c_weather, c_calendar, c_occupancy, c_trend, c_base, model_version) "
                    "VALUES (:h, :t, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 'v')"
                ),
                p,
            )
            await s.execute(
                text(
                    "INSERT INTO public.tb_forecast_snapshot (home_id, generated_at, "
                    "horizon_date, kwh, amount, model_version) "
                    "VALUES (:h, :t, current_date, 1, 1, 'v')"
                ),
                p,
            )
        await s.execute(
            text(
                "INSERT INTO public.tb_savings_plan (user_id, home_id, start_on, end_on, "
                "model_version, forecast_kwh, actions, days) VALUES (:u, :h, :a, :b, 'v', 10, "
                "'[]'::jsonb, CAST(:d AS jsonb))"
            ),
            {
                "u": user_id,
                "h": home_id,
                "a": OLD.date(),
                "b": TODAY.date(),
                "d": json.dumps(days),
            },
        )


async def test_derived_rows_go_by_their_own_date_and_a_plan_keeps_only_kept_days(
    client, make_member
):
    owner = await make_member("owner")
    await seed_derived(owner.home_id, owner.user_id)
    cut = (KEPT - timedelta(days=1)).date().isoformat()
    r = await client.delete(f"/api/v1/homes/current/history?before={cut}", headers=owner.headers)
    assert r.status_code == 204, r.text
    async with SessionLocal() as s:
        for table in ("tb_suggestion", "tb_expect_hourly", "tb_forecast_snapshot"):
            n = await s.scalar(
                text(f"SELECT count(*) FROM public.{table} WHERE home_id = :h"),
                {"h": owner.home_id},
            )
            assert n == 1, table
        days = await s.scalar(
            text("SELECT days FROM public.tb_savings_plan WHERE home_id = :h"),
            {"h": owner.home_id},
        )
    assert list(days) == [KEPT.date().isoformat()]  # the plan stays, its erased day does not


async def test_the_nightly_refresh_does_not_predict_erased_days_again(make_member, monkeypatch):
    import pandas as pd

    from app.modules.expect.services import refresh

    owner = await make_member("owner", history_erased_before=KEPT)
    asked = []

    async def bundle(*_):
        return SimpleNamespace(version="v")

    async def frame(_s, _h, lo, *_):
        asked.append(lo)
        return None

    monkeypatch.setattr(refresh, "active_bundle", bundle)
    monkeypatch.setattr(refresh, "feature_frame", frame)
    monkeypatch.setattr(refresh, "predict", lambda *_: pd.DataFrame(columns=refresh.HOUR_COLS))
    async with SessionLocal() as s, s.begin():
        await refresh.refresh_home(s, owner.home_id, datetime.now(UTC))
    assert asked == [KEPT]


async def test_another_homes_totals_survive_without_their_raw_rows(client, make_member):
    owner, other = await make_member("owner"), await make_member("owner")
    await seed(owner.home_id)
    theirs = await seed(other.home_id)
    async with SessionLocal() as s, s.begin():  # as retention leaves them
        for table in RAW:
            await s.execute(text(f"DELETE FROM {table} WHERE series_id = :s"), {"s": theirs})

    async def totals():
        async with SessionLocal() as s:
            return {
                v: (
                    await s.execute(
                        text(
                            f"SELECT * FROM public.{v} WHERE series_id = :s "
                            "AND bucket < :t ORDER BY bucket"
                        ),
                        {"s": theirs, "t": KEPT},
                    )
                ).all()
                for v in ("reading_1h", "reading_1d")
            }

    before = await totals()
    assert all(before.values())
    r = await client.delete("/api/v1/homes/current/history", headers=owner.headers)
    assert r.status_code == 204, r.text
    async with engine.connect() as c:
        c = await c.execution_options(isolation_level="AUTOCOMMIT")
        await backfill_aggregates(c, OLD, OLD + timedelta(days=1))
    assert await totals() == before
