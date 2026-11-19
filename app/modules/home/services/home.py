from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Home, HomeMember, Province
from ..schemas import HomeRead, HomeUpdate
from ..utils import HomeOwnerRequiredError, UnknownProvinceError

# Required columns: null in a patch means "not sent", never "clear".
REQUIRED = {"name", "billing_cycle_day"}


async def read_home(db: AsyncSession, member: HomeMember) -> HomeRead:
    home = await db.get(Home, member.home_id)
    fields = {k: getattr(home, k) for k in HomeRead.model_fields if k != "role"}
    return HomeRead.model_validate({**fields, "role": member.role})


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
    await db.refresh(home)  # answer what was stored (numeric(8,2) pads 72.5 to 72.50)
    return await read_home(db, member)


async def provinces(db: AsyncSession) -> list[Province]:
    return list(await db.scalars(select(Province).order_by(Province.name)))
