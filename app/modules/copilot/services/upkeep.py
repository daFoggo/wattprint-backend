from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import SavingsMeasure, ScopeToken, Suggestion, SuggestionFeedback

TRIAL = timedelta(days=14)


async def prune_scope_tokens(s: AsyncSession) -> None:
    await s.execute(delete(ScopeToken).where(ScopeToken.expires_at < func.now()))


async def _kwh(s: AsyncSession, home_id, lo: datetime, hi: datetime) -> float:
    wh = await s.scalar(
        text(
            "SELECT sum(r.energy_wh) FROM public.reading_1h r JOIN public.tb_series s "
            "USING (series_id) WHERE s.home_id = :h AND s.kind = 'main' AND s.metric = 'power_w' "
            "AND r.bucket >= :lo AND r.bucket < :hi"
        ),
        {"h": home_id, "lo": lo, "hi": hi},
    )
    return float(wh or 0) / 1000


async def measure_plans(s: AsyncSession, now: datetime | None = None) -> None:
    """M&V of each plan tried for 14 days: the main meter's kWh of the 14 days after it was
    accepted against the 14 days before (no weather adjustment yet)."""
    now = now or datetime.now(UTC)
    due = (
        await s.execute(
            select(Suggestion.id, Suggestion.home_id, func.min(SuggestionFeedback.at))
            .join(SuggestionFeedback, SuggestionFeedback.suggestion_id == Suggestion.id)
            .outerjoin(SavingsMeasure, SavingsMeasure.suggestion_id == Suggestion.id)
            .where(
                Suggestion.status == "accepted",
                SuggestionFeedback.action == "accept",
                SavingsMeasure.suggestion_id.is_(None),
            )
            .group_by(Suggestion.id, Suggestion.home_id)
            .having(func.min(SuggestionFeedback.at) <= now - TRIAL)
        )
    ).all()
    for plan_id, home_id, accepted in due:
        await s.execute(
            insert(SavingsMeasure)
            .values(
                suggestion_id=plan_id,
                baseline_kwh=round(await _kwh(s, home_id, accepted - TRIAL, accepted), 3),
                actual_kwh=round(await _kwh(s, home_id, accepted, accepted + TRIAL), 3),
                measured_at=now,
            )
            .on_conflict_do_nothing()
        )
