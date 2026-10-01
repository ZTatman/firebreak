from __future__ import annotations

import httpx
from fastapi import HTTPException, status

from app.models.app_settings import AppSettings


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


async def get(app_settings: AppSettings, path: str, access_token: str) -> dict | list[dict]:
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