from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from labelforge.models.base import Base, TimestampMixin, utcnow

if TYPE_CHECKING:
    from labelforge.models.project import Project


class LabelClass(TimestampMixin, Base):
    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(String(9))  # hex, mis. "#ff8800"
    text_prompt: Mapped[str | None] = mapped_column(String(500))
    order_index: Mapped[int] = mapped_column(Integer, default=0)  # = index class di YOLO

    project: Mapped["Project"] = relationship(back_populates="classes")
    exemplars: Mapped[list["ClassExemplar"]] = relationship(
        back_populates="label_class", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def effective_prompt(self) -> str:
        return (self.text_prompt or self.name).strip()


class ClassExemplar(Base):
    """Contoh visual (crop) untuk mode image-guided OWLv2."""

    __tablename__ = "class_exemplars"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    source_image_id: Mapped[int | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL")
    )
    source_annotation_id: Mapped[int | None] = mapped_column(
        ForeignKey("annotations.id", ondelete="SET NULL")
    )
    # Posisi crop di gambar asal, ternormalisasi 0-1.
    x_min: Mapped[float] = mapped_column(Float)
    y_min: Mapped[float] = mapped_column(Float)
    x_max: Mapped[float] = mapped_column(Float)
    y_max: Mapped[float] = mapped_column(Float)
    crop_storage_key: Mapped[str] = mapped_column(String(500))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    label_class: Mapped["LabelClass"] = relationship(back_populates="exemplars")
