from app.common.base_repository import BaseRepository

from ..models import HomeMember


class HomeMemberRepository(BaseRepository[HomeMember]):
    model = HomeMember
