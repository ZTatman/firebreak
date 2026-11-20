from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet
from fastapi import Request
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.auth.crypto import fernet_from_encryption_key

if TYPE_CHECKING:
    from app.models.app_settings import AppSettings

_env_file = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    """Bootstrap settings loaded from environment variables.

    Only contains fields needed before the database is available.
    Forgejo config lives in the AppSettings DB table after setup.
    """

    app_name: str = "Firebreak"
    database_url: str = "postgresql+asyncpg://firebreak:firebreak@db:5432/firebreak_db"
    token_encryption_key: str = ""

    model_config = SettingsConfigDict(env_file=str(_env_file))


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()


@lru_cache
def get_fernet() -> Fernet:
    """
    Get a Fernet cipher from the TOKEN_ENCRYPTION_KEY env var.
    Return a cached Fernet cipher from the TOKEN_ENCRYPTION_KEY env var.
    """
    key = get_settings().token_encryption_key
    if not key:
        raise ValueError(
            "TOKEN_ENCRYPTION_KEY is not set. Add it to your .env file or deployment "
            "environment. Generate one with: uv run python -c "
            "'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    fernet = fernet_from_encryption_key(SecretStr(key))
    if fernet is None:
        raise ValueError(
            "TOKEN_ENCRYPTION_KEY is invalid. Generate a valid key with: uv run python -c "
            "'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return fernet


def get_app_settings(request: Request) -> AppSettings:
    """FastAPI dependency returning the AppSettings row from app state."""
    return request.app.state.app_settings
