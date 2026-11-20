from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, HTTPException

from app.config import get_app_settings
from app.models.app_settings import AppSettings


def validate_base_url(value: str) -> str:
    """Keep authenticated requests on a configured, encrypted transport."""
    try:
        url = urlsplit(value.strip())
        local = url.hostname in {"localhost", "127.0.0.1", "::1", "forgejo"} or (
            url.hostname is not None and url.hostname.endswith(".localhost")
        )
        valid = (
            bool(url.hostname)
            and (url.scheme == "https" or (url.scheme == "http" and local))
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
        )
        _ = url.port
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(
            503,
            detail={
                "stage": "configuration",
                "message": "Configure an HTTPS Forgejo URL (HTTP is allowed for local endpoints).",
            },
        )
    return value.strip().rstrip("/")


async def get_client(
    settings: Annotated[AppSettings, Depends(get_app_settings)],
) -> AsyncIterator[httpx.AsyncClient]:
    if settings is None:
        raise HTTPException(503, detail={"stage": "configuration", "message": "Setup required."})
    base_url = validate_base_url(settings.forgejo_base_url)
    async with httpx.AsyncClient(
        base_url=base_url + "/api/v1/",
        timeout=10.0,
        follow_redirects=False,
    ) as client:
        yield client


async def get(
    client: httpx.AsyncClient,
    path: str,
    pat: str,
    stage: str,
    *,
    params: dict[str, int] | None = None,
) -> tuple[Any, httpx.Response]:
    """Return the parsed body and pagination headers without reflecting errors."""
    try:
        response = await client.get(
            path,
            params=params,
            headers={"Authorization": f"token {pat}", "Accept": "application/json"},
        )
    except httpx.RequestError:
        raise HTTPException(
            502,
            detail={
                "stage": stage,
                "message": "Cannot reach Forgejo. Check the connection settings.",
            },
        ) from None
    if response.status_code != 200:
        status = 404 if response.status_code == 404 and stage in {"repository", "branch"} else 502
        message = (
            "Forgejo could not find the selected repository or branch."
            if status == 404
            else (
                "Forgejo rejected the PAT. Check its validity and read:user/read:repository scopes."
                if response.status_code in {401, 403}
                else "Forgejo returned an unexpected response."
            )
        )
        raise HTTPException(status, detail={"stage": stage, "message": message})
    try:
        return response.json(), response
    except ValueError:
        raise malformed(stage) from None


def malformed(stage: str) -> HTTPException:
    return HTTPException(
        502, detail={"stage": stage, "message": "Forgejo returned invalid JSON data."}
    )
