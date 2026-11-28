import uuid
from datetime import UTC, date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.demo import demo_home_entries
from app.config import settings
from app.modules.auth.api import User

from ..models import Home, HomeMember, Province
from ..schemas import HomeRead, HomeUpdate, KeptLevel, PrivacyOverview
from ..utils import DemoHomeReadOnlyError, HomeOwnerRequiredError, UnknownProvinceError

ICT = timezone(timedelta(hours=7))
# Required columns: null in a patch means "not sent", never "clear".
REQUIRED = {"name", "billing_cycle_day"}


async def read_home(db: AsyncSession, member: HomeMember) -> HomeRead:
    home = await db.get(Home, member.home_id)
    computed = {"role", "detail", "ai_detail_effective"}
    fields = {k: getattr(home, k) for k in HomeRead.model_fields if k not in computed}
    fields |= {
        "role": member.role,
        "detail": member.detail,
        "ai_detail_effective": ai_detail(home, member),
    }
    return HomeRead.model_validate(fields)


def ai_detail(home: Home, member: HomeMember | None = None) -> str:
    """The level Wappi uses: the home's choice, else the system default; never finer than what the
    asking member may see."""
    if member is not None and member.detail == "daily":
        return "daily"
    return home.ai_detail or settings.copilot_ai_detail_default


async def update_home(db: AsyncSession, member: HomeMember, patch: HomeUpdate) -> HomeRead:
    if member.role != "owner":
        raise HomeOwnerRequiredError
    data = {
        k: v
        for k, v in patch.model_dump(exclude_unset=True).items()
        if v is not None or k not in REQUIRED
    }
    code = data.get("province_code")
    if code is not None and await db.get(Province, code) is None:
        raise UnknownProvinceError
    home = await db.get(Home, member.home_id)
    for name, value in data.items():
        setattr(home, name, value)
    await db.commit()
    if "billing_cycle_day" in data:
        # Lazy: billing reads homes through home.api, so a top-level import would be a cycle.
        from app.modules.billing.api import forget_device_forecasts

        forget_device_forecasts(home.id)
    await db.refresh(home)  # answer what was stored (numeric(8,2) pads 72.5 to 72.50)
    return await read_home(db, member)


async def provinces(db: AsyncSession) -> list[Province]:
    return list(await db.scalars(select(Province).order_by(Province.name)))


async def _is_demo_home(db: AsyncSession, home_id: uuid.UUID) -> bool:
    owners = [h["owner"]["email"].lower() for h in demo_home_entries()]
    found = await db.scalar(
        select(HomeMember.home_id)
        .join(User, User.id == HomeMember.user_id)
        .where(HomeMember.home_id == home_id, User.email.in_(owners))
    )
    return found is not None


async def privacy_overview(db: AsyncSession, member: HomeMember) -> PrivacyOverview:
    from app.modules.energy.api import kept_history  # lazy: see erase_history

    home = await db.get(Home, member.home_id)
    erased = home.history_erased_before
    return PrivacyOverview(
        levels=[
            KeptLevel(level=level, keep_days=days, oldest=oldest)
            for level, days, oldest in await kept_history(db, home.id)
        ],
        erased_before=erased.astimezone(ICT).date() if erased else None,
        can_erase=member.role == "owner" and not await _is_demo_home(db, home.id),
    )


async def erase_history(db: AsyncSession, member: HomeMember, before: date | None) -> None:
    """Owner only: the home's measurements before `before` (all when None), and what was derived
    from them. Bills follow the daily totals: a cycle wholly older goes, a cut one turns partial."""
    if member.role != "owner":
        raise HomeOwnerRequiredError
    if await _is_demo_home(db, member.home_id):
        raise DemoHomeReadOnlyError
    # Lazy: energy and billing read homes through home.api, so a top-level import is a cycle.
    from app.modules.billing.api import forget_device_forecasts, refresh_bills
    from app.modules.energy.api import erase_home_history

    now = datetime.now(UTC)
    cut = now if before is None else min(now, datetime.combine(before, time(), ICT))
    home = await db.get(Home, member.home_id)
    await erase_home_history(db, member.home_id, cut)
    home.history_erased_before = max(cut, home.history_erased_before or cut)
    await db.flush()
    await refresh_bills(db, member.home_id, now)
    await db.commit()
    forget_device_forecasts(member.home_id)
