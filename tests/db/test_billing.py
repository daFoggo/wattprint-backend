from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.models import Bill, BillItem, Home, TariffPlan, TariffTier, TariffVersion
from app.modules.billing.services.bill import _allocate, _cycle_start, compute_bill, current_bill
from app.modules.energy.services.aggregates import backfill_aggregates as backfill
from tests.db.conftest import _create_migrated_db, relations, run_alembic

PLAN = "vn_residential"
ICT = timedelta(hours=7)
V1279 = date(2025, 5, 10)
V2892 = date(2026, 11, 1)
# A lock hang must fail loudly instead of stalling the run.
LOCK_TIMEOUT = {"server_settings": {"lock_timeout": "5000"}}


def local_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC) - ICT


@pytest.fixture(scope="module")
async def bdb():
    """Private migrated database (policies off); yields (AUTOCOMMIT connection, dsn)."""
    dsn, drop = await _create_migrated_db()
    engine = create_async_engine(dsn, isolation_level="AUTOCOMMIT", connect_args=LOCK_TIMEOUT)
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT public.set_policies(false)"))
            yield c, dsn
    finally:
        await engine.dispose()
        await drop()


@pytest.fixture
async def bsession(bdb):
    engine = create_async_engine(bdb[1], connect_args=LOCK_TIMEOUT)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as s:
            yield s
    finally:
        await engine.dispose()


@asynccontextmanager
async def home(c, session, cycle_day=1, plan=PLAN):
    """A committed home with a main series; everything it owns is removed afterwards."""
    hid = await c.scalar(
        text(
            "INSERT INTO public.tb_home (name, billing_cycle_day, tariff_plan_code) "
            "VALUES ('Bill', :d, :p) RETURNING id"
        ),
        {"d": cycle_day, "p": plan},
    )
    sid = await c.scalar(
        text(
            "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
            "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
        ),
        {"h": hid},
    )
    sids = [sid]
    ctx = {"id": hid, "main": sid, "sids": sids}
    try:
        yield ctx
    finally:
        await session.rollback()  # release row locks held by an uncommitted bill insert
        for s in sids:
            for t in ("reading", "device_estimate"):
                await c.execute(text(f"DELETE FROM public.tb_{t} WHERE series_id = :s"), {"s": s})
        await c.execute(text("DELETE FROM public.tb_home WHERE id = :i"), {"i": hid})


async def load(c, sid, start: datetime, minutes: int, watts: float = 1000, table="reading"):
    """One reading per minute at constant power: exactly watts * minutes / 60 Wh."""
    await c.execute(
        text(
            f"INSERT INTO public.tb_{table} (ts, series_id, value) "
            "SELECT CAST(:s AS timestamptz) + g * interval '1 minute', :sid, :w "
            "FROM generate_series(0, :n - 1) g"
        ),
        {"s": start, "sid": sid, "w": watts, "n": minutes},
    )


async def add_device(c, h, name="Fridge"):
    did = await c.scalar(
        text(
            "INSERT INTO public.tb_device (home_id, device_type_code, name, origin) "
            "VALUES (:h, 'fridge', :n, 'nilm') RETURNING id"
        ),
        {"h": h["id"], "n": name},
    )
    sid = await c.scalar(
        text(
            "INSERT INTO public.tb_series (home_id, kind, device_id, metric, unit) "
            "VALUES (:h, 'device', :d, 'power_w', 'W') RETURNING series_id"
        ),
        {"h": h["id"], "d": did},
    )
    h["sids"].append(sid)
    return did, sid


async def bill_for(c, session, h, start: date, kwh: float | None, now=None, watts=1000):
    """Load `kwh` of main-series energy at `watts` from period start, aggregate, compute."""
    if kwh:
        minutes = round(kwh * 1000 / watts * 60)
        await load(c, h["main"], local_midnight(start), minutes, watts)
    await backfill(
        c, local_midnight(start) - timedelta(days=1), local_midnight(start) + timedelta(days=45)
    )
    now = now or local_midnight(start) + timedelta(days=60)
    bill = await compute_bill(session, h["id"], start, now=now)
    await session.commit()
    return bill


# --- running cycle ---


def test_cycle_start_before_and_on_cycle_day():
    assert _cycle_start(date(2026, 11, 12), 1) == date(2026, 11, 1)
    assert _cycle_start(date(2026, 11, 12), 15) == date(2026, 10, 15)
    assert _cycle_start(date(2026, 11, 15), 15) == date(2026, 11, 15)
    assert _cycle_start(date(2026, 1, 3), 28) == date(2025, 12, 28)


async def test_current_bill_prices_today_at_the_margin(bdb, bsession):
    """90 kWh before today, 30 today: today crosses from tier 1 into tier 2 of decision 2892."""
    c, _ = bdb
    today = date(2026, 11, 20)
    async with home(c, bsession) as h:
        await load(c, h["main"], local_midnight(V2892), 30 * 60, 3000)  # 90 kWh on Nov 1-2
        await load(c, h["main"], local_midnight(today), 10 * 60, 3000)  # 30 kWh, 00:00-10:00
        await backfill(c, local_midnight(V2892), local_midnight(today) + timedelta(days=1))
        cur = await current_bill(bsession, h["id"], now=local_midnight(today) + timedelta(hours=12))
        await bsession.commit()
        stored = await c.scalar(
            text("SELECT count(*) FROM public.tb_bill WHERE home_id = :h"), {"h": h["id"]}
        )
    assert stored == 0  # a GET reads only
    assert (cur.period_start, cur.kwh, cur.today_kwh) == (
        V2892,
        Decimal("120.000"),
        Decimal("30.000"),
    )
    assert cur.amount_before_vat == Decimal("235880")  # 100 * 1901 + 20 * 2289
    assert cur.tier_no == 2
    assert [(t.tier_no, t.kwh, t.amount) for t in cur.tiers[:3]] == [
        (1, Decimal("100.000"), Decimal("190100")),
        (2, Decimal("20.000"), Decimal("45780")),
        (3, Decimal("0"), Decimal("0")),
    ]
    assert sum(t.amount for t in cur.tiers) == cur.amount_before_vat
    # T(120) - T(90) = 235880 - 171090 = 64790, plus 8% VAT = 69973.2
    assert cur.today_amount == Decimal("69973")


async def test_current_tier_at_a_boundary_is_the_next_one(bdb, bsession):
    """Exactly 100 kWh fills tier 1, so the next kWh is priced in tier 2; nothing used today."""
    c, _ = bdb
    today = date(2026, 11, 20)
    async with home(c, bsession) as h:
        await load(c, h["main"], local_midnight(V2892), 100 * 60, 1000)
        await backfill(c, local_midnight(V2892), local_midnight(today) + timedelta(days=1))
        cur = await current_bill(bsession, h["id"], now=local_midnight(today) + timedelta(hours=1))
        await bsession.commit()
    assert (cur.kwh, cur.tier_no, cur.today_kwh, cur.today_amount) == (
        Decimal("100.000"),
        2,
        Decimal(0),
        Decimal(0),
    )


# --- tier arithmetic ---


async def test_amount_under_decision_1279_six_tiers(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        b = await bill_for(c, bsession, h, date(2026, 10, 1), 350)
    assert b.kwh_total == Decimal("350.000")
    assert (b.amount_before_vat, b.vat_amount, b.amount_total) == (
        Decimal("907000"),
        Decimal("72560"),
        Decimal("979560"),
    )
    assert b.period_end == date(2026, 10, 31) and b.tariff_straddle is False


async def test_amount_under_decision_2892_five_tiers(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        b = await bill_for(c, bsession, h, V2892, 350)
    assert (b.amount_before_vat, b.vat_amount, b.amount_total) == (
        Decimal("853100"),
        Decimal("68248"),
        Decimal("921348"),
    )
    assert b.period_end == date(2026, 11, 30)


async def test_tier_boundary_exactly_100_kwh_2892(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        b = await bill_for(c, bsession, h, V2892, 100)
    assert b.amount_before_vat == Decimal("190100")  # all in tier 1: (0, 100]


async def test_open_top_tier_800_kwh_2892(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        b = await bill_for(c, bsession, h, V2892, 800, watts=2000)
    # 100*1901 + 100*2289 + 200*2894 + 300*3456 + 100*3844
    assert b.amount_before_vat == Decimal("2419000")


async def test_vat_uses_version_vat_rate(bdb, bsession):
    c, _ = bdb
    await c.execute(
        text("UPDATE public.tb_tariff_version SET vat_rate = 0.1 WHERE valid_from = :d"),
        {"d": V2892},
    )
    try:
        async with home(c, bsession) as h:
            b = await bill_for(c, bsession, h, V2892, 350)
    finally:
        await c.execute(
            text("UPDATE public.tb_tariff_version SET vat_rate = 0.08 WHERE valid_from = :d"),
            {"d": V2892},
        )
    assert (b.vat_amount, b.amount_total) == (Decimal("85310"), Decimal("938410"))


# --- version selection ---


async def test_version_chosen_by_period_start(bdb, bsession):
    c, _ = bdb
    vid = {
        d: await c.scalar(
            text("SELECT id FROM public.tb_tariff_version WHERE valid_from = :d"), {"d": d}
        )
        for d in (V1279, V2892)
    }
    async with home(c, bsession) as h:
        old = await compute_bill(bsession, h["id"], date(2026, 10, 1))
        new = await compute_bill(bsession, h["id"], date(2026, 11, 1))
        got = [(b.version_id, b.tariff_straddle) for b in (old, new)]  # rollback expires them
    assert got == [(vid[V1279], False), (vid[V2892], False)]


async def test_straddle_flag_when_version_changes_inside_period(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession, cycle_day=15) as h:
        b = await bill_for(c, bsession, h, date(2026, 10, 15), 100)
    assert b.period_end == date(2026, 11, 14)
    assert b.tariff_straddle is True
    # whole period at 1279 prices: 50*1984 + 50*2050
    assert b.amount_before_vat == Decimal("201700")


async def test_no_version_or_plan_raises_lookup_error(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        with pytest.raises(LookupError):
            await compute_bill(bsession, h["id"], date(2025, 1, 1))
    async with home(c, bsession, plan=None) as h:
        with pytest.raises(LookupError):
            await compute_bill(bsession, h["id"], date(2026, 10, 1))


async def test_period_start_must_match_cycle_day(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession, cycle_day=1) as h:
        with pytest.raises(ValueError):
            await compute_bill(bsession, h["id"], date(2026, 10, 15))
    async with home(c, bsession, cycle_day=15) as h:
        with pytest.raises(ValueError):
            await compute_bill(bsession, h["id"], date(2026, 10, 1))
        assert (await compute_bill(bsession, h["id"], date(2026, 10, 15))).period_end == date(
            2026, 11, 14
        )


# --- persistence, status, items ---


async def test_compute_bill_is_idempotent(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        did, dsid = await add_device(c, h)
        await load(c, dsid, local_midnight(V2892), 2400, table="device_estimate")
        first = await bill_for(c, bsession, h, V2892, 100)
        first_id, first_total = first.id, first.amount_total
        again = await compute_bill(
            bsession, h["id"], V2892, now=local_midnight(V2892) + timedelta(days=60)
        )
        await bsession.commit()
        count = await c.scalar(
            text("SELECT count(*) FROM public.tb_bill WHERE home_id = :h"), {"h": h["id"]}
        )
        items = await c.scalar(
            text("SELECT count(*) FROM public.tb_bill_item WHERE bill_id = :b"), {"b": first_id}
        )
    assert again.id == first_id and again.amount_total == first_total
    assert count == 1
    assert items == 2  # device + other, not duplicated


async def test_partial_status_when_coverage_low(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        b = await bill_for(c, bsession, h, V2892, 10)
    assert b.status == "partial" and b.coverage < Decimal("0.95")


async def test_status_open_then_closed_with_full_coverage(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        await load(c, h["main"], local_midnight(V2892), 30 * 1440)
        await backfill(
            c, local_midnight(V2892) - timedelta(days=1), local_midnight(V2892) + timedelta(days=45)
        )
        mid = local_midnight(date(2026, 11, 15))
        opened = await compute_bill(bsession, h["id"], V2892, now=mid)
        assert (opened.status, opened.coverage) == ("open", Decimal("1.0000"))
        closed = await compute_bill(bsession, h["id"], V2892, now=local_midnight(date(2026, 12, 3)))
        assert (closed.id, closed.status, closed.coverage) == (
            opened.id,
            "closed",
            Decimal("1.0000"),
        )
        assert closed.kwh_total == Decimal("720.000")


async def test_device_item_share_40_percent(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        did, dsid = await add_device(c, h, "Aircon")
        await load(c, dsid, local_midnight(V2892), 2400, table="device_estimate")  # 40 kWh
        b = await bill_for(c, bsession, h, V2892, 100)
        items = (
            (await bsession.execute(select(BillItem).where(BillItem.bill_id == b.id)))
            .scalars()
            .all()
        )
        bsession.expunge_all()  # keep loaded values readable after the cleanup rollback
    dev = next(i for i in items if i.device_id == did)
    assert (dev.label, dev.kwh, dev.share) == ("Aircon", Decimal("40.000"), Decimal("0.400000"))
    assert dev.amount == Decimal("76040.00")  # 40% of 190100
    other = next(i for i in items if i.device_id is None)
    assert (other.label, other.kwh) == ("other", Decimal("60.000"))


async def test_device_item_share_and_amounts_sum_to_before_vat(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        _, a = await add_device(c, h, "A")
        _, b2 = await add_device(c, h, "B")
        await load(c, a, local_midnight(V2892), 2000, table="device_estimate")  # 33.333 kWh
        await load(c, b2, local_midnight(V2892), 1500, table="device_estimate")  # 25 kWh
        b = await bill_for(c, bsession, h, V2892, 100)
        items = (
            (await bsession.execute(select(BillItem).where(BillItem.bill_id == b.id)))
            .scalars()
            .all()
        )
        bsession.expunge_all()
    assert len(items) == 3
    assert sum(i.amount for i in items) == b.amount_before_vat
    assert sum(i.kwh for i in items) == pytest.approx(Decimal("100"), abs=Decimal("0.002"))


async def test_home_without_readings_is_partial_zero(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        b = await bill_for(c, bsession, h, V2892, None)
        n = await c.scalar(
            text("SELECT count(*) FROM public.tb_bill_item WHERE bill_id = :b"), {"b": b.id}
        )
    assert (b.kwh_total, b.amount_before_vat, b.vat_amount, b.amount_total) == (
        Decimal("0.000"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    )
    assert b.coverage == Decimal("0.0000") and b.status == "partial" and n == 0


async def _bill_items(session, bill):
    items = (
        (await session.execute(select(BillItem).where(BillItem.bill_id == bill.id))).scalars().all()
    )
    return sorted(items, key=lambda i: (i.device_id is None, -i.kwh))


async def test_remainder_lands_on_other(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        _, a = await add_device(c, h, "A")
        _, b2 = await add_device(c, h, "B")
        await load(c, a, local_midnight(V2892), 3000, table="device_estimate")  # 50 kWh
        await load(c, b2, local_midnight(V2892), 3000, table="device_estimate")  # 50 kWh
        b = await bill_for(c, bsession, h, V2892, 350)
        items = await _bill_items(bsession, b)
        got = [(i.label, i.amount) for i in items]
        before = b.amount_before_vat
    # 853100 * (50/350) rounds to 121871 twice; other's exact share rounds to 609357, and the
    # +1 dong rounding remainder lands on it
    assert sorted(got) == [
        ("A", Decimal("121871")),
        ("B", Decimal("121871")),
        ("other", Decimal("609358")),
    ]
    assert sum(a for _, a in got) == before == Decimal("853100")


async def test_devices_equal_main_kwh_has_no_other_item(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        _, a = await add_device(c, h, "A")
        _, b2 = await add_device(c, h, "B")
        await load(c, a, local_midnight(V2892), 3000, table="device_estimate")  # 50 kWh
        await load(c, b2, local_midnight(V2892), 3000, table="device_estimate")  # 50 kWh
        b = await bill_for(c, bsession, h, V2892, 100)
        items = await _bill_items(bsession, b)
        got = [(i.device_id is None, i.share, i.amount) for i in items]
        before = b.amount_before_vat
    assert got == [(False, Decimal("0.500000"), Decimal("95050"))] * 2
    assert sum(g[2] for g in got) == before


async def test_device_overshoot_normalises_shares(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        _, a = await add_device(c, h, "Big")
        _, b2 = await add_device(c, h, "Small")
        await load(c, a, local_midnight(V2892), 1800, table="device_estimate")  # 30 kWh
        await load(c, b2, local_midnight(V2892), 300, table="device_estimate")  # 5 kWh
        b = await bill_for(c, bsession, h, V2892, 10)  # main sees only 10 kWh
        items = await _bill_items(bsession, b)
        got = [(i.label, i.kwh, i.share, i.amount) for i in items]
        before = b.amount_before_vat
    assert [g[0] for g in got] == ["Big", "Small"]  # no other item
    assert [g[1] for g in got] == [Decimal("30.000"), Decimal("5.000")]  # own estimates kept
    assert abs(sum(g[2] for g in got) - 1) <= Decimal("0.000001")
    assert all(g[3] >= 0 for g in got) and sum(g[3] for g in got) == before
    assert got[0][3] > got[1][3]


def test_allocate_remainder_goes_to_other():
    items = _allocate([Decimal(1), Decimal(1)], Decimal(3), Decimal(100))
    assert [a for _, _, a in items] == [Decimal(33), Decimal(33), Decimal(34)]


def test_allocate_without_other_remainder_goes_to_largest():
    items = _allocate([Decimal(1)] * 3, Decimal(3), Decimal(100))
    assert [a for _, _, a in items] == [Decimal(34), Decimal(33), Decimal(33)]


@pytest.mark.parametrize("devs", [[30, 5], [30, 30], [60, 45]])
def test_allocate_overshoot_is_normalised_and_never_negative(devs):
    kwh_total, before = Decimal(10 if devs[0] < 60 else 100), Decimal(19010)
    items = _allocate([Decimal(d) for d in devs], kwh_total, before)
    assert len(items) == len(devs)  # no other item
    assert all(a >= 0 for _, _, a in items) and sum(a for _, _, a in items) == before
    assert all(sh <= 1 for _, sh, _ in items)
    assert abs(sum(sh for _, sh, _ in items) - 1) <= Decimal("0.000001") * len(devs)
    assert [k for k, _, _ in items] == [Decimal(d) for d in devs]


def test_allocate_large_overshoot_fits_share_column():
    (k, share, amount), _ = _allocate([Decimal(500), Decimal(500)], Decimal(10), Decimal(1000))
    assert share == Decimal("0.500000") and amount == Decimal(500) and k == Decimal(500)


async def test_naive_now_rejected(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        with pytest.raises(ValueError):
            await compute_bill(bsession, h["id"], V2892, now=datetime(2026, 12, 1))


async def test_coverage_compared_unrounded(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        await load(c, h["main"], local_midnight(V2892), 41039)  # 41039/43200 = 0.949977
        await backfill(
            c, local_midnight(V2892) - timedelta(days=1), local_midnight(V2892) + timedelta(days=45)
        )
        b = await compute_bill(bsession, h["id"], V2892, now=local_midnight(date(2026, 12, 5)))
        got = (b.coverage, b.status)
    assert got == (Decimal("0.9500"), "partial")


async def test_period_window_includes_last_day_excludes_neighbours(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        for ts in (
            local_midnight(V2892) - timedelta(minutes=1),  # last minute of the previous cycle
            local_midnight(date(2026, 12, 1)) - timedelta(minutes=1),  # last minute of this one
            local_midnight(date(2026, 12, 1)),  # first minute of the next cycle
        ):
            await load(c, h["main"], ts, 1, watts=60000)  # exactly 1 kWh each
        b = await bill_for(c, bsession, h, V2892, None)
        kwh = b.kwh_total
    assert kwh == Decimal("1.000")


async def test_expected_minutes_derived_from_now_inside_period(bdb, bsession):
    c, _ = bdb
    async with home(c, bsession) as h:
        await load(c, h["main"], local_midnight(V2892), 10 * 1440)  # first 10 days only
        await backfill(
            c, local_midnight(V2892) - timedelta(days=1), local_midnight(V2892) + timedelta(days=45)
        )
        full = await compute_bill(bsession, h["id"], V2892, now=local_midnight(date(2026, 11, 11)))
        got_full = (full.coverage, full.status)
        half = await compute_bill(bsession, h["id"], V2892, now=local_midnight(date(2026, 11, 21)))
        got_half = (half.coverage, half.status)
    assert got_full == (Decimal("1.0000"), "open")
    assert got_half == (Decimal("0.5000"), "partial")


@asynccontextmanager
async def plan(c, code, versions):
    """A committed test plan; versions are (valid_from, valid_to) pairs (no tiers)."""
    await c.execute(
        text("INSERT INTO public.tb_tariff_plan (code, name) VALUES (:c, 'T')"), {"c": code}
    )
    ids = []
    for vf, vt in versions:
        ids.append(
            await c.scalar(
                text(
                    "INSERT INTO public.tb_tariff_version "
                    "(plan_code, valid_from, valid_to, vat_rate, "
                    "source_doc) VALUES (:c, :f, :t, 0.08, 'test') RETURNING id"
                ),
                {"c": code, "f": vf, "t": vt},
            )
        )
    try:
        yield ids
    finally:
        await c.execute(text("DELETE FROM public.tb_bill WHERE version_id = ANY(:i)"), {"i": ids})
        await c.execute(text("DELETE FROM public.tb_home WHERE tariff_plan_code = :c"), {"c": code})
        await c.execute(
            text("DELETE FROM public.tb_tariff_version WHERE plan_code = :c"), {"c": code}
        )
        await c.execute(text("DELETE FROM public.tb_tariff_plan WHERE code = :c"), {"c": code})


async def test_straddle_when_next_version_starts_on_period_end(bdb, bsession):
    c, _ = bdb
    versions = [(date(2026, 1, 1), date(2026, 1, 30)), (date(2026, 1, 31), None)]
    async with plan(c, "tst_edge", versions) as ids:
        async with home(c, bsession, plan="tst_edge") as h:
            b = await compute_bill(bsession, h["id"], date(2026, 1, 1))
            got = (b.period_end, b.version_id, b.tariff_straddle)
    assert got == (date(2026, 1, 31), ids[0], True)


async def test_overlapping_versions_later_valid_from_wins(bdb, bsession):
    c, _ = bdb
    versions = [(date(2026, 1, 1), None), (date(2026, 1, 15), None)]
    async with plan(c, "tst_overlap", versions) as ids:
        async with home(c, bsession, plan="tst_overlap") as h:
            b = await compute_bill(bsession, h["id"], date(2026, 2, 1))
            got = b.version_id
    assert got == ids[1]


# --- schema, seed, constraints ---


async def test_bill_unique_per_home_period(conn):
    hid = await conn.scalar(text("INSERT INTO public.tb_home (name) VALUES ('U') RETURNING id"))
    vid = await conn.scalar(text("SELECT id FROM public.tb_tariff_version LIMIT 1"))
    ins = text(
        "INSERT INTO public.tb_bill (home_id, period_start, period_end, version_id, kwh_total, "
        "amount_before_vat, vat_amount, amount_total, coverage, status) "
        "VALUES (:h, '2026-11-01', '2026-11-30', :v, 0, 0, 0, 0, 0, 'open')"
    )
    await conn.execute(ins, {"h": hid, "v": vid})
    with pytest.raises(IntegrityError):
        async with conn.begin_nested():
            await conn.execute(ins, {"h": hid, "v": vid})


async def test_home_tariff_plan_fk(conn):
    with pytest.raises(IntegrityError):
        await conn.execute(
            text("INSERT INTO public.tb_home (name, tariff_plan_code) VALUES ('X', 'nope')")
        )


async def test_seed_versions_do_not_overlap(conn):
    rows = (
        await conn.execute(
            text(
                "SELECT valid_from, valid_to, vat_rate, source_doc FROM public.tb_tariff_version "
                "WHERE plan_code = :p ORDER BY valid_from"
            ),
            {"p": PLAN},
        )
    ).all()
    assert [r.valid_from for r in rows] == [V1279, V2892]
    assert rows[0].valid_to + timedelta(days=1) == rows[1].valid_from
    assert rows[1].valid_to is None
    assert all(
        r.vat_rate == Decimal("0.0800") and "verify before 2027" in r.source_doc for r in rows
    )
    assert "1279/QD-BCT" in rows[0].source_doc and "2892" in rows[1].source_doc


async def test_seed_tiers(conn):
    async def tiers(valid_from):
        res = await conn.execute(
            text(
                "SELECT t.from_kwh, t.to_kwh, t.price_per_kwh FROM public.tb_tariff_tier t "
                "JOIN public.tb_tariff_version v ON v.id = t.version_id "
                "WHERE v.valid_from = :d ORDER BY t.tier_no"
            ),
            {"d": valid_from},
        )
        return [(int(a), None if b is None else int(b), int(p)) for a, b, p in res.all()]

    assert await tiers(V1279) == [
        (0, 50, 1984),
        (50, 100, 2050),
        (100, 200, 2380),
        (200, 300, 2998),
        (300, 400, 3350),
        (400, None, 3460),
    ]
    assert await tiers(V2892) == [
        (0, 100, 1901),
        (100, 200, 2289),
        (200, 400, 2894),
        (400, 700, 3456),
        (700, None, 3844),
    ]


def test_metadata_sorted_tables_resolves():
    names = {t.fullname for t in Base.metadata.sorted_tables}
    assert {
        "public.tb_tariff_plan",
        "public.tb_tariff_version",
        "public.tb_tariff_tier",
        "public.tb_bill",
        "public.tb_bill_item",
        "public.tb_home",
    } <= names


async def test_orm_round_trip(session):
    plan = TariffPlan(code="rt_plan", name="RT")
    ver = TariffVersion(
        plan_code="rt_plan",
        valid_from=date(2030, 1, 1),
        vat_rate=Decimal("0.1000"),
        source_doc="test",
    )
    h = Home(name="RT", tariff_plan_code="rt_plan")
    session.add_all([plan, ver, h])
    await session.flush()
    tier = TariffTier(
        version_id=ver.id, tier_no=1, from_kwh=Decimal("0"), price_per_kwh=Decimal("1000")
    )
    bill = Bill(
        home_id=h.id,
        version_id=ver.id,
        period_start=date(2030, 1, 1),
        period_end=date(2030, 1, 31),
        kwh_total=Decimal("1.5"),
        amount_before_vat=Decimal("1500"),
        vat_amount=Decimal("150"),
        amount_total=Decimal("1650"),
        coverage=Decimal("1"),
        status="open",
    )
    session.add_all([tier, bill])
    await session.flush()
    item = BillItem(
        bill_id=bill.id,
        label="other",
        kwh=Decimal("1.5"),
        share=Decimal("1"),
        amount=Decimal("1500"),
    )
    session.add(item)
    await session.flush()
    await session.refresh(bill)
    await session.refresh(ver)
    assert bill.tariff_straddle is False and bill.computed_at is not None
    assert ver.valid_to is None and tier.to_kwh is None and item.device_id is None
    got = (await session.execute(select(BillItem).where(BillItem.bill_id == bill.id))).scalars()
    assert [i.label for i in got] == ["other"]


async def test_billing_downgrade_upgrade(throwaway_dsn):
    billing_module = {
        "public.tb_tariff_plan",
        "public.tb_tariff_version",
        "public.tb_tariff_tier",
        "public.tb_bill",
        "public.tb_bill_item",
    }
    fk = text(
        "SELECT count(*) FROM information_schema.table_constraints "
        "WHERE table_schema = 'public' AND table_name = 'tb_home' "
        "AND constraint_type = 'FOREIGN KEY' "
        "AND constraint_name = 'fk_home_tariff_plan_code_tariff_plan'"
    )
    engine = create_async_engine(throwaway_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as c:
            before = await relations(c)
            assert billing_module <= before and await c.scalar(fk) == 1
            await c.execute(
                text("INSERT INTO public.tb_home (name, tariff_plan_code) VALUES ('D', :p)"),
                {"p": PLAN},
            )
        run_alembic(throwaway_dsn, "downgrade", "c8a4e1f7b295")
        async with engine.connect() as c:
            assert billing_module.isdisjoint(await relations(c)) and await c.scalar(fk) == 0
            assert (
                await c.scalar(
                    text("SELECT count(*) FROM public.tb_home WHERE tariff_plan_code = :p"),
                    {"p": PLAN},
                )
                == 1
            )
        run_alembic(throwaway_dsn, "upgrade", "head")
        async with engine.connect() as c:
            assert await relations(c) == before and await c.scalar(fk) == 1
            assert await c.scalar(text("SELECT count(*) FROM public.tb_tariff_version")) == 2
            assert await c.scalar(text("SELECT count(*) FROM public.tb_tariff_tier")) == 11
    finally:
        await engine.dispose()
