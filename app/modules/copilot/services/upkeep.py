from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ScopeToken


async def prune_scope_tokens(s: AsyncSession) -> None:
    await s.execute(delete(ScopeToken).where(ScopeToken.expires_at < func.now()))
