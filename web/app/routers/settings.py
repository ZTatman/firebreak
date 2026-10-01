from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.auth.crypto import encrypt_optional
from app.auth.session import get_current_session
from app.deps import get_db
from app.models.session import Session as UserBrowserSession
from app.settings import get_fernet
from app.templating import templates

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    sess: Annotated[UserBrowserSession, Depends(get_current_session)],
) -> Response:
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": sess.user,
            "pat_registered": sess.user.has_pat,
            "pat_registered_at": sess.user.pat_registered_at,
            "pat_deleted": request.query_params.get("pat") == "deleted",
        },
    )


@router.post("/pat")
async def register_pat(
    pat: Annotated[str, Form()],
    db: Annotated[AsyncSession, Depends(get_db)],
    sess: Annotated[UserBrowserSession, Depends(get_current_session)],
) -> RedirectResponse:
    pat = pat.strip()
    if not pat:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Forgejo access token is required.",
        )

    fernet = get_fernet()
    sess.user.pat_encrypted = encrypt_optional(fernet, pat)
    sess.user.pat_registered_at = datetime.now(UTC)
    await db.commit()

    return RedirectResponse(
        "/settings?pat=registered",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/pat/delete")
async def delete_pat(
    db: Annotated[AsyncSession, Depends(get_db)],
    sess: Annotated[UserBrowserSession, Depends(get_current_session)],
) -> RedirectResponse:
    sess.user.pat_encrypted = None
    sess.user.pat_registered_at = None
    await db.commit()

    return RedirectResponse(
        "/settings?pat=deleted",
        status_code=status.HTTP_303_SEE_OTHER,
    )
