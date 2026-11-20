from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

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


@router.post("/", status_code=501)
async def create_link(request: CreateLinkRequest) -> dict:
    """Stub — link creation not yet implemented."""
    return {"detail": "Link creation is not yet implemented."}
