from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status
from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from app.models.app_settings import AppSettings

_LOCAL_HTTP_HOSTS = {"localhost", "127.0.0.1", "::1", "forgejo"}
# A full SHA-1 or SHA-256 commit ID, as Forgejo returns them (lowercase hex).
COMMIT_SHA = r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$"


def _authenticated_base_url(value: str) -> httpx.URL:
    """Require encrypted transport except for documented local Forgejo hosts."""
    try:
        url = httpx.URL(value.strip())
    except httpx.InvalidURL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configure a valid Forgejo URL in setup.",
        ) from None

    local_http = url.scheme == "http" and (
        url.host in _LOCAL_HTTP_HOSTS or url.host.endswith(".localhost")
    )
    if (
        not url.host
        or (url.scheme != "https" and not local_http)
        or url.userinfo
        or url.query
        or url.fragment
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configure an HTTPS Forgejo URL in setup. HTTP is only allowed for local Forgejo endpoints.",
        )
    return url


class Repo(BaseModel):
    """A repository returned by Forgejo."""

    repo_name: str = Field(validation_alias="name")
    repo_full_name: str = Field(validation_alias="full_name")
    repo_owner: str = Field(validation_alias=AliasPath("owner", "username"))
    default_branch: str
    description: str | None
    visibility: Literal["private", "public"] = Field(validation_alias="private")
    html_url: str
    created_at: datetime
    updated_at: datetime
    archived: bool
    archived_at: datetime | None

    @field_validator("visibility", mode="before")
    @classmethod
    def map_visibility(cls, value: Any) -> Literal["private", "public"]:
        if not isinstance(value, bool):
            raise ValueError("expected a boolean")  # noqa: TRY004
        return "private" if value else "public"


@dataclass(frozen=True)
class RepoPage:
    repos: list[Repo]
    total_count: int | None
    has_next_page: bool


class Commit(BaseModel):
    """A commit, normalized across Forgejo's two payload shapes.

    ``/branches`` nests a trimmed commit keyed ``id``/``timestamp``/``url``,
    while ``/commits`` returns a flat GitHub-style object keyed
    ``sha``/``commit.message``/``html_url``/``created``. Each field therefore
    accepts either shape.
    """

    id: str = Field(
        validation_alias=AliasChoices("sha", "id"),
        pattern=COMMIT_SHA,
    )
    message: str = Field(
        validation_alias=AliasChoices("message", AliasPath("commit", "message"))
    )
    url: str = Field(validation_alias=AliasChoices("html_url", "url"))
    created_at: datetime = Field(
        validation_alias=AliasChoices(
            "timestamp",
            "created_at",
            "created",
            AliasPath("commit", "committer", "date"),
        )
    )


class Branch(BaseModel):
    """A branch returned by Forgejo."""

    name: str
    protected: bool
    commit: Commit


_REPOSITORIES = TypeAdapter(list[Repo])
_BRANCHES = TypeAdapter(list[Branch])
_BRANCH = TypeAdapter(Branch)
_COMMITS = TypeAdapter(list[Commit])
_OBJECT = TypeAdapter(dict[str, Any])


def _malformed_response() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Forgejo returned unexpected data. Check the Forgejo URL and try again.",
    )


def _parse_json[T](response: httpx.Response, adapter: TypeAdapter[T]) -> T:
    try:
        return adapter.validate_json(response.content)
    except ValidationError:
        raise _malformed_response() from None


async def get_repos(
    app_settings: AppSettings,
    access_token: str,
    *,
    limit: int = 30,
    page: int = 1,
    owner: str | None = None,
) -> RepoPage:
    """Get the user's repositories from the Forgejo API.

    Forgejo paginates this endpoint and caps `limit` at the instance's
    max_response_items (50 on the default config), so a caller asking for
    everything silently gets one page. Paging is exposed here rather than
    looped internally so the caller can decide how many round trips to spend.

    Args:
        app_settings: The application settings.
        access_token: The Forgejo API token.
        limit: The maximum number of repositories to return.
        page: The page number to return.
        owner: Restrict results to repositories owned by this username.
    Returns:
        The repositories and Forgejo's total-count pagination metadata.
    """
    params: dict[str, str | int] = {"limit": limit, "page": page}
    endpoint = f"/users/{quote(owner, safe='')}/repos" if owner else "/user/repos"
    path = f"/api/v1{endpoint}?{httpx.QueryParams(params)}"
    response = await _get(app_settings, path, access_token)
    repos = _parse_json(response, _REPOSITORIES)
    total_count_header = response.headers.get("x-total-count")
    try:
        total_count = int(total_count_header) if total_count_header else None
    except ValueError:
        total_count = None
    return RepoPage(
        repos=repos,
        total_count=total_count,
        has_next_page="next" in response.links,
    )


async def get_branches(
    app_settings: AppSettings,
    access_token: str,
    owner: str,
    repo: str,
    *,
    limit: int = 10,
    page: int = 1,
) -> list[Branch]:
    """Get the branches of a repository from the Forgejo API.
    Args:
        access_token: The Forgejo API token.
        owner: The owner of the repository.
        repo: The name of the repository.
        limit: The maximum number of branches to return.
        page: The page number to return.
    Returns:
        A list of branches.
    """

    response = await _get(
        app_settings,
        f"/api/v1/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/branches?"
        f"{httpx.QueryParams({'limit': limit, 'page': page})}",
        access_token,
    )
    return _parse_json(response, _BRANCHES)


async def get_branch_tip(
    app_settings: AppSettings, access_token: str, owner: str, repo: str, branch: str
) -> str:
    """Resolve a branch by name without letting Git choose a tag or other ref."""
    response = await _get(
        app_settings,
        f"/api/v1/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
        f"/branches/{quote(branch, safe='')}",
        access_token,
    )
    result = _parse_json(response, _BRANCH)
    if result.name != branch:
        raise _malformed_response()
    return result.commit.id


async def get_commits(
    app_settings: AppSettings,
    access_token: str,
    owner: str,
    repo: str,
    *,
    ref: str,
    limit: int = 10,
    page: int = 1,
) -> list[Commit]:
    """Get the commits of a branch from the Forgejo API.

    Args:
        access_token: The Forgejo API token.
        owner: The owner of the repository.
        repo: The name of the repository.
        ref: The branch name, commit sha, or tag to list commits for.
        limit: The maximum number of commits to return.
        page: The page number to return.

    Returns:
        A list of commits.
    """
    response = await _get(
        app_settings,
        f"/api/v1/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/commits?"
        f"{httpx.QueryParams({'sha': ref, 'limit': limit, 'page': page})}",
        access_token,
    )
    return _parse_json(response, _COMMITS)


async def verify_owned_commit(
    app_settings: AppSettings,
    access_token: str,
    provider_user_id: str,
    repo: str,
    commit_sha: str,
) -> tuple[str, str]:
    """Verify the PAT owner and exact commit, returning canonical repo names."""
    user = await get(app_settings, "/api/v1/user", access_token)
    owner = user.get("login")
    user_id = user.get("id")
    if type(user_id) is not int or not isinstance(owner, str) or not owner:
        raise _malformed_response()
    if str(user_id) != provider_user_id:
        raise HTTPException(
            status_code=403, detail="Use a Forgejo token from your linked account."
        )

    path = f"/api/v1/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
    repository = await get(
        app_settings, path, access_token, not_found="Repository not found."
    )
    repo_owner = repository.get("owner")
    repo_name = repository.get("name")
    if not isinstance(repo_owner, dict) or not isinstance(repo_name, str):
        raise _malformed_response()
    if repo_owner.get("id") != user_id or repo_name.casefold() != repo.casefold():
        raise HTTPException(status_code=403, detail="Select a repository you own.")

    commit = await get(
        app_settings,
        f"{path}/git/commits/{quote(commit_sha, safe='')}?"
        f"{httpx.QueryParams({'stat': 'false', 'verification': 'false', 'files': 'false'})}",
        access_token,
        not_found="The selected commit was not found in this repository.",
    )
    if commit.get("sha") != commit_sha:
        raise _malformed_response()
    return owner, repo_name


async def post(app_settings: AppSettings, path: str, data: dict) -> dict:
    """Send a POST request to the Forgejo API.

    Args:
        app_settings: The application settings.
        path: The path to the Forgejo API endpoint.
        data: The data to send in the request.

    Returns:
        The response from the Forgejo API.
    """
    base_url = _authenticated_base_url(app_settings.forgejo_base_url)
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            resp = await client.post(
                path, data=data, headers={"Accept": "application/json"}
            )
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
    return _parse_json(resp, _OBJECT)


async def get(
    app_settings: AppSettings,
    path: str,
    access_token: str,
    *,
    not_found: str | None = None,
) -> dict[str, Any]:
    """Fetch a JSON object from the Forgejo API."""
    response = await _get(app_settings, path, access_token, not_found=not_found)
    return _parse_json(response, _OBJECT)


async def _get(
    app_settings: AppSettings,
    path: str,
    access_token: str,
    *,
    not_found: str | None = None,
) -> httpx.Response:
    """Fetch a response without dropping headers needed for pagination."""
    base_url = _authenticated_base_url(app_settings.forgejo_base_url)
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            resp = await client.get(
                path, headers={"Authorization": f"token {access_token}"}
            )
    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Cannot reach Forgejo. Check your connection settings.",
        )
    if resp.status_code == 200:
        return resp
    if resp.status_code == 404 and not_found:
        raise HTTPException(status_code=404, detail=not_found)
    if resp.status_code in {401, 403}:
        detail = (
            "Forgejo rejected the access token. For repository browsing, "
            "check that your personal access token is valid and has "
            "read:user and read:repository scopes."
        )
    else:
        detail = f"Forgejo returned an error ({resp.status_code}). Check the connection settings and try again."
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
