from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import decrypt_token
from app.auth.identity import find_or_create_user
from app.auth.session import create_session, revoke_session
from app.config import get_app_settings, get_fernet
from app.deps import get_db
from app.models.app_settings import AppSettings

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Forgejo API client ──


async def _forgejo_post(app_settings: AppSettings, path: str, data: dict) -> dict:
    url = f"{app_settings.forgejo_base_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, data=data, headers={"Accept": "application/json"})
    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Cannot reach Forgejo. Check your connection settings.",
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Forgejo returned an error ({resp.status_code}). Verify your OAuth configuration.",
        )
    return resp.json()


async def _forgejo_get(app_settings: AppSettings, path: str, token: str) -> dict:
    url = f"{app_settings.forgejo_base_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers={"Authorization": f"token {token}"})
    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Cannot reach Forgejo. Check your connection settings.",
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Forgejo returned an error ({resp.status_code}). Verify your OAuth configuration.",
        )
    return resp.json()


# ── OAuth CSRF helpers ──


def _set_oauth_state_cookie(response: RedirectResponse, state: str) -> None:
    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=600,
    )


def _verify_oauth_state(state: str | None, oauth_state: str | None) -> None:
    if not state or not oauth_state or not secrets.compare_digest(state, oauth_state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state mismatch. Possible CSRF attack.",
        )


# ── Forgejo response parsers ──


def _parse_token_response(data: dict) -> tuple[str, str | None, datetime | None]:
    access_token = data.get("access_token")
    if not access_token or not isinstance(access_token, str):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Forgejo OAuth response did not include an access_token.",
        )
    refresh_token = data.get("refresh_token")
    refresh_plain = refresh_token if isinstance(refresh_token, str) else None
    expires_in = data.get("expires_in")
    if expires_in is not None:
        expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))
    else:
        expires_at = None
    return access_token, refresh_plain, expires_at


def _parse_user_response(data: dict) -> tuple[str, str, str | None]:
    provider_user_id = str(data.get("id", "")).strip()
    provider_username = str(data.get("login") or data.get("username", "")).strip()
    if not provider_user_id or not provider_username:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Forgejo user response missing id or username.",
        )
    email_val = data.get("email")
    email = email_val if isinstance(email_val, str) and email_val.strip() else None
    return provider_user_id, provider_username, email


# ── OAuth config helpers ──


def _forgejo_oauth_redirect_uri(request: Request, app_settings: AppSettings) -> str:
    base_url = app_settings.firebreak_public_base_url.strip().rstrip("/")
    if base_url:
        return f"{base_url}/auth/callback/forgejo"
    return str(request.url_for("forgejo_oauth_callback"))


def _get_oauth_client_secret(app_settings: AppSettings) -> str:
    try:
        return decrypt_token(get_fernet(), app_settings.forgejo_oauth_client_secret_encrypted)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Forgejo OAuth credentials could not be decrypted. Reconfigure at /setup.",
        )


# ── Routes ──


@router.get("/login/forgejo")
async def login_forgejo(
    request: Request, app_settings: Annotated[AppSettings, Depends(get_app_settings)]
) -> RedirectResponse:
    """Redirect the browser to Forgejo to begin OAuth sign-in."""

    redirect_uri = _forgejo_oauth_redirect_uri(request, app_settings)
    state = secrets.token_urlsafe(32)
    query = urlencode(
        {
            "client_id": app_settings.forgejo_oauth_client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    authorization_url = f"{app_settings.forgejo_base_url}/login/oauth/authorize?{query}"
    response = RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)
    _set_oauth_state_cookie(response, state)
    return response


@router.get("/callback/forgejo", name="forgejo_oauth_callback")
async def callback_forgejo(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    app_settings: Annotated[AppSettings, Depends(get_app_settings)],
    code: str | None = None,
    state: str | None = None,
    oauth_state: Annotated[str | None, Cookie()] = None,
) -> RedirectResponse:
    """Handle Forgejo's OAuth callback and create a local app session."""

    _verify_oauth_state(state, oauth_state)

    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Forgejo did not return an authorization code. The user may have denied consent.",
        )

    client_secret = _get_oauth_client_secret(app_settings)
    redirect_uri = _forgejo_oauth_redirect_uri(request, app_settings)

    token_data = await _forgejo_post(
        app_settings,
        "/login/oauth/access_token",
        {
            "grant_type": "authorization_code",
            "client_id": app_settings.forgejo_oauth_client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
    )
    access_token, refresh_plain, expires_at = _parse_token_response(token_data)

    user_data = await _forgejo_get(app_settings, "/api/v1/user", access_token)
    provider_user_id, provider_username, email = _parse_user_response(user_data)

    user = await find_or_create_user(
        db,
        app_settings,
        provider="forgejo",
        provider_user_id=provider_user_id,
        provider_username=provider_username,
        email=email,
        access_token_raw=access_token,
        access_token_expires_at=expires_at,
        refresh_token_raw=refresh_plain,
    )

    # Clear setup token on first successful login — setup is proven to work
    if request.app.state.setup_token is not None:
        request.app.state.setup_token = None

    redirect = RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)
    redirect.delete_cookie("oauth_state")

    await create_session(db, redirect, user.id, secure=request.url.scheme == "https")
    return redirect


@router.get("/logout")
async def logout(
    db: Annotated[AsyncSession, Depends(get_db)],
    firebreak_session: Annotated[str | None, Cookie()] = None,
) -> RedirectResponse:
    """Revoke the current app session and redirect back to the home page."""

    redirect = RedirectResponse("/", status_code=status.HTTP_302_FOUND)
    await revoke_session(db, redirect, firebreak_session)
    return redirect
