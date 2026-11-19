import asyncio
import logging
import smtplib
import uuid
from datetime import UTC, datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal
from app.modules.billing.api import current_bill

from ..models import Alert, NotificationLog

log = logging.getLogger("insight.mail")
ICT = timezone(timedelta(hours=7))
FRESH = timedelta(days=1)  # an alert older than this when mail can go out is not mailed late
WEEKLY_HOUR = 8  # Monday 08:00 local


def _send(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


async def send(to: str, subject: str, body: str) -> None:
    await asyncio.to_thread(_send, to, subject, body)


def _vnd(x: float) -> str:
    return f"{round(x):,}".replace(",", ".") + " đ"


def _num(x: float, digits: int = 1) -> str:
    return f"{x:,.{digits}f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def alert_text(a: Alert, device: str | None) -> tuple[str, str]:
    """Subject and first lines of an alert's mail (the dashboard says the same in vi/en)."""
    p = a.payload
    match a.kind:
        case "longer_than_usual":
            return (
                f"{device} chạy lâu hơn thường lệ",
                f"{p['days']} ngày qua mỗi lần chạy khoảng {p['recent_min']} phút, thường lệ "
                f"{p['usual_min']} phút. Kiểm tra gioăng cửa và dàn nóng.",
            )
        case "unexplained_load":
            return (
                "Có tải lạ đang chạy",
                f"{p['minutes']} phút qua phần chưa nhận ra thiết bị dùng khoảng {p['watts']} W, "
                f"thường không quá {p['usual_w']} W. Có thể có thiết bị bị quên bật.",
            )
        case "standby_high":
            return (
                "Điện nền ban đêm tăng",
                f"{p['nights']} đêm qua nhà dùng khoảng {p['recent_w']} W lúc không ai dùng điện, "
                f"thường {p['usual_w']} W.",
            )
        case _:  # tier_near
            when = "đã sang" if p["days"] == 0 else f"khoảng {p['days']} ngày nữa sẽ sang"
            return (
                f"Kỳ này {when} bậc {p['tier_no']}",
                f"Từ {_num(p['from_kwh'], 0)} kWh mỗi kWh giá {_vnd(p['price_per_kwh'])} "
                "(chưa VAT).",
            )


async def _members(s: AsyncSession, home_id: uuid.UUID):
    return (
        await s.execute(
            text(
                "SELECT u.id, u.email, coalesce(p.notify_anomaly, true) AS anomaly, "
                "coalesce(p.notify_tier, true) AS tier "
                "FROM public.tb_home_member m JOIN public.tb_users u ON u.id = m.user_id "
                "LEFT JOIN public.tb_user_preference p ON p.user_id = u.id "
                "WHERE m.home_id = :h AND u.is_active"
            ),
            {"h": home_id},
        )
    ).all()


async def _claim(s: AsyncSession, user_id: uuid.UUID, kind: str, ref: str) -> bool:
    """Log the mail before sending it: False when it was already sent (a re-run, another worker)."""
    return (
        await s.scalar(
            insert(NotificationLog)
            .values(user_id=user_id, kind=kind, ref=ref)
            .on_conflict_do_nothing()
            .returning(NotificationLog.id)
        )
    ) is not None


async def mail_alerts(now: datetime) -> None:
    """Mail each new alert to the members who want it: anomalies (warning and up) and tiers."""
    async with SessionLocal() as s:
        ids = list(
            await s.scalars(
                select(Alert.id).where(
                    Alert.notified_at.is_(None),
                    Alert.status == "open",
                    (Alert.kind == "tier_near") | Alert.severity.in_(("warning", "critical")),
                )
            )
        )
    for alert_id in ids:
        try:
            async with SessionLocal() as s, s.begin():
                a = await s.get(Alert, alert_id, with_for_update={"skip_locked": True})
                if a is None or a.notified_at is not None:
                    continue
                missed = False
                if now - a.ts <= FRESH:
                    device = a.device_id and await s.scalar(
                        text("SELECT name FROM public.tb_device WHERE id = :d"), {"d": a.device_id}
                    )
                    subject, body = alert_text(a, device or "Một thiết bị")
                    body += f"\n\nXem trên WattPrint: {settings.dashboard_url}/dashboard\n"
                    # Per day, not per alert: a cause that comes and goes is mailed once a day.
                    ref = f"{a.home_id}:{a.dedup_key}:{now.astimezone(ICT).date()}"
                    for m in await _members(s, a.home_id):
                        wants = m.tier if a.kind == "tier_near" else m.anomaly
                        try:
                            # Each member on their own: a refused address rolls back only its log
                            # row, so the others are not mailed again on the next run.
                            async with s.begin_nested():
                                if wants and await _claim(s, m.id, "alert", ref):
                                    await send(m.email, f"WattPrint: {subject}", body)
                        except Exception:
                            log.exception("alert %s not mailed to %s", alert_id, m.id)
                            missed = True
                if not missed:  # else the next run retries the members not mailed yet
                    await s.execute(
                        update(Alert).where(Alert.id == a.id).values(notified_at=func.now())
                    )
        except Exception:
            log.exception("alert %s not mailed", alert_id)


async def _week_kwh(s: AsyncSession, home_id: uuid.UUID, lo: datetime, hi: datetime) -> float:
    wh = await s.scalar(
        text(
            "SELECT sum(r.energy_wh) FROM public.reading_1d r JOIN public.tb_series s "
            "USING (series_id) WHERE s.home_id = :h AND s.kind = 'main' AND s.metric = 'power_w' "
            "AND r.bucket >= :lo AND r.bucket < :hi"
        ),
        {"h": home_id, "lo": lo, "hi": hi},
    )
    return float(wh or 0) / 1000


async def weekly_summary(s: AsyncSession, home_id: uuid.UUID, now: datetime) -> str:
    local = now.astimezone(ICT)
    monday = local.date() - timedelta(days=local.weekday())
    week = datetime(monday.year, monday.month, monday.day, tzinfo=ICT).astimezone(UTC)
    last = await _week_kwh(s, home_id, week - timedelta(days=7), week)
    before = await _week_kwh(s, home_id, week - timedelta(days=14), week - timedelta(days=7))
    lines = [f"Tuần qua nhà dùng {_num(last)} kWh"]
    if before:
        lines[0] += (
            f", {'nhiều' if last >= before else 'ít'} hơn tuần trước {abs(last / before - 1):.0%}"
        )
    lines[0] += "."
    try:
        bill = await current_bill(s, home_id, now)
        lines.append(
            f"Kỳ này đến nay: {_num(float(bill.kwh), 0)} kWh, "
            f"tạm tính {_vnd(float(bill.amount_total))}."
        )
    except LookupError:
        pass
    n_open = await s.scalar(
        select(func.count()).where(Alert.home_id == home_id, Alert.status == "open")
    )
    if n_open:
        lines.append(f"{n_open} cảnh báo đang mở.")
    return "\n".join(lines)


async def mail_weekly(now: datetime) -> None:
    """Monday from 08:00 local: last week's summary to every member who asked for it, once."""
    local = now.astimezone(ICT)
    if local.weekday() != 0 or local.hour < WEEKLY_HOUR:
        return
    year, week, _ = local.isocalendar()
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT m.home_id, h.name, u.id, u.email FROM public.tb_user_preference p "
                    "JOIN public.tb_users u ON u.id = p.user_id AND u.is_active "
                    "JOIN public.tb_home_member m ON m.user_id = u.id "
                    "JOIN public.tb_home h ON h.id = m.home_id WHERE p.weekly_summary"
                )
            )
        ).all()
    for home_id, home, user_id, email in rows:
        try:
            async with SessionLocal() as s, s.begin():
                if await _claim(s, user_id, "weekly", f"{year}-W{week:02d}:{home_id}"):
                    body = await weekly_summary(s, home_id, now)
                    body += f"\n\nXem trên WattPrint: {settings.dashboard_url}/dashboard\n"
                    await send(email, f"WattPrint: tóm tắt tuần của {home}", body)
        except Exception:
            log.exception("weekly summary for %s not mailed", user_id)
