import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.outbound import CONSENT_VERSION, PURPOSES

from ..schemas.schema_consent import Consent


async def consents(db: AsyncSession, user_id: uuid.UUID) -> list[Consent]:
    """The latest choice per purpose; none yet means off."""
    rows = await db.execute(
        text(
            "SELECT DISTINCT ON (purpose) purpose, granted, version, created_at "
            "FROM public.tb_consent WHERE user_id = :u ORDER BY purpose, created_at DESC, id DESC"
        ),
        {"u": user_id},
    )
    last = {r.purpose: r for r in rows}
    out = []
    for p in PURPOSES:
        r = last.get(p)
        out.append(
            Consent(
                purpose=p,
                granted=bool(r and r.granted and r.version == CONSENT_VERSION),
                version=r.version if r else None,
                at=r.created_at if r else None,
                current_version=CONSENT_VERSION,
            )
        )
    return out


async def set_consent(db: AsyncSession, user_id: uuid.UUID, purpose: str, granted: bool) -> Consent:
    """A new row every time (the history stays): who, what for, yes or no, on which wording."""
    await db.execute(
        text(
            "INSERT INTO public.tb_consent (user_id, purpose, granted, version) "
            "VALUES (:u, :p, :g, :v)"
        ),
        {"u": user_id, "p": purpose, "g": granted, "v": CONSENT_VERSION},
    )
    await db.commit()
    return next(c for c in await consents(db, user_id) if c.purpose == purpose)
