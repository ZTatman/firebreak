from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.crypto import encrypt_optional
from app.models.app_settings import AppSettings
from app.models.user import LinkedIdentity, User
from app.settings import get_fernet


async def find_or_create_user(
    db: AsyncSession,
    app_settings: AppSettings,
    *,
    provider: str,
    provider_user_id: str,
    provider_username: str,
    email: str | None,
    access_token_raw: str | None,
    access_token_expires_at: datetime | None,
    refresh_token_raw: str | None,
) -> User:
    """Find or create a user based on the given provider and identity details."""

    fernet = get_fernet()

    result = await db.execute(
        select(LinkedIdentity)
        .options(selectinload(LinkedIdentity.user))
        .where(
            LinkedIdentity.provider == provider,
            LinkedIdentity.provider_user_id == provider_user_id,
        )
    )
    identity = result.scalar_one_or_none()

    if identity:
        identity.provider_username = provider_username
        if access_token_raw is not None:
            identity.access_token_encrypted = encrypt_optional(fernet, access_token_raw)
            identity.access_token_expires_at = access_token_expires_at
        if refresh_token_raw is not None:
            identity.refresh_token_encrypted = encrypt_optional(
                fernet, refresh_token_raw
            )
        user = identity.user
        if email:
            user.email = email
        if not user.display_name:
            user.display_name = provider_username
        await db.commit()
        await db.refresh(user)
        return user

    user = User(email=email, display_name=provider_username)
    db.add(user)
    await db.flush()

    linked = LinkedIdentity(
        user_id=user.id,
        provider=provider,
        provider_user_id=provider_user_id,
        provider_username=provider_username,
        access_token_encrypted=encrypt_optional(fernet, access_token_raw),
        access_token_expires_at=access_token_expires_at,
        refresh_token_encrypted=encrypt_optional(fernet, refresh_token_raw),
    )
    db.add(linked)
    await db.commit()
    await db.refresh(user)
    return user
