from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.pat import decrypt_pat
from app.auth.session import get_current_session
from app.config import get_app_settings
from app.deps import get_db
from app.models.app_settings import AppSettings
from app.models.grant import Grant
from app.models.session import Session as BrowserSession
from app.models.user import LinkedIdentity
from app.services import forgejo
from app.services.inspection import redact

router = APIRouter(prefix="/links", tags=["links"])

SessionDep = Annotated[BrowserSession, Depends(get_current_session)]
DatabaseDep = Annotated[AsyncSession, Depends(get_db)]
ClientDep = Annotated[httpx.AsyncClient, Depends(forgejo.get_client)]
SettingsDep = Annotated[AppSettings, Depends(get_app_settings)]
Name = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[\w.-]+$")]


class CreateLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_owner: Name
    repo_name: Name
    branch: Annotated[str, Field(min_length=1, max_length=1024)]
    expires_at: AwareDatetime
    link_type: Literal["public"] = "public"

    @field_validator("repo_owner", "repo_name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if value in {".", ".."}:
            raise ValueError("Invalid repository name or owner")
        return value

    @field_validator("branch")
    @classmethod
    def valid_branch(cls, value: str) -> str:
        if (
            value == "@"
            or value.startswith(("/", "."))
            or value.endswith(("/", "."))
            or any(part.startswith(".") or part.endswith(".lock") for part in value.split("/"))
            or any(s in value for s in ("..", "//", "@{"))
            or re.search(r"[\x00-\x20\x7f~^:?*\[\\]", value)
        ):
            raise ValueError("Invalid branch name")
        return value

    @field_validator("expires_at")
    @classmethod
    def future_expiration(cls, value: datetime) -> datetime:
        if value <= datetime.now(UTC):
            raise ValueError("Expiration must be in the future")
        return value.astimezone(UTC)


class ForgejoUser(BaseModel):
    model_config = ConfigDict(strict=True)
    id: Annotated[int, Field(gt=0)]
    login: Name


class ForgejoRepository(BaseModel):
    model_config = ConfigDict(strict=True)
    owner: ForgejoUser
    name: Name
    full_name: str
    default_branch: str
    private: bool


class Repository(BaseModel):
    owner: str
    name: str
    full_name: str
    default_branch: str
    private: bool


class RepositoryResponse(BaseModel):
    repositories: list[Repository]
    page: int
    limit: int
    next_page: int | None
    inspection: dict[str, Any] | None = None


class CreatedGrant(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    repo_owner: str
    repo_name: str
    commit_sha: str
    grant_type: Literal["public"]
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    recipient_email: None
    token_hash: Literal["[redacted]"] = "[redacted]"


class CreateLinkResponse(BaseModel):
    created_grant: CreatedGrant
    share_url: str
    viewer_available: Literal[False] = False
    inspection: dict[str, Any] | None = None


async def verify_identity(
    db: AsyncSession,
    sess: BrowserSession,
    client: httpx.AsyncClient,
    pat: str,
) -> tuple[ForgejoUser, dict[str, Any]]:
    raw, _ = await forgejo.get(client, "user", pat, "identity")
    try:
        user = ForgejoUser.model_validate(raw)
    except ValidationError:
        raise forgejo.malformed("identity") from None
    identity = await db.scalar(
        select(LinkedIdentity).where(
            LinkedIdentity.user_id == sess.user_id,
            LinkedIdentity.provider == "forgejo",
            LinkedIdentity.provider_user_id == str(user.id),
        )
    )
    if identity is None:
        raise HTTPException(
            403,
            detail={
                "stage": "identity",
                "message": "The PAT must belong to your signed-in Forgejo account.",
            },
        )
    return user, raw


@router.get("/repositories", response_model_exclude_unset=True)
async def repositories(
    response: Response,
    sess: SessionDep,
    db: DatabaseDep,
    client: ClientDep,
    inspect: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
) -> RepositoryResponse:
    response.headers["Cache-Control"] = "no-store"
    pat = decrypt_pat(sess.user)
    user, raw_user = await verify_identity(db, sess, client, pat)
    raw, upstream = await forgejo.get(
        client,
        "user/repos",
        pat,
        "repositories",
        params={"page": page, "limit": limit},
    )
    if not isinstance(raw, list):
        raise forgejo.malformed("repositories")
    try:
        parsed = [ForgejoRepository.model_validate(repo) for repo in raw]
    except ValidationError:
        raise forgejo.malformed("repositories") from None
    result = RepositoryResponse(
        repositories=[
            Repository(
                owner=repo.owner.login,
                name=repo.name,
                full_name=repo.full_name,
                default_branch=repo.default_branch,
                private=repo.private,
            )
            for repo in parsed
            if repo.owner.id == user.id
        ],
        page=page,
        limit=limit,
        next_page=page + 1 if "next" in upstream.links else None,
    )
    if inspect:
        result.inspection = {
            "forgejo": redact(
                {
                    "authenticated_user": raw_user,
                    "repositories": raw,
                },
                pat,
            )
        }
    return result


def public_base_url(settings: AppSettings) -> str:
    value = settings.firebreak_public_base_url.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        )
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(
            503,
            detail={
                "stage": "configuration",
                "message": "Configure the Firebreak public base URL in setup.",
            },
        )
    return value


async def require_json(request: Request) -> None:
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise HTTPException(415, detail={"stage": "request", "message": "Send application/json."})


@router.post(
    "/", status_code=201, response_model_exclude_unset=True, dependencies=[Depends(require_json)]
)
async def create_link(
    payload: CreateLinkRequest,
    response: Response,
    sess: SessionDep,
    db: DatabaseDep,
    client: ClientDep,
    settings: SettingsDep,
    inspect: bool = False,
) -> CreateLinkResponse:
    response.headers["Cache-Control"] = "no-store"
    base_url = public_base_url(settings)
    pat = decrypt_pat(sess.user)
    user, raw_user = await verify_identity(db, sess, client, pat)
    repo_path = f"repos/{quote(payload.repo_owner, safe='')}/{quote(payload.repo_name, safe='')}"
    raw_repo, _ = await forgejo.get(client, repo_path, pat, "repository")
    try:
        repo = ForgejoRepository.model_validate(raw_repo)
    except ValidationError:
        raise forgejo.malformed("repository") from None
    if repo.owner.id != user.id:
        raise HTTPException(
            403,
            detail={
                "stage": "repository",
                "message": "Only personally owned repositories can be shared.",
            },
        )
    if (repo.name.casefold(), repo.owner.login.casefold()) != (
        payload.repo_name.casefold(),
        payload.repo_owner.casefold(),
    ):
        raise forgejo.malformed("repository")
    raw_branch, _ = await forgejo.get(
        client,
        f"{repo_path}/branches/{quote(payload.branch, safe='')}",
        pat,
        "branch",
    )
    commit = raw_branch.get("commit") if isinstance(raw_branch, dict) else None
    sha = commit.get("id") if isinstance(commit, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
        raise forgejo.malformed("branch")
    if raw_branch.get("name") != payload.branch:
        raise forgejo.malformed("branch")
    if payload.expires_at <= datetime.now(UTC):
        raise HTTPException(
            422, detail={"stage": "grant", "message": "Expiration must be in the future."}
        )
    token = secrets.token_urlsafe(32)
    grant = Grant(
        user_id=sess.user_id,
        repo_owner=repo.owner.login,
        repo_name=repo.name,
        commit_sha=sha,
        grant_type="public",
        expires_at=payload.expires_at,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        recipient_email=None,
        revoked_at=None,
    )
    try:
        db.add(grant)
        await db.flush()
        await db.refresh(grant)
        created = CreatedGrant(
            id=grant.id,
            user_id=grant.user_id,
            repo_owner=grant.repo_owner,
            repo_name=grant.repo_name,
            commit_sha=grant.commit_sha,
            grant_type="public",
            created_at=grant.created_at,
            expires_at=grant.expires_at,
            revoked_at=grant.revoked_at,
            recipient_email=None,
            token_hash="[redacted]",
        )
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            500,
            detail={
                "stage": "grant",
                "message": "Could not save the grant. Please try again.",
            },
        ) from None
    result = CreateLinkResponse(
        created_grant=created,
        share_url=f"{base_url}/s/{token}",
        viewer_available=False,
    )
    if inspect:
        result.inspection = {
            "request": payload.model_dump(mode="json"),
            "forgejo": redact(
                {
                    "authenticated_user": raw_user,
                    "repository": raw_repo,
                    "branch": raw_branch,
                },
                pat,
            ),
            "ownership": {
                "allowed": True,
                "reason": "repository owner matches authenticated Forgejo user",
            },
        }
    return result
