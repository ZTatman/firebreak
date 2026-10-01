from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import httpx
from fastapi import HTTPException, status
from pydantic import AliasChoices, AliasPath, BaseModel, Field, field_validator

from app.models.app_settings import AppSettings


class Repo(BaseModel):
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
            raise TypeError(f"expected a boolean, got {value!r}")
        return "private" if value else "public"


class Commit(BaseModel):
    id: str = Field(validation_alias=AliasChoices("sha", "id"))
    message: str
    url: str
    created_at: datetime = Field(validation_alias="timestamp")


class Branch(BaseModel):
    name: str
    protected: bool
    commit: Commit


async def get_repos(app_settings: AppSettings, access_token: str) -> list[Repo]:
    """Get the user's repositories from the Forgejo API.
    Args:
        access_token: The Forgejo API token.
    Returns:
        A list of repositories.
    """

    repos = await get(app_settings, "/api/v1/user/repos", access_token)
    if not repos:
        return []
    return [Repo.model_validate(r) for r in repos]


async def get_branches(
    app_settings: AppSettings,
    access_token: str,
    owner: str,
    repo: str,
    *,
    limit=10,
    page=1,
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

    branches = await get(
        app_settings,
        f"/api/v1/repos/{owner}/{repo}/branches?limit={limit}&page={page}",
        access_token,
    )
    if not branches:
        return []
    return [Branch.model_validate(b) for b in branches]


async def get_commits(
    app_settings: AppSettings,
    access_token: str,
    owner: str,
    repo: str,
    *,
    branch: str,
    limit: int = 10,
    page: int = 1,
) -> list[Commit]:
    """Get the commits of a branch from the Forgejo API.

    Args:
        access_token: The Forgejo API token.
        owner: The owner of the repository.
        repo: The name of the repository.
        branch: The branch to list commits for.
        limit: The maximum number of commits to return.
        page: The page number to return.

    Returns:
        A list of commits.
    """
    commits = await get(
        app_settings,
        f"/api/v1/repos/{owner}/{repo}/commits?branch={branch}&limit={limit}&page={page}",
        access_token,
    )
    if not commits:
        return []
    return commits
    # return [Commit.model_validate(c) for c in commits]


async def post(app_settings: AppSettings, path: str, data: dict) -> dict:
    """Send a POST request to the Forgejo API.

    Args:
        app_settings: The application settings.
        path: The path to the Forgejo API endpoint.
        data: The data to send in the request.

    Returns:
        The response from the Forgejo API.
    """
    try:
        async with httpx.AsyncClient(
            base_url=app_settings.forgejo_base_url, timeout=30.0
        ) as client:
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
    return resp.json()


async def get(
    app_settings: AppSettings, path: str, access_token: str
) -> dict | list[dict]:
    """Send a GET request to the Forgejo API.

    Args:
        app_settings: The application settings.
        path: The path to the Forgejo API endpoint.
        access_token: The authentication token.

    Returns:
        The response from the Forgejo API as a dictionary or list of dictionaries.
    """
    try:
        async with httpx.AsyncClient(
            base_url=app_settings.forgejo_base_url, timeout=30.0
        ) as client:
            resp = await client.get(
                path, headers={"Authorization": f"token {access_token}"}
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
    return resp.json()
