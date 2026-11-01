import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

PASSWORD = "correct-horse-battery"


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def email() -> str:
    return f"user-{uuid.uuid4().hex[:8]}@example.com"
