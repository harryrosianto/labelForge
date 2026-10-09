"""Tabel untuk Fase 3 (model registry)."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from labelforge.models.base import Base, utcnow


class MLModel(Base):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    dataset_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200))
    framework: Mapped[str] = mapped_column(String(64))
    weights_key: Mapped[str | None] = mapped_column(String(500))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
