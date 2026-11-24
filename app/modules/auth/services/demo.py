import tomllib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.home.api import HomeMember, HomeRead, read_home

from ..models import User
from ..schemas.schema_demo import DemoDevice, DemoHome
from ..utils.exceptions import DemoHomeNotFoundError, DemoNotForMembersError


async def _homes(db: AsyncSession) -> list[tuple[DemoHome, str]]:
    """(home, owner email) for each toml home whose owner is a member of a home."""
    homes = tomllib.loads(Path(settings.demo_homes_file).read_text())["home"]
    emails = [h["owner"]["email"].lower() for h in homes]
    seeded = set(
        await db.scalars(
            select(User.email)
            .join(HomeMember, HomeMember.user_id == User.id)
            .where(User.email.in_(emails))
        )
    )
    return [
        (
            DemoHome(
                key=str(h.get("key", h["house"])),
                house=h["house"],
                name=h.get("name", f"REFIT House {h['house']}"),
                devices=[
                    DemoDevice(label=label, name=name)
                    for label, name in h["devices"].items()
                    if label != "Other"
                ],
            ),
            email,
        )
        for h, email in zip(homes, emails, strict=True)
        if email in seeded
    ]


async def demo_homes(db: AsyncSession) -> list[DemoHome]:
    return [home for home, _ in await _homes(db)]


async def view_demo_home(db: AsyncSession, user: User, key: str) -> HomeRead:
    """Makes the account a read-only viewer of that demo home (moving its one viewer row there)."""
    email = next((e for home, e in await _homes(db) if home.key == key), None)
    if email is None:
        raise DemoHomeNotFoundError()
    home_id = await db.scalar(
        select(HomeMember.home_id)
        .join(User, User.id == HomeMember.user_id)
        .where(User.email == email, HomeMember.role == "owner")
    )
    if home_id is None:
        raise DemoHomeNotFoundError()
    # One statement, so two tabs cannot both insert: a viewer row moves, a member row stays.
    moved = await db.execute(
        insert(HomeMember)
        .values(home_id=home_id, user_id=user.id, role="viewer")
        .on_conflict_do_update(
            index_elements=[HomeMember.user_id],
            set_={"home_id": home_id},
            where=HomeMember.role == "viewer",
        )
        .returning(HomeMember.home_id)
    )
    if moved.scalar() is None:
        raise DemoNotForMembersError()
    await db.commit()
    member = HomeMember(home_id=home_id, user_id=user.id, role="viewer")
    return await read_home(db, member)
