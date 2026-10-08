from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from labelforge.models.base import Base, TimestampMixin
from labelforge.models.enums import SOURCE_MANUAL, ImageSource, ImageStatus, ShapeType

if TYPE_CHECKING:
    from labelforge.models.label_class import LabelClass
    from labelforge.models.project import Project


class Image(TimestampMixin, Base):
    __tablename__ = "images"
    __table_args__ = (
        UniqueConstraint("project_id", "sha256"),
        Index("ix_images_project_status", "project_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(500))
    storage_key: Mapped[str] = mapped_column(String(500))
    thumb_key: Mapped[str] = mapped_column(String(500))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default=ImageStatus.UNLABELED)
    # Asal gambar: upload langsung, import dataset, frame video, atau capture kamera RTSP.
    source_type: Mapped[str] = mapped_column(
        String(16), default=ImageSource.UPLOAD, server_default=ImageSource.UPLOAD, index=True
    )
    source_id: Mapped[int | None] = mapped_column(Integer)  # id video / kamera / import
    source_label: Mapped[str | None] = mapped_column(String(200))
    frame_time_s: Mapped[float | None] = mapped_column(Float)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dhash: Mapped[str | None] = mapped_column(String(16))  # hash perseptual 64-bit (hex)

    project: Mapped["Project"] = relationship(back_populates="images")
    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="image", cascade="all, delete-orphan", passive_deletes=True
    )


class Annotation(TimestampMixin, Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    # Bbox xyxy ternormalisasi 0-1 terhadap width/height gambar.
    x_min: Mapped[float] = mapped_column(Float)
    y_min: Mapped[float] = mapped_column(Float)
    x_max: Mapped[float] = mapped_column(Float)
    y_max: Mapped[float] = mapped_column(Float)
    shape_type: Mapped[str] = mapped_column(String(16), default=ShapeType.BBOX)
    points: Mapped[list | None] = mapped_column(JSON)  # polygon (Fase 4)
    # "manual" | "ai:grounding_dino" | "ai:owlv2_text" | "ai:owlv2_image" | "ai:remote:<x>"
    source: Mapped[str] = mapped_column(String(64), default=SOURCE_MANUAL, index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("labeling_jobs.id", ondelete="SET NULL")
    )

    image: Mapped["Image"] = relationship(back_populates="annotations")
    label_class: Mapped["LabelClass"] = relationship()
