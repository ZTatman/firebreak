from itertools import count
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import decrypt_token
from app.auth.session import get_current_session, share_link_csrf_token
from app.clients import forgejo
from app.deps import get_db
from app.models.app_settings import AppSettings
from app.models.grant import DEFAULT_LINK_LIFETIME_DAYS
from app.models.session import Session as UserBrowserSession
from app.models.user import LinkedIdentity
from app.settings import get_app_settings, get_fernet
from app.templating import templates

router = APIRouter(prefix="/links", tags=["repositories"])
picker_router = APIRouter(prefix="/dashboard/snapshot-picker", include_in_schema=False)


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
    return (await get_forgejo_identity(sess, db)).provider_username


async def get_forgejo_identity(
    sess: UserBrowserSession, db: AsyncSession
) -> LinkedIdentity:
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
    return identity


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


RECENT_COMMITS = 30
PICKER_PAGE_SIZE = 50


@picker_router.get("/preview", response_class=HTMLResponse)
async def preview_snapshot(
    request: Request,
    session: Annotated[UserBrowserSession, Depends(get_current_session)],
    owner: Annotated[str, Depends(get_forgejo_owner)],
    repo: Annotated[str, Query(min_length=1, max_length=255)],
    ref: Annotated[str, Query(min_length=1, max_length=1024)],
    commit: Annotated[str, Query(pattern=forgejo.COMMIT_SHA)],
) -> Response:
    """Render the dialog's review step without creating a share link."""
    return templates.TemplateResponse(
        request,
        "share_link.html",
        {
            "owner": owner,
            "repo": repo,
            "ref": ref,
            "commit": commit,
            "csrf_token": share_link_csrf_token(session),
            "expires_in": DEFAULT_LINK_LIFETIME_DAYS,
        },
        headers={"Cache-Control": "no-store"},
    )


@picker_router.get("/{step}", response_class=HTMLResponse)
async def get_snapshot_picker_step(
    request: Request,
    step: Literal["repository", "branch", "commit"],
    app_settings: Annotated[AppSettings, Depends(get_app_settings)],
    session: Annotated[UserBrowserSession, Depends(get_current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    repo: Annotated[str, Query(max_length=255)] = "",
    ref: Annotated[str, Query(max_length=1024)] = "",
) -> Response:
    """Load dependent picker options without changing the JSON listing API."""
    if step != "repository" and (repo in {".", ".."} or "/" in repo or "\\" in repo):
        raise HTTPException(status_code=400, detail="Invalid repository name.")

    options: list[tuple[str, str]] = []
    error = False
    message = ""
    try:
        if step == "repository" or (repo and (step == "branch" or ref)):
            access_token = await get_forgejo_token(session)
            owner = await get_forgejo_owner(session, db)
            options = await _snapshot_options(
                step, app_settings, access_token, owner, repo, ref
            )
            if not options:
                message = {
                    "repository": "No repositories found.",
                    "branch": "No branches found.",
                    "commit": "No commits found.",
                }[step]
    except HTTPException as exc:
        if exc.status_code not in {403, 502, 503}:
            raise
        error = True
        message = str(exc.detail)

    return templates.TemplateResponse(
        request,
        "snapshot_picker.html",
        {
            "step": step,
            "options": options,
            "message": message,
            "error": error,
            "repo": repo,
            "ref": ref,
        },
        headers={"Cache-Control": "no-store"},
        block_name={
            "repository": "picker_steps",
            "branch": "branch_steps",
            "commit": "commit_step",
        }[step],
    )


async def _snapshot_options(
    step: Literal["repository", "branch", "commit"],
    app_settings: AppSettings,
    access_token: str,
    owner: str,
    repo: str,
    ref: str,
) -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    if step == "commit":
        ref = await forgejo.get_branch_tip(app_settings, access_token, owner, repo, ref)
    for page in count(1):
        if step == "repository":
            result = await forgejo.get_repos(
                app_settings,
                access_token,
                owner=owner,
                page=page,
                limit=PICKER_PAGE_SIZE,
            )
            options.extend((item.repo_name, item.repo_name) for item in result.repos)
            if not result.has_next_page or not result.repos:
                break
        elif step == "branch":
            branches = await forgejo.get_branches(
                app_settings,
                access_token,
                owner,
                repo,
                page=page,
                limit=PICKER_PAGE_SIZE,
            )
            if not branches:
                break
            options.extend((item.name, item.name) for item in branches)
        else:
            commits = await forgejo.get_commits(
                app_settings,
                access_token,
                owner,
                repo,
                ref=ref,
                page=page,
                limit=RECENT_COMMITS,
            )
            if not commits:
                break
            for item in commits[: RECENT_COMMITS - len(options)]:
                subject = item.message.partition("\n")[0]
                options.append((item.id, f"{item.id[:7]} — {subject}"))
            if len(options) == RECENT_COMMITS:
                break
    return options
