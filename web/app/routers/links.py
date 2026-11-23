import hashlib
import hmac
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.auth.session import get_current_session, share_link_csrf_token
from app.clients import forgejo
from app.deps import get_db
from app.models.app_settings import AppSettings
from app.models.grant import Grant
from app.models.session import Session as UserBrowserSession
from app.routers.repositories import get_forgejo_identity, get_forgejo_token
from app.settings import get_app_settings
from app.templating import templates

router = APIRouter(prefix="/links", tags=["links"])

_REPO_NAME = r"^[^/\\]+$"
_COMMIT_SHA = r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$"
_NO_STORE = {"Cache-Control": "no-store"}


class CreateLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_name: str = Field(max_length=255, pattern=_REPO_NAME)
    repo_owner: str | None = Field(default=None, max_length=255)
    commit_sha: str = Field(pattern=_COMMIT_SHA)
    expires_at: AwareDatetime


class CreateLinkResponse(BaseModel):
    expires_at: datetime
    commit_sha: str
    share_url: str


@router.post("/", status_code=201)
async def create_link(
    request: Request,
    response: Response,
    link: CreateLinkRequest,
    session: Annotated[UserBrowserSession, Depends(get_current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    app_settings: Annotated[AppSettings, Depends(get_app_settings)],
) -> CreateLinkResponse:
    # This cookie-authenticated endpoint only accepts JSON, not cross-site forms.
    content_type = request.headers.get("content-type", "").partition(";")[0]
    if content_type.strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Use application/json.")
    result = await _create_public_link(link, session, db, app_settings)
    response.headers.update(_NO_STORE)
    return result


@router.post("/create", response_class=HTMLResponse, include_in_schema=False)
async def create_link_from_preview(
    request: Request,
    session: Annotated[UserBrowserSession, Depends(get_current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    app_settings: Annotated[AppSettings, Depends(get_app_settings)],
    repo_name: Annotated[str, Form(max_length=255, pattern=_REPO_NAME)],
    commit_sha: Annotated[str, Form(pattern=_COMMIT_SHA)],
    ref: Annotated[str, Form(min_length=1, max_length=1024)],
    expires_in: Annotated[Literal["1", "7", "30"], Form()],
    csrf_token: Annotated[str, Form(max_length=64)],
) -> Response:
    if not hmac.compare_digest(
        csrf_token.encode(), share_link_csrf_token(session).encode()
    ):
        raise HTTPException(status_code=403, detail="Reopen the picker and try again.")

    link = CreateLinkRequest(
        repo_name=repo_name,
        commit_sha=commit_sha,
        expires_at=datetime.now(UTC) + timedelta(days=int(expires_in)),
    )
    is_htmx = request.headers.get("HX-Request") == "true"
    try:
        created_link = await _create_public_link(link, session, db, app_settings)
    except HTTPException as exc:
        return templates.TemplateResponse(
            request,
            "share_link.html",
            {
                "user": session.user,
                "repo": repo_name,
                "ref": ref,
                "commit": commit_sha,
                "csrf_token": csrf_token,
                "expires_in": expires_in,
                "link_error": exc.detail,
                "full_page": not is_htmx,
            },
            headers=_NO_STORE,
            # HTMX only swaps successful responses by default.
            status_code=200 if is_htmx else exc.status_code,
        )

    headers = (
        {**_NO_STORE, "HX-Trigger-After-Settle": "share-link-created"}
        if is_htmx
        else _NO_STORE
    )
    return templates.TemplateResponse(
        request,
        "share_links.html",
        {
            "user": session.user,
            "share_links": await list_share_links(db, session.user_id),
            "created_link": created_link,
            "out_of_band": is_htmx,
            "full_page": not is_htmx,
        },
        headers=headers,
        status_code=201,
    )


async def list_share_links(db: AsyncSession, user_id: UUID) -> Sequence[Grant]:
    stmt = (
        select(Grant)
        .options(
            load_only(
                Grant.repo_owner,
                Grant.repo_name,
                Grant.commit_sha,
                Grant.expires_at,
                Grant.revoked_at,
            )
        )
        .where(Grant.user_id == user_id)
        .order_by(Grant.created_at.desc(), Grant.id.desc())
    )
    return (await db.scalars(stmt)).all()


async def _create_public_link(
    link: CreateLinkRequest,
    session: UserBrowserSession,
    db: AsyncSession,
    app_settings: AppSettings,
) -> CreateLinkResponse:
    if link.repo_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid repository name.")
    if link.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Choose a future expiration.")

    try:
        base_url = httpx.URL(app_settings.firebreak_public_base_url.strip())
    except httpx.InvalidURL:
        base_url = httpx.URL("")
    if (
        base_url.scheme not in {"http", "https"}
        or not base_url.host
        or base_url.userinfo
        or base_url.query
        or base_url.fragment
    ):
        raise HTTPException(
            status_code=503, detail="Configure a valid Public Base URL in setup."
        )

    identity = await get_forgejo_identity(session, db)
    access_token = await get_forgejo_token(session)
    owner, repo = await forgejo.verify_owned_commit(
        app_settings,
        access_token,
        identity.provider_user_id,
        link.repo_name,
        link.commit_sha,
    )
    if link.repo_owner is not None and link.repo_owner.casefold() != owner.casefold():
        raise HTTPException(status_code=403, detail="Select a repository you own.")
    # Check again: the Forgejo requests above can outlast a near-term expiration.
    if link.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Choose a future expiration.")

    token = secrets.token_urlsafe(32)
    db.add(
        Grant(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            user_id=session.user_id,
            expires_at=link.expires_at,
            repo_owner=owner,
            repo_name=repo,
            commit_sha=link.commit_sha,
            grant_type="public",
        )
    )
    await db.commit()
    return CreateLinkResponse(
        expires_at=link.expires_at,
        commit_sha=link.commit_sha,
        share_url=f"{str(base_url).rstrip('/')}/share/{token}",
    )
