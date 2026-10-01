from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import decrypt_token
from app.auth.session import get_current_session
from app.clients import forgejo
from app.deps import get_db
from app.models.app_settings import AppSettings
from app.models.session import Session as UserBrowserSession
from app.models.user import LinkedIdentity
from app.settings import get_app_settings, get_fernet

router = APIRouter(prefix="/links", tags=["links"])


class CreateLinkRequest(BaseModel):
    repo_name: str
    repo_owner: str
    commit_sha: str
    expires_at: datetime
    link_type: Literal["public", "private"] = "public"
    recipient_email: EmailStr | None = None


class CreateLinkResponse(BaseModel):
    expires_at: datetime
    commit_sha: str
    share_url: str


async def get_forgejo_token(
    sess: Annotated[UserBrowserSession, Depends(get_current_session)],
) -> str:
    if not sess.user.has_pat:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Personal access token not found. Please register one and try again.",
        )
    try:
        return decrypt_token(get_fernet(), sess.user.pat_encrypted)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored Forgejo token cannot be decrypted. Reconnect your account in settings.",
        ) from None


@router.post("/", status_code=501)
async def create_link(request: CreateLinkRequest) -> dict:
    """Stub — link creation not yet implemented."""
    return {"detail": "Link creation is not yet implemented."}


@router.get("/repositories")
async def get_repositories(
    app_settings: Annotated[AppSettings, Depends(get_app_settings)],
    access_token: Annotated[str, Depends(get_forgejo_token)],
):
    """Get a list of the user's repositories from Forgejo."""

    repos = await forgejo.get_repos(app_settings, access_token)
    return repos


@router.get("/repositories/{repo}/branches")
async def get_repository_branches(
    app_settings: Annotated[AppSettings, Depends(get_app_settings)],
    sess: Annotated[UserBrowserSession, Depends(get_current_session)],
    access_token: Annotated[str, Depends(get_forgejo_token)],
    db: Annotated[AsyncSession, Depends(get_db)],
    repo: Annotated[str, Path(min_length=1, description="The name of the repository")],
    limit: int = 10,
    page: int = 1,
):
    # Derive {owner} path param from users linked identity provider server-side
    stmt = select(LinkedIdentity).where(
        LinkedIdentity.user_id == sess.user_id, LinkedIdentity.provider == "forgejo"
    )
    result = await db.execute(stmt)
    identity = result.scalar_one_or_none()
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No linked identity for forgejo was found. Please sign-in and try again.",
        )
    owner = identity.provider_username

    branches = await forgejo.get_branches(
        app_settings, access_token, owner, repo, limit=limit, page=page
    )
    return branches
