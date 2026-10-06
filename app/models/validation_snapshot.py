from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ValidationSnapshot(Base):
    __tablename__ = "validation_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    top_n: Mapped[int] = mapped_column(Integer, server_default="20", default=20)
    predictions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    labeled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    labels: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    precision_at_10: Mapped[float | None] = mapped_column(Float)
    precision_at_20: Mapped[float | None] = mapped_column(Float)
