from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, get_args

from sqlalchemy import Enum, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from .user import User

GrantType = Literal["public", "private"]

# Public links must expire. These are the lifetimes the dashboard offers, and the
# longest one is the cap for every way of creating a link.
LINK_LIFETIME_DAYS = (1, 7, 30)
DEFAULT_LINK_LIFETIME_DAYS = 7


class Grant(Base):
    __tablename__ = "grants"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    token_hash: Mapped[str] = mapped_column(
        String, unique=True, nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    repo_owner: Mapped[str] = mapped_column(String, nullable=False)
    repo_name: Mapped[str] = mapped_column(String, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String, nullable=False)
    grant_type: Mapped[GrantType] = mapped_column(
        Enum(*get_args(GrantType), name="grant_type_enum"),
        nullable=False,
        default="public",
    )
    recipient_email: Mapped[str | None] = mapped_column(String, nullable=True)

    user: Mapped[User] = relationship("User", back_populates="grants")

    @property
    def status(self) -> Literal["active", "expired", "revoked"]:
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at <= datetime.now(UTC):
            return "expired"
        return "active"

    @property
    def ends_at(self) -> datetime:
        """When access ends: the revocation time, else the scheduled expiry."""
        return self.revoked_at or self.expires_at
