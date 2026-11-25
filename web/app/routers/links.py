import hashlib
import hmac
import json
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.auth.session import get_current_session, share_link_csrf_token
from app.clients import forgejo
from app.deps import get_db
from app.models.app_settings import AppSettings
from app.models.grant import LINK_LIFETIME_DAYS, Grant
from app.models.session import Session as UserBrowserSession
from app.routers.repositories import get_forgejo_identity, get_forgejo_token
from app.settings import get_app_settings
from app.templating import templates

router = APIRouter(prefix="/links", tags=["links"])

_REPO_NAME = r"^[^/\\]+$"
_NO_STORE = {"Cache-Control": "no-store"}
_MAX_LINK_LIFETIME = timedelta(days=max(LINK_LIFETIME_DAYS))


class CreateLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_name: str = Field(max_length=255, pattern=_REPO_NAME)
    repo_owner: str | None = Field(default=None, max_length=255)
    commit_sha: str = Field(pattern=forgejo.COMMIT_SHA)
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
    _, result = await _create_public_link(link, session, db, app_settings)
    response.headers.update(_NO_STORE)
    return result


@router.post("/create", response_class=HTMLResponse, include_in_schema=False)
async def create_link_from_preview(
    request: Request,
    session: Annotated[UserBrowserSession, Depends(get_current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    app_settings: Annotated[AppSettings, Depends(get_app_settings)],
    repo_owner: Annotated[str, Form(min_length=1, max_length=255)],
    repo_name: Annotated[str, Form(max_length=255, pattern=_REPO_NAME)],
    commit_sha: Annotated[str, Form(pattern=forgejo.COMMIT_SHA)],
    ref: Annotated[str, Form(min_length=1, max_length=1024)],
    expires_in: Annotated[int, Form()],
    csrf_token: Annotated[str, Form(max_length=64)],
) -> Response:
    # The picker only works through HTMX, so this route only serves its fragments.
    _check_dashboard_form(
        request,
        session,
        csrf_token,
        wrong_place="Create links from the dashboard.",
        bad_token="Reopen the picker and try again.",
    )
    if expires_in not in LINK_LIFETIME_DAYS:
        raise HTTPException(status_code=422, detail="Choose a listed expiration.")

    link = CreateLinkRequest(
        # The owner shown on the review step; creation rejects it if the PAT's
        # account differs, so the link is for exactly what the user reviewed.
        repo_owner=repo_owner,
        repo_name=repo_name,
        commit_sha=commit_sha,
        expires_at=datetime.now(UTC) + timedelta(days=expires_in),
    )
    try:
        created_link_id, created_link = await _create_public_link(
            link, session, db, app_settings
        )
    except HTTPException as exc:
        return templates.TemplateResponse(
            request,
            "share_link.html",
            {
                "owner": repo_owner,
                "repo": repo_name,
                "ref": ref,
                "commit": commit_sha,
                "csrf_token": csrf_token,
                "expires_in": expires_in,
                "link_error": exc.detail,
                # Every access-token failure says "token"; those are fixed in Settings.
                "link_error_in_settings": "token" in str(exc.detail).lower(),
            },
            headers=_NO_STORE,
            # HTMX only swaps successful responses by default.
            status_code=200,
        )

    return templates.TemplateResponse(
        request,
        "share_links.html",
        {
            "share_links": await list_share_links(db, session.user_id),
            "created_link": created_link,
            "created_link_id": created_link_id,
            "out_of_band": True,
        },
        headers={**_NO_STORE, "HX-Trigger-After-Settle": "share-link-created"},
        status_code=201,
    )


@router.post("/{link_id}/revoke", response_class=HTMLResponse, include_in_schema=False)
async def revoke_link(
    request: Request,
    link_id: UUID,
    session: Annotated[UserBrowserSession, Depends(get_current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    csrf_token: Annotated[str, Form(max_length=64)],
) -> Response:
    # The dashboard's confirmation dialog only works through HTMX, and carries the
    # same session-bound token as the create form.
    _check_dashboard_form(
        request,
        session,
        csrf_token,
        wrong_place="Revoke links from the dashboard.",
        bad_token="Reload the page and try again.",
    )

    # One statement, so a link that expires or is revoked in the meantime is left
    # alone: an earlier revocation time is kept, and expired links keep ending at
    # their expiry. The app's clock, not the database's, so the update, the message
    # and the tabs (Grant.status) all agree on whether the link had expired.
    now = datetime.now(UTC)
    revoked_id = await db.scalar(
        update(Grant)
        .where(
            Grant.id == link_id,
            Grant.user_id == session.user_id,
            Grant.revoked_at.is_(None),
            Grant.expires_at > now,
        )
        .values(revoked_at=now)
        .returning(Grant.id)
    )
    await db.commit()

    # The response re-renders the whole list anyway, so the link is found in it.
    share_links = await list_share_links(db, session.user_id)
    link = next((link for link in share_links if link.id == link_id), None)
    if link is None:
        # Also for another user's link, so its existence isn't revealed.
        raise HTTPException(status_code=404, detail="Share link not found.")

    if revoked_id is not None:
        message = "Share link revoked."
    elif link.status_at(now) == "revoked":
        message = "This share link was already revoked."
    else:
        message = "This share link has already expired."
    return templates.TemplateResponse(
        request,
        "share_link_revoked.html",
        # The whole list, since the link moves from Active to Revoked.
        {"share_links": share_links},
        headers={
            **_NO_STORE,
            "HX-Trigger-After-Settle": json.dumps(
                {
                    "share-link-revoked": {
                        "id": str(link.id),
                        "message": message,
                        # False when it was already revoked or expired: nothing changed.
                        "revoked": revoked_id is not None,
                    }
                }
            ),
        },
    )


def _check_dashboard_form(
    request: Request,
    session: UserBrowserSession,
    csrf_token: str,
    *,
    wrong_place: str,
    bad_token: str,
) -> None:
    """Reject a dashboard form post that isn't from HTMX or lacks the session's token."""
    if request.headers.get("HX-Request") != "true":
        raise HTTPException(status_code=400, detail=wrong_place)
    if not hmac.compare_digest(
        csrf_token.encode(), share_link_csrf_token(session).encode()
    ):
        raise HTTPException(status_code=403, detail=bad_token)


async def list_share_links(db: AsyncSession, user_id: UUID) -> Sequence[Grant]:
    stmt = (
        select(Grant)
        .options(
            load_only(
                Grant.repo_owner,
                Grant.repo_name,
                Grant.commit_sha,
                Grant.created_at,
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
) -> tuple[UUID, CreateLinkResponse]:
    """Save a public link; return its ID and the one-time share URL."""
    if link.repo_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid repository name.")
    now = datetime.now(UTC)
    if link.expires_at <= now:
        raise HTTPException(status_code=400, detail="Choose a future expiration.")
    # Checked before any UTC conversion, so out-of-range timestamps are rejected
    # here rather than overflowing when the row is saved.
    if link.expires_at > now + _MAX_LINK_LIFETIME:
        raise HTTPException(
            status_code=400,
            detail=f"Choose an expiration within {_MAX_LINK_LIFETIME.days} days.",
        )

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
    # The Forgejo API returns the owner of the commit, which may differ from the
    # user-supplied owner. If the user supplied an owner, it must match the
    # Forgejo result, or the link is for a repository the user doesn't own.
    if link.repo_owner is not None and link.repo_owner.casefold() != owner.casefold():
        raise HTTPException(status_code=403, detail="Select a repository you own.")
    # Check again: the Forgejo requests above can outlast a near-term expiration.
    if link.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Choose a future expiration.")

    token = secrets.token_urlsafe(32)
    grant = Grant(
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        user_id=session.user_id,
        expires_at=link.expires_at,
        repo_owner=owner,
        repo_name=repo,
        commit_sha=link.commit_sha,
        grant_type="public",
    )
    db.add(grant)
    # The insert returns the generated ID, which stays loaded after commit.
    await db.commit()
    return grant.id, CreateLinkResponse(
        expires_at=link.expires_at,
        commit_sha=link.commit_sha,
        share_url=f"{str(base_url).rstrip('/')}/share/{token}",
    )
