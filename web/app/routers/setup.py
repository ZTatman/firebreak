from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func as sql_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.auth.crypto import encrypt_token
from app.auth.session import lookup_session
from app.deps import get_db
from app.models.app_settings import AppSettings
from app.models.user import User
from app.settings import get_fernet
from app.templating import templates

router = APIRouter(prefix="/setup", tags=["setup"])


async def _require_auth_if_configured(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    firebreak_session: Annotated[str | None, Cookie()] = None,
) -> None:
    """Block anonymous access to /setup after initial configuration.

    If no users exist yet (e.g. bad OAuth config on first setup), the setup
    token is still required but login is not — there's nobody to log in as.
    """
    if request.app.state.app_settings is None:
        return

    # If no users exist, allow access — the setup token still protects POST
    user_count = await db.scalar(select(sql_func.count()).select_from(User)) or 0
    if user_count == 0:
        return

    sess = await lookup_session(db, firebreak_session)
    if sess is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to reconfigure Firebreak.",
        )


@router.get("", dependencies=[Depends(_require_auth_if_configured)])
async def setup_page(
    request: Request, db: Annotated[AsyncSession, Depends(get_db)]
) -> Response:
    """Render the setup wizard. Pre-fills fields when reconfiguring."""
    existing = request.app.state.app_settings
    user_count = await db.scalar(select(sql_func.count()).select_from(User)) or 0
    has_users = user_count > 0
    public_base = (existing.firebreak_public_base_url if existing else "") or str(
        request.base_url
    ).rstrip("/")
    ctx = {
        "reconfiguring": existing is not None and has_users,
        "forgejo_base_url": existing.forgejo_base_url if existing else "",
        "forgejo_oauth_client_id": existing.forgejo_oauth_client_id if existing else "",
        "firebreak_public_base_url": existing.firebreak_public_base_url
        if existing
        else "",
        "oauth_callback_url": f"{public_base}/auth/callback/forgejo",
    }
    return templates.TemplateResponse(request, "setup.html", ctx)


@router.post("", dependencies=[Depends(_require_auth_if_configured)])
async def setup_submit(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    forgejo_base_url: Annotated[str, Form()],
    forgejo_oauth_client_id: Annotated[str, Form()],
    forgejo_oauth_client_secret: Annotated[str, Form()] = "",
    firebreak_public_base_url: Annotated[str, Form()] = "",
    setup_token: Annotated[str, Form()] = "",
) -> RedirectResponse:
    """Process the setup wizard — creates or updates Forgejo settings."""
    user_count = await db.scalar(select(sql_func.count()).select_from(User)) or 0
    has_users = user_count > 0
    is_reconfiguring = request.app.state.app_settings is not None and has_users

    # Require setup token when no users exist (first-time or fixing bad config)
    if not has_users:
        expected = request.app.state.setup_token
        if not expected or setup_token.strip() != expected:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid setup token. Check your server logs for the correct token.",
            )

    forgejo_base_url = forgejo_base_url.strip().rstrip("/")
    forgejo_oauth_client_id = forgejo_oauth_client_id.strip()
    forgejo_oauth_client_secret = forgejo_oauth_client_secret.strip()
    firebreak_public_base_url = firebreak_public_base_url.strip().rstrip("/")

    if not forgejo_base_url or not forgejo_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Forgejo URL and Client ID are required.",
        )

    if is_reconfiguring:
        result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=500, detail="Settings row missing during reconfiguration."
            )
        row.forgejo_base_url = forgejo_base_url
        row.forgejo_oauth_client_id = forgejo_oauth_client_id
        row.firebreak_public_base_url = firebreak_public_base_url
        if forgejo_oauth_client_secret:
            try:
                fernet = get_fernet()
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        "TOKEN_ENCRYPTION_KEY is not set. Add it to your .env file or deployment "
                        "environment. Generate one with: "
                        "uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
                    ),
                )
            row.forgejo_oauth_client_secret_encrypted = encrypt_token(
                fernet, forgejo_oauth_client_secret
            )
        await db.commit()
        await db.refresh(row)
        request.app.state.app_settings = row
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    # First-time setup (or retry after bad config) — no users exist yet
    if not forgejo_oauth_client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client Secret is required during initial setup.",
        )

    try:
        fernet = get_fernet()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "TOKEN_ENCRYPTION_KEY is not set. Add it to your .env file or deployment "
                "environment. Generate one with: "
                "uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            ),
        )
    encrypted_secret = encrypt_token(fernet, forgejo_oauth_client_secret)

    # Update existing row if retrying after bad config, otherwise create
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    row = result.scalar_one_or_none()
    if row:
        row.forgejo_base_url = forgejo_base_url
        row.forgejo_oauth_client_id = forgejo_oauth_client_id
        row.forgejo_oauth_client_secret_encrypted = encrypted_secret
        row.firebreak_public_base_url = firebreak_public_base_url
    else:
        row = AppSettings(
            id=1,
            forgejo_base_url=forgejo_base_url,
            forgejo_oauth_client_id=forgejo_oauth_client_id,
            forgejo_oauth_client_secret_encrypted=encrypted_secret,
            firebreak_public_base_url=firebreak_public_base_url,
        )
        db.add(row)
    await db.commit()
    await db.refresh(row)
    request.app.state.app_settings = row

    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
