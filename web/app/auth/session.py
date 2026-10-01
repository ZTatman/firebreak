from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.deps import get_db
from app.models.session import Session

SESSION_COOKIE = "firebreak_session"
SESSION_DURATION_DAYS = 7


async def create_session(
    db: AsyncSession, response: Response, user_id: uuid.UUID, secure: bool = True
) -> None:
    """Create a persisted browser session and set its cookie on the response."""

    # The browser gets the raw token, but the database only stores its hash.
    # This keeps a leaked sessions table from containing usable cookie values.
    raw_token = secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(days=SESSION_DURATION_DAYS)
    row = Session(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(row)
    await db.commit()
    # HttpOnly keeps client-side scripts from reading the session cookie. Lax is
    # enough for normal navigation while reducing cross-site request exposure.
    response.set_cookie(
        key=SESSION_COOKIE,
        value=raw_token,  # raw token is stored in the cookie, not the hash
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=60 * 60 * 24 * SESSION_DURATION_DAYS,
        path="/",
    )


async def lookup_session(
    db: AsyncSession,
    firebreak_session: str | None,
) -> Session | None:
    """Return the active session for a raw cookie token, if one exists."""

    if not firebreak_session:
        return None
    token_hash = hashlib.sha256(firebreak_session.encode()).hexdigest()
    now = datetime.now(UTC)
    stmt = (
        select(Session)
        .options(selectinload(Session.user))
        .where(
            Session.token_hash == token_hash,
            Session.expires_at > now,
            Session.revoked_at.is_(None),
        )
    )
    result = await db.execute(stmt)
    sess = result.scalar_one_or_none()
    if sess is None:
        return None
    # Track activity whenever a valid cookie is used, then refresh the related
    # user so route handlers can safely access sess.user.
    sess.last_seen_at = now
    await db.commit()
    await db.refresh(sess, attribute_names=["user"])
    return sess


async def get_current_session(
    db: Annotated[AsyncSession, Depends(get_db)],
    firebreak_session: Annotated[str | None, Cookie()] = None,
) -> Session:
    """FastAPI dependency that requires a valid signed-in session."""

    sess = await lookup_session(db, firebreak_session)
    if sess is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not signed in",
        )
    return sess


async def get_optional_session(
    db: Annotated[AsyncSession, Depends(get_db)],
    firebreak_session: Annotated[str | None, Cookie()] = None,
) -> Session | None:
    """FastAPI dependency that returns the current session when available."""

    return await lookup_session(db, firebreak_session)


async def revoke_session(
    db: AsyncSession, response: Response, firebreak_session: str | None
) -> None:
    """Delete the browser cookie and mark the matching session as revoked."""

    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        samesite="lax",
        httponly=True,
    )
    if not firebreak_session:
        return
    token_hash = hashlib.sha256(firebreak_session.encode()).hexdigest()
    await db.execute(
        update(Session)
        .where(Session.token_hash == token_hash, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()
