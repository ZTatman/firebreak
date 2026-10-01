from __future__ import annotations

import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AppSettings(Base):
    __tablename__ = "app_settings"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    forgejo_base_url: Mapped[str] = mapped_column(String, nullable=False)
    forgejo_oauth_client_id: Mapped[str] = mapped_column(String, nullable=False)
    forgejo_oauth_client_secret_encrypted: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    firebreak_public_base_url: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    setup_completed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
