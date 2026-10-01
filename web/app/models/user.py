from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from .grant import Grant
    from .session import Session


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    pat_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    pat_registered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    @property
    def has_pat(self) -> bool:
        return self.pat_encrypted is not None

    # One-to-many relationship with LinkedIdentity: A user could have multiple identitiy providers
    # LinkedIdentity is a table that stores all the identities of the user
    # for example, GitHub, GitLab, etc.
    identities: Mapped[list[LinkedIdentity]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # One-to-many relationship with Session: A user could have multiple cross-browser sessions
    # Session is a table that stores all the possible browser sessions of the user
    sessions: Mapped[list[Session]] = relationship(
        "Session",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # One-to-many relationship with Grant
    # Grant is a table that stores all the share links a user creates
    grants: Mapped[list[Grant]] = relationship(
        "Grant",
        back_populates="user",
    )


class LinkedIdentity(Base):
    __tablename__ = "linked_identities"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String, nullable=False)
    provider_username: Mapped[str] = mapped_column(String, nullable=False)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped[User] = relationship(back_populates="identities")

    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)
