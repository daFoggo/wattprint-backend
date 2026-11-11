import calendar
import uuid
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


def _tier_amount(tiers: list[TariffTier], kwh: Decimal) -> Decimal:
    """Cumulative tiers: a tier prices the kWh in (from_kwh, to_kwh]; the last is unbounded."""
    total = Decimal(0)
    for t in sorted(tiers, key=lambda t: t.tier_no):
        top = kwh if t.to_kwh is None else min(kwh, t.to_kwh)
        total += max(top - t.from_kwh, Decimal(0)) * t.price_per_kwh
    return total


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


async def compute_bill(
    session: AsyncSession, home_id: uuid.UUID, period_start: date, now: datetime | None = None
) -> Bill:
    """Compute (or recompute) the bill of one billing cycle; idempotent on (home, period_start).

    The bill is priced with the tariff version valid on period_start only (no proration); a
    version change inside the period just sets tariff_straddle. The caller commits.
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

    version = (
        await session.execute(
            select(TariffVersion)
            .where(
                TariffVersion.plan_code == home.tariff_plan_code,
                TariffVersion.valid_from <= period_start,
                func.coalesce(TariffVersion.valid_to, date.max) >= period_start,
            )
            .order_by(TariffVersion.valid_from.desc())
            .limit(1)  # overlapping versions: the later valid_from wins
        )
    ).scalar_one_or_none()
    if version is None:
        raise LookupError(f"no tariff version of {home.tariff_plan_code} valid on {period_start}")
    straddle = (
        await session.scalar(
            select(func.count())
            .select_from(TariffVersion)
            .where(
                TariffVersion.plan_code == version.plan_code,
                TariffVersion.valid_from > period_start,
                TariffVersion.valid_from <= period_end,
            )
        )
    ) > 0
    tiers = list(
        (
            await session.execute(select(TariffTier).where(TariffTier.version_id == version.id))
        ).scalars()
    )

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

    before_vat = _round(_tier_amount(tiers, kwh_total))
    vat = _round(before_vat * version.vat_rate)

    values = dict(
        period_end=period_end,
        version_id=version.id,
        kwh_total=kwh_total,
        amount_before_vat=before_vat,
        vat_amount=vat,
        amount_total=before_vat + vat,
        coverage=coverage,
        tariff_straddle=straddle,
        status=status,
    )
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
