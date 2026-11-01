import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.mark.parametrize("key", ["", "short"])
def test_short_jwt_secret_rejected(key):
    with pytest.raises(ValidationError):
        Settings(jwt_secret_key=key)


def test_32_char_jwt_secret_accepted():
    assert Settings(jwt_secret_key="k" * 32).jwt_secret_key == "k" * 32


def test_missing_jwt_secret_rejected(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
