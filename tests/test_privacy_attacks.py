# Attacks on the privacy controls (checklist D9-1, D9-4, D9-5), kept as evidence:
# docs/evidence/privacy/attacks.md lists each one with its outcome. No call leaves the test.

import ast
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.database import SessionLocal

needs_copilot_db = pytest.mark.skipif(
    not settings.copilot_database_url, reason="COPILOT_DATABASE_URL is not set"
)
ROOT = Path(__file__).resolve().parents[1]
ICT = timezone(timedelta(hours=7))


async def _device(home_id):
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO public.tb_device (home_id, device_type_code, name, origin) "
                "VALUES (:h, 'kettle', 'Ấm', 'manual')"
            ),
            {"h": home_id},
        )


async def _token(home_id, detail="daily") -> str:
    async with SessionLocal() as s, s.begin():
        return str(
            await s.scalar(
                text(
                    "INSERT INTO public.tb_scope_token (home_id, detail) VALUES (:h, :d) "
                    "RETURNING token"
                ),
                {"h": home_id, "d": detail},
            )
        )


async def _set_ai_detail(home_id, detail):
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text("UPDATE public.tb_home SET ai_detail = :d WHERE id = :h"),
            {"h": home_id, "d": detail},
        )


# --- D9-1: another home, through the SQL Wappi and custom watches run -------------------------


@needs_copilot_db
async def test_sql_cannot_switch_to_another_home_or_steal_its_token(make_member):
    me = await make_member("owner")
    other = await make_member("owner")
    await _device(other.home_id)
    mine, theirs = await _token(me.home_id), await _token(other.home_id)
    engine = create_async_engine(settings.copilot_database_url)
    try:
        async with engine.connect() as victim, engine.connect() as attacker:
            # Another home's live session, its token bound as text2sql binds it.
            await victim.execute(text("BEGIN"))
            await victim.execute(
                text("SELECT set_config('app.copilot_token', :t, true)"), {"t": theirs}
            )
            await attacker.execute(text("BEGIN"))
            await attacker.execute(
                text("SELECT set_config('app.copilot_token', :t, true)"), {"t": mine}
            )
            count = "SELECT count(*) FROM copilot_ro.device"
            assert await attacker.scalar(text(count)) == 0
            # 1. Name the other home instead of a token, or a guessed token.
            for forged in (str(other.home_id), str(uuid.uuid4())):
                await attacker.execute(
                    text("SELECT set_config('app.copilot_token', :t, true)"), {"t": forged}
                )
                assert await attacker.scalar(text(count)) == 0
            # 2. The other session's statements carry no token: it is a bind parameter.
            seen = (await attacker.scalars(text("SELECT query FROM pg_stat_activity"))).all()
            assert not any(theirs in (q or "") for q in seen)
            await attacker.rollback()
            await victim.rollback()
        # 3. Read the tokens, or the tables under the views.
        for sql in (
            "SELECT token FROM public.tb_scope_token",
            "SELECT count(*) FROM public.tb_device",
            "SELECT count(*) FROM public.reading_1m",
            "SELECT count(*) FROM public.tb_device_cycle",
        ):
            async with engine.connect() as c:
                with pytest.raises(Exception, match="permission denied"):
                    await c.execute(text(sql))
    finally:
        await engine.dispose()


@needs_copilot_db
async def test_a_custom_watch_cannot_write(make_member):
    from app.modules.insight.services.watches import run_sql

    me = await make_member("owner")
    other = await make_member("owner")
    await _device(other.home_id)
    for sql in (
        "SELECT 1; DELETE FROM public.tb_device",
        "SELECT count(*) FROM copilot_ro.device) q; DELETE FROM public.tb_device; SELECT (1",
        "WITH d AS (DELETE FROM copilot_ro.device RETURNING 1) SELECT count(*) FROM d",
    ):
        with pytest.raises(Exception):  # noqa: B017 - any refusal, as long as nothing runs
            await run_sql(me.home_id, sql)
    async with SessionLocal() as s:
        n = await s.scalar(
            text("SELECT count(*) FROM public.tb_device WHERE home_id = :h"), {"h": other.home_id}
        )
    assert n == 1


# --- D9-1: finer than a day, at the daily level -----------------------------------------------


async def _readings(home_id, hours=3):
    from app.modules.ops.services.ingest import ReadingRow, ingest_readings

    serial = f"attack-{home_id}"
    async with SessionLocal() as s, s.begin():
        meter = await s.scalar(
            text("INSERT INTO public.tb_meter (serial, home_id) VALUES (:s, :h) RETURNING id"),
            {"s": serial, "h": home_id},
        )
        await s.execute(
            text(
                "INSERT INTO public.tb_series (home_id, meter_id, source_channel, kind, metric, "
                "unit) VALUES (:h, :m, 'agg', 'main', 'power_w', 'W')"
            ),
            {"h": home_id, "m": meter},
        )
    start = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(hours=hours)
    rows = [ReadingRow(start + timedelta(minutes=i), "agg", 500.0) for i in range(hours * 60)]
    async with SessionLocal() as s, s.begin():
        await ingest_readings(s, serial, rows, "test")
    return meter


async def _drop_meter(meter):
    async with SessionLocal() as s, s.begin():
        await s.execute(text("DELETE FROM public.tb_series WHERE meter_id = :m"), {"m": meter})
        await s.execute(text("DELETE FROM public.tb_meter WHERE id = :m"), {"m": meter})


@needs_copilot_db
async def test_a_daily_home_reads_no_hour_even_past_the_name_check(make_member):
    from app.modules.insight.services.watches import run_sql

    me = await make_member("owner", ai_detail="hourly")
    meter = await _readings(me.home_id)
    try:
        # The app refuses `reading_1h` by name; spell it so the name check misses it.
        sneaky = 'SELECT count(*) FROM copilot_ro.U&"reading\\005f1h"'
        assert await run_sql(me.home_id, sneaky) > 0  # hours are there, for an hourly home
        await _set_ai_detail(me.home_id, "daily")
        assert await run_sql(me.home_id, sneaky) == 0  # the view itself answers nothing
        assert await run_sql(me.home_id, sneaky.replace("1h", "1d")) > 0  # days still are
    finally:
        await _drop_meter(meter)


@needs_copilot_db
async def test_an_alert_id_does_not_tell_its_time(client, make_member):
    from sqlalchemy.dialects.postgresql import insert

    from app.modules.insight.models import Alert
    from app.modules.insight.services.watches import run_sql

    owner = await make_member("owner")
    daily = await make_member("member", home_id=owner.home_id)
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text("UPDATE public.tb_home_member SET detail = 'daily' WHERE user_id = :u"),
            {"u": daily.user_id},
        )
        # As detectors and watches insert one: a kettle switched on at 06:42.
        alert_id = await s.scalar(
            insert(Alert)
            .values(
                home_id=owner.home_id,
                kind="device_on",
                severity="warning",
                ts=datetime.now(UTC),
                payload={"device": "Ấm", "at": datetime.now(UTC).isoformat()},
                dedup_key=f"attack:{uuid.uuid4()}",
            )
            .returning(Alert.id)
        )
    # A UUIDv7 id holds its creation time to the millisecond: this one is random.
    assert alert_id.version == 4
    (seen,) = (await client.get("/api/v1/insights/alerts", headers=daily.headers)).json()
    assert uuid.UUID(seen["id"]).version == 4 and "at" not in seen["payload"]
    sql = "SELECT count(uuid_extract_timestamp(id)) FROM copilot_ro.alert"
    assert await run_sql(owner.home_id, sql) == 0


async def test_wappi_at_daily_does_not_compare_part_of_a_day(make_member):
    from app.modules.copilot.services import tools

    me = await make_member("owner")
    at = datetime(2026, 11, 24, 15, 10, tzinfo=ICT).astimezone(UTC)
    async with SessionLocal() as s:
        # Asked each hour, "today so far against yesterday at this hour" rebuilds the hours.
        out = await tools.explain_usage(tools.Ctx(s, me.home_id, at, "vi"), "today")
    assert "daily" in out.data["error"]


# --- D9-1: a removed or departed member -------------------------------------------------------


async def _wants_mail(user_id):
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO public.tb_user_preference (user_id, notify_anomaly, weekly_summary) "
                "VALUES (:u, true, true) ON CONFLICT (user_id) DO UPDATE "
                "SET notify_anomaly = true, weekly_summary = true"
            ),
            {"u": user_id},
        )


async def _email(user_id):
    async with SessionLocal() as s:
        return await s.scalar(
            text("SELECT email FROM public.tb_users WHERE id = :u"), {"u": user_id}
        )


async def test_a_removed_or_departed_member_gets_nothing_more(client, make_member, monkeypatch):
    from app.modules.insight.services import mail

    sent = []

    async def fake_send(to, subject, body):
        sent.append(to)

    monkeypatch.setattr(mail, "send", fake_send)
    email = ("wappi", "voice", "email")
    owner = await make_member("owner", consent=email)
    removed = await make_member("member", home_id=owner.home_id, consent=email)
    left = await make_member("member", home_id=owner.home_id, consent=email)
    for m in (owner, removed, left):
        await _wants_mail(m.user_id)
    one = f"/api/v1/homes/current/members/{removed.user_id}"
    assert (await client.delete(one, headers=owner.headers)).status_code == 204
    r = await client.delete("/api/v1/homes/current/membership", headers=left.headers)
    assert r.status_code == 204

    for m in (removed, left):  # their old token still signs in, but reaches no home
        for path in ("/energy/overview", "/insights/alerts", "/billing/current"):
            r = await client.get(f"/api/v1{path}", headers=m.headers)
            assert r.status_code == 404, path
    now = datetime.now(UTC)
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO public.tb_alert (home_id, kind, severity, ts, payload, dedup_key) "
                "VALUES (:h, 'standby_high', 'warning', :t, CAST(:p AS jsonb), :k)"
            ),
            {
                "h": owner.home_id,
                "t": now,
                "p": '{"nights": 3, "recent_w": 90, "usual_w": 40}',
                "k": f"attack:{uuid.uuid4()}",
            },
        )
    await mail.mail_alerts(now)
    monday = datetime(2026, 11, 30, 9, tzinfo=ICT).astimezone(UTC)
    await mail.mail_weekly(monday)
    owner_email = await _email(owner.user_id)
    assert sent.count(owner_email) == 2  # the alert and the week: mail does go out
    for m in (removed, left):
        assert await _email(m.user_id) not in sent


# --- D9-4: an alert's mail names no clock time, for anyone ------------------------------------

CLOCK = re.compile(r"\d{1,2}[:h]\d{2}|\d{1,2} ?giờ|\bAM\b|\bPM\b")
AT = "2026-11-21T23:42:00+00:00"  # 06:42 local
MAILS = [
    ("device_on", {"device": "Ấm", "at": AT, "watch_id": "w", "label": "Ấm"}),
    ("device_off", {"device": "Ấm", "at": AT, "watch_id": "w", "label": "Ấm"}),
    ("device_long_run", {"device": "Ấm", "threshold": 30, "value": 45, "at": AT}),
    ("device_high_power", {"device": "Ấm", "threshold": 2000, "value": 2400, "at": AT}),
    ("watch_hit", {"label": "Điện hôm nay", "op": "gt", "threshold": 5, "unit": "kwh", "value": 6}),
    ("watch_broken", {"label": "Điện hôm nay"}),
    ("longer_than_usual", {"days": 3, "recent_min": 50, "usual_min": 30}),
    ("usage_anomaly", {"start": AT, "excess_kwh": 2.0, "excess_vnd": 6000, "activity_ratio": 2}),
    ("unexplained_load", {"minutes": 40, "watts": 300, "usual_w": 100}),
    ("standby_high", {"nights": 3, "recent_w": 90, "usual_w": 40}),
    ("tier_near", {"days": 2, "tier_no": 4, "from_kwh": 200, "price_per_kwh": 2900}),
    *[
        ("device_anomaly", {"signal": sig, "value": 6, "usual": 1.5, "excess_vnd": 900, "at": AT})
        for sig in ("long_run", "odd_hour", "denser", "daily")
    ],
]


@pytest.mark.parametrize(
    ("kind", "payload"), MAILS, ids=[f"{k}-{p.get('signal', '')}" for k, p in MAILS]
)
def test_an_alert_mail_names_no_clock_time(kind, payload):
    from app.modules.insight.services.mail import alert_text

    subject, body = alert_text(SimpleNamespace(kind=kind, payload=payload), "Ấm")
    assert not CLOCK.search(subject + " " + body), (subject, body)


# --- D9-5: no token or personal data in a log line --------------------------------------------

LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
# Names that hold secrets or what a person wrote or is: never an argument of a log call.
SENSITIVE = {
    "text", "content", "body", "json", "headers", "email", "phone", "password", "secret",
    "token", "access_token", "refresh_token", "authorization", "question", "answer", "reply",
    "transcript", "words", "audio", "full_name", "address", "postal_code",
}  # fmt: skip


def _log_calls(tree):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LOG_METHODS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in {"log", "logger", "logging"}
        ):
            yield node


def _names(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            yield n.id
        elif isinstance(n, ast.Attribute):
            yield n.attr


def test_no_log_call_prints_a_token_or_personal_data():
    found = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        for call in _log_calls(ast.parse(path.read_text(), str(path))):
            args = [*call.args, *(k.value for k in call.keywords if k.arg != "exc_info")]
            bad = {n for a in args for n in _names(a)} & SENSITIVE
            if bad:
                found.append(f"{path.relative_to(ROOT)}:{call.lineno} {sorted(bad)}")
    assert found == [], "a log call prints what it must not:\n" + "\n".join(found)


def test_the_scan_catches_a_raw_body():
    tree = ast.parse('log.warning("refused (%s): %s", r.status_code, r.text[:300])')
    (call,) = _log_calls(tree)
    assert "text" in {n for a in call.args for n in _names(a)}


async def test_a_keycloak_refusal_logs_no_response_body(monkeypatch, caplog):
    from app.modules.auth.services import demo

    leak = "guest-123@demo.example"

    def refuse(request):
        return httpx.Response(409, json={"errorMessage": f"User exists with same email {leak}"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as client:
        kc = demo._Keycloak(client)
        with caplog.at_level(logging.WARNING, logger=demo.log.name):
            for call in (kc.create(leak, "pw"), kc.grant(leak, "pw")):
                with pytest.raises(demo.DemoUnavailableError):
                    await call
    assert caplog.records and leak not in caplog.text and "User exists" not in caplog.text
