import calendar
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.home.api import Device, Home

from ..models import Bill, BillItem, TariffTier, TariffVersion

# Homes are pinned to Asia/Ho_Chi_Minh (a CHECK on public.tb_home.timezone), which has no DST.
ICT = timezone(timedelta(hours=7))
PARTIAL_BELOW = Decimal("0.95")
_ONE = Decimal(1)


def _round(value: Decimal, places: str = "1") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _add_month(d: date) -> date:
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _local_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=ICT).astimezone(UTC)


def _tier_split(tiers: list[TariffTier], kwh: Decimal) -> list[tuple[TariffTier, Decimal, Decimal]]:
    """(tier, kWh in it, amount in whole dong) per tier, in tier order.

    Cumulative tiers: a tier prices the kWh in (from_kwh, to_kwh]; the last is unbounded. Each
    tier's amount is rounded on its own, as on an EVN bill, so the lines add up to the total.
    """
    split = []
    for t in sorted(tiers, key=lambda t: t.tier_no):
        top = kwh if t.to_kwh is None else min(kwh, t.to_kwh)
        used = max(top - t.from_kwh, Decimal(0))
        split.append((t, used, _round(used * t.price_per_kwh)))
    return split


def _tier_amount(tiers: list[TariffTier], kwh: Decimal) -> Decimal:
    return sum((amount for _, _, amount in _tier_split(tiers, kwh)), Decimal(0))


@dataclass
class _Segment:
    """The days of a cycle priced by one tariff version."""

    version: TariffVersion
    tiers: list[TariffTier]
    start: date
    days: int


@dataclass
class _ScaledTier:
    tier_no: int
    from_kwh: Decimal
    to_kwh: Decimal | None
    price_per_kwh: Decimal


def _scaled(tiers: list[TariffTier], days: int, total_days: int) -> list[_ScaledTier]:
    """Each tier's width times days / total_days, rounded to whole kWh, stacked from 0."""
    out, lo = [], Decimal(0)
    for t in sorted(tiers, key=lambda t: t.tier_no):
        hi = None if t.to_kwh is None else lo + _round((t.to_kwh - t.from_kwh) * days / total_days)
        out.append(_ScaledTier(t.tier_no, lo, hi, t.price_per_kwh))
        lo = hi  # None only after the last, unbounded tier
    return out


def _parts(segments: list[_Segment], kwh: Decimal) -> list[tuple[_Segment, list, Decimal]]:
    """(segment, its tiers, its kWh) per segment.

    One segment prices all the kWh with its own tiers. When the tariff changes inside the cycle,
    EVN splits both by days: a segment of N of the cycle's T days takes kWh * N / T (the last
    takes the rest) and tiers N / T as wide (Bo Cong Thuong, Tap chi Cong Thuong 2010-03-13).
    """
    if len(segments) == 1:
        return [(segments[0], segments[0].tiers, kwh)]
    total = sum(s.days for s in segments)
    out, rest = [], kwh
    for i, s in enumerate(segments):
        part = rest if i == len(segments) - 1 else _round(kwh * s.days / total, "0.001")
        rest -= part
        out.append((s, _scaled(s.tiers, s.days, total), part))
    return out


def _cycle_amount(segments: list[_Segment], kwh: Decimal) -> Decimal:
    """The cycle's amount before VAT for kwh, across its tariff segments."""
    return sum((_tier_amount(t, k) for _, t, k in _parts(segments, kwh)), Decimal(0))


async def _segments(session, plan_code: str, start: date, end: date) -> list[_Segment]:
    """The cycle's days grouped by the tariff version valid on each (the later valid_from wins
    where versions overlap). A day without a valid version keeps the one before it."""
    versions = list(
        (
            await session.execute(
                select(TariffVersion)
                .where(
                    TariffVersion.plan_code == plan_code,
                    TariffVersion.valid_from <= end,
                    func.coalesce(TariffVersion.valid_to, date.max) >= start,
                )
                .order_by(TariffVersion.valid_from)
            )
        ).scalars()
    )
    segments: list[_Segment] = []
    day = start
    while day <= end:
        valid = [v for v in versions if v.valid_from <= day and (v.valid_to or date.max) >= day]
        if valid and (not segments or segments[-1].version.id != valid[-1].id):
            segments.append(_Segment(valid[-1], [], day, 1))
        elif segments:
            segments[-1].days += 1
        else:
            raise LookupError(f"no tariff version of {plan_code} valid on {start}")
        day += timedelta(days=1)
    for s in segments:
        s.tiers = list(
            (
                await session.execute(
                    select(TariffTier).where(TariffTier.version_id == s.version.id)
                )
            ).scalars()
        )
    return segments


async def _kwh_by_series(session, view, series_ids, lo, hi) -> dict[uuid.UUID, Decimal]:
    if not series_ids:
        return {}
    rows = await session.execute(
        text(
            f"SELECT series_id, sum(energy_wh)::numeric AS wh FROM public.{view} "
            "WHERE series_id = ANY(:ids) AND bucket >= :lo AND bucket < :hi GROUP BY series_id"
        ),
        {"ids": list(series_ids), "lo": lo, "hi": hi},
    )
    return {r.series_id: _round(Decimal(r.wh) / 1000, "0.001") for r in rows}


def _split_amount(shares: list[Decimal], before_vat: Decimal, remainder_to: int) -> list[Decimal]:
    """Amount per item in whole dong; the rounding remainder goes to item `remainder_to`."""
    amounts = [_round(s * before_vat) for s in shares]
    amounts[remainder_to] += before_vat - sum(amounts)
    return amounts


def _allocate(
    dev_kwh: list[Decimal], kwh_total: Decimal, before_vat: Decimal
) -> list[tuple[Decimal, Decimal, Decimal]]:
    """(kwh, share, amount) per item: the devices (largest first, as given), then `other`.

    Shares are relative to the main-meter kWh. `other` takes the kWh the devices do not explain
    and the rounding remainder of the amounts. When the devices claim at least as much as the
    meter measured (their estimates are not quality-filtered, the meter series is), there is no
    `other` item; if they claim more, the shares are normalised by the device sum so they add up
    to exactly 1 (the stored kwh stays each device's own estimate). Without an `other` item the
    rounding remainder goes to the largest item. Amounts sum exactly to before_vat.
    """
    dev_sum = sum(dev_kwh, Decimal(0))
    denom = max(dev_sum, kwh_total)
    kwhs = list(dev_kwh)
    if dev_sum < kwh_total:
        kwhs.append(kwh_total - dev_sum)
    exact = [k / denom for k in kwhs]
    has_other = dev_sum < kwh_total
    amounts = _split_amount(exact, before_vat, len(kwhs) - 1 if has_other else 0)
    return [(k, _round(e, "0.000001"), a) for k, e, a in zip(kwhs, exact, amounts, strict=True)]


async def _price(
    session: AsyncSession, home_id: uuid.UUID, period_start: date, now: datetime | None
):
    """Price one billing cycle without writing: (bill columns, tariff segments, series rows).

    A tariff change inside the cycle splits it by days as EVN does (see _parts); the bill keeps
    the version valid on period_start and sets tariff_straddle.
    """
    if now is not None and now.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")
    home = await session.get(Home, home_id)
    if home is None:
        raise LookupError(f"home {home_id} not found")
    cycle_day = home.billing_cycle_day or 1
    if period_start.day != cycle_day:
        raise ValueError(f"period_start must fall on billing cycle day {cycle_day}")
    if home.tariff_plan_code is None:
        raise LookupError(f"home {home_id} has no tariff plan")
    period_end = _add_month(period_start) - timedelta(days=1)
    segments = await _segments(session, home.tariff_plan_code, period_start, period_end)

    lo = _local_midnight(period_start)
    hi = _local_midnight(period_end + timedelta(days=1))
    now = now or datetime.now(UTC)

    series = (
        await session.execute(
            text(
                "SELECT series_id, kind, device_id FROM public.tb_series "
                "WHERE home_id = :h AND metric = 'power_w' AND kind IN ('main', 'device')"
            ),
            {"h": home_id},
        )
    ).all()
    main_ids = [s.series_id for s in series if s.kind == "main"]
    kwh_total = sum(
        (await _kwh_by_series(session, "reading_1d", main_ids, lo, hi)).values(), Decimal(0)
    )
    covered = 0
    if main_ids:
        covered = await session.scalar(
            text(
                "SELECT coalesce(sum(covered_minutes), 0) FROM public.reading_1d "
                "WHERE series_id = ANY(:ids) AND bucket >= :lo AND bucket < :hi"
            ),
            {"ids": main_ids, "lo": lo, "hi": hi},
        )
    expected = (min(now, hi) - lo).total_seconds() / 60
    ratio = (
        min(_ONE, Decimal(int(covered)) / Decimal(round(expected))) if expected >= 1 else Decimal(0)
    )
    coverage = _round(ratio, "0.0001")  # stored rounded; the status uses the exact ratio
    if ratio < PARTIAL_BELOW:
        status = "partial"
    elif period_end < now.astimezone(ICT).date():
        status = "closed"
    else:
        status = "open"

    parts = [(s, _tier_amount(t, k)) for s, t, k in _parts(segments, kwh_total)]
    before_vat = sum((a for _, a in parts), Decimal(0))
    vat = _round(sum((a * s.version.vat_rate for s, a in parts), Decimal(0)))

    values = dict(
        period_end=period_end,
        version_id=segments[0].version.id,
        kwh_total=kwh_total,
        amount_before_vat=before_vat,
        vat_amount=vat,
        amount_total=before_vat + vat,
        coverage=coverage,
        tariff_straddle=len(segments) > 1,
        status=status,
    )
    return values, segments, series


async def compute_bill(
    session: AsyncSession, home_id: uuid.UUID, period_start: date, now: datetime | None = None
) -> Bill:
    """Compute (or recompute) and store the bill of one billing cycle; idempotent on
    (home, period_start). The caller commits.
    """
    values, _, series = await _price(session, home_id, period_start, now)
    kwh_total, before_vat = values["kwh_total"], values["amount_before_vat"]
    lo = _local_midnight(period_start)
    hi = _local_midnight(values["period_end"] + timedelta(days=1))
    bill_id = await session.scalar(
        insert(Bill)
        .values(home_id=home_id, period_start=period_start, **values)
        .on_conflict_do_update(
            index_elements=["home_id", "period_start"], set_={**values, "computed_at": func.now()}
        )
        .returning(Bill.id)
    )
    await session.execute(delete(BillItem).where(BillItem.bill_id == bill_id))

    if kwh_total > 0:
        dev_series = {s.series_id: s.device_id for s in series if s.kind == "device"}
        dev_kwh = await _kwh_by_series(session, "device_estimate_1d", list(dev_series), lo, hi)
        names = (
            dict(
                (
                    await session.execute(
                        select(Device.id, Device.name).where(
                            Device.id.in_(set(dev_series.values()))
                        )
                    )
                ).all()
            )
            if dev_series
            else {}
        )
        devs = sorted(
            ((dev_series[sid], names[dev_series[sid]], kwh) for sid, kwh in dev_kwh.items()),
            key=lambda e: -e[2],
        )
        allocated = _allocate([e[2] for e in devs], kwh_total, before_vat)
        labels = [(d, label) for d, label, _ in devs] + [(None, "other")]
        session.add_all(
            BillItem(bill_id=bill_id, device_id=d, label=label, kwh=k, share=sh, amount=a)
            for (d, label), (k, sh, a) in zip(labels, allocated, strict=False)
        )
    await session.flush()
    return await session.get(Bill, bill_id, populate_existing=True)


@dataclass
class TierUse:
    tier_no: int
    from_kwh: Decimal
    to_kwh: Decimal | None
    price_per_kwh: Decimal
    kwh: Decimal
    amount: Decimal


@dataclass
class CurrentBill:
    period_start: date
    period_end: date
    status: str
    coverage: Decimal
    tariff_straddle: bool
    vat_rate: Decimal
    kwh: Decimal
    amount_before_vat: Decimal
    vat_amount: Decimal
    amount_total: Decimal
    tier_no: int
    tiers: list[TierUse]
    today_kwh: Decimal
    today_amount: Decimal


def _cycle_start(today: date, cycle_day: int) -> date:
    if today.day >= cycle_day:
        return today.replace(day=cycle_day)
    return (today.replace(day=1) - timedelta(days=1)).replace(day=cycle_day)  # day <= 28


async def current_bill(
    session: AsyncSession, home_id: uuid.UUID, now: datetime | None = None
) -> CurrentBill:
    """The running billing cycle so far: its bill, the kWh and amount in each tier, the tier the
    next kWh falls in, and what today cost (VAT included). Reads only: a GET does not write; the
    stored bill is compute_bill's.

    Today is priced at the margin: T(kWh by now) - T(kWh by local midnight), T being the cycle's
    tiered amount, so the days of a cycle add up to its bill. In a cycle with a tariff change the
    totals follow EVN's split by days, while the tier rows place the kWh on today's tariff (where
    the next kWh lands); their amounts then do not add up to the total (tariff_straddle says so).
    """
    now = now or datetime.now(UTC)
    home = await session.get(Home, home_id)
    if home is None:
        raise LookupError(f"home {home_id} not found")
    today = now.astimezone(ICT).date()
    start = _cycle_start(today, home.billing_cycle_day or 1)
    bill, segments, series = await _price(session, home_id, start, now)
    # The tariff in force today: its tiers place the kWh and price the next one.
    today_segment = [s for s in segments if s.start <= today][-1]
    tiers, vat_rate = today_segment.tiers, today_segment.version.vat_rate
    main_ids = [s.series_id for s in series if s.kind == "main"]
    lo = _local_midnight(today)
    today_kwh = sum(
        (
            await _kwh_by_series(session, "reading_1d", main_ids, lo, lo + timedelta(days=1))
        ).values(),
        Decimal(0),
    )
    kwh = bill["kwh_total"]
    marginal = _cycle_amount(segments, kwh) - _cycle_amount(
        segments, max(kwh - today_kwh, Decimal(0))
    )
    split = _tier_split(tiers, kwh)
    return CurrentBill(
        period_start=start,
        period_end=bill["period_end"],
        status=bill["status"],
        coverage=bill["coverage"],
        tariff_straddle=bill["tariff_straddle"],
        vat_rate=vat_rate,
        kwh=kwh,
        amount_before_vat=bill["amount_before_vat"],
        vat_amount=bill["vat_amount"],
        amount_total=bill["amount_total"],
        # The tier the next kWh is priced in: at exactly 100 kWh that is tier 2, not tier 1.
        tier_no=next(t.tier_no for t, _, _ in split if t.to_kwh is None or kwh < t.to_kwh),
        tiers=[
            TierUse(t.tier_no, t.from_kwh, t.to_kwh, t.price_per_kwh, used, amount)
            for t, used, amount in split
        ],
        today_kwh=today_kwh,
        today_amount=_round(marginal * (_ONE + vat_rate)),
    )
