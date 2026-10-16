from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
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

router = APIRouter(prefix="/links", tags=["repositories"])


async def get_forgejo_token(
    sess: Annotated[UserBrowserSession, Depends(get_current_session)],
) -> str:
    """Decrypt the current user's Forgejo access token.

    Args:
        sess: The authenticated browser session.
    Returns:
        The decrypted Forgejo access token.
    Raises:
        HTTPException: If no token is registered, or it cannot be decrypted.
    """
    encrypted_token = sess.user.pat_encrypted
    if encrypted_token is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Personal access token not found. Please register one and try again.",
        )
    try:
        return decrypt_token(get_fernet(), encrypted_token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored Forgejo token cannot be decrypted. Reconnect your account in settings.",
        ) from None


async def get_forgejo_owner(
    sess: Annotated[UserBrowserSession, Depends(get_current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> str:
    """Resolve the {owner} path value from the user's linked identity.

    Owner is derived server-side rather than taken from the request so a
    caller cannot address repositories belonging to someone else.

    Args:
        sess: The authenticated browser session.
        db: A request-scoped database session.
    Returns:
        The Forgejo username linked to the signed-in user.
    Raises:
        HTTPException: If the session has no linked Forgejo identity.
    """
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
    return identity.provider_username


@router.get("/repositories")
async def get_repositories(
    app_settings: Annotated[AppSettings, Depends(get_app_settings)],
    access_token: Annotated[str, Depends(get_forgejo_token)],
    owner: Annotated[str, Depends(get_forgejo_owner)],
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
    page: Annotated[int, Query(ge=1)] = 1,
):
    """Get a page of repositories owned by the linked Forgejo account."""

    repo_page = await forgejo.get_repos(
        app_settings, access_token, owner=owner, limit=limit, page=page
    )
    return repo_page.repos


@router.get("/repositories/{repo}/branches")
async def get_repository_branches(
    app_settings: Annotated[AppSettings, Depends(get_app_settings)],
    access_token: Annotated[str, Depends(get_forgejo_token)],
    owner: Annotated[str, Depends(get_forgejo_owner)],
    repo: Annotated[str, Path(min_length=1, description="The name of the repository")],
    limit: int = 10,
    page: int = 1,
):
    """List the branches of the signed-in user's repository."""

    branches = await forgejo.get_branches(
        app_settings, access_token, owner, repo, limit=limit, page=page
    )
    return branches


@router.get("/repositories/{repo}/commits")
async def get_repository_commits(
    app_settings: Annotated[AppSettings, Depends(get_app_settings)],
    access_token: Annotated[str, Depends(get_forgejo_token)],
    owner: Annotated[str, Depends(get_forgejo_owner)],
    repo: Annotated[str, Path(min_length=1, description="The name of the repository")],
    ref: Annotated[str, Query(description="Branch name, commit sha, or tag")] = "main",
    limit: int = 10,
    page: int = 1,
):
    """List the commits of the signed-in user's repository at a ref."""

    commits = await forgejo.get_commits(
        app_settings, access_token, owner, repo, ref=ref, limit=limit, page=page
    )
    return commits
