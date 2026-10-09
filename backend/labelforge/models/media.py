from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from labelforge.models.base import Base, TimestampMixin
from labelforge.models.enums import ImportStatus


class DatasetImport(TimestampMixin, Base):
    """ZIP dataset YOLO/COCO yang diunggah: dianalisis dulu, diimpor setelah pemetaan class."""

    __tablename__ = "dataset_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(500))
    storage_key: Mapped[str] = mapped_column(String(500))
    format: Mapped[str | None] = mapped_column(String(16))  # yolo | coco
    analysis: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default=ImportStatus.ANALYZED)
    error: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("labeling_jobs.id", ondelete="SET NULL"))


class Video(TimestampMixin, Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(500))
    storage_key: Mapped[str] = mapped_column(String(500))
    duration_s: Mapped[float | None] = mapped_column(Float)
    fps: Mapped[float | None] = mapped_column(Float)
    frame_count: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)


class CameraSource(TimestampMixin, Base):
    """Kamera RTSP. URL lengkap (berisi kredensial) hanya disimpan terenkripsi."""

    __tablename__ = "camera_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    url_encrypted: Mapped[str] = mapped_column(Text)
    url_masked: Mapped[str] = mapped_column(String(500))
