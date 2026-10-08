from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from labelforge.models.base import Base, TimestampMixin, utcnow
from labelforge.models.enums import VersionStatus


class DatasetVersion(TimestampMixin, Base):
    """Snapshot dataset yang tidak bisa diubah (manifest gambar + salinan anotasi)."""

    __tablename__ = "dataset_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    # filter, split, seed, preprocessing, augmentasi, dan daftar class (urutan = index)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default=VersionStatus.BUILDING)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict | None] = mapped_column(JSON)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("labeling_jobs.id", ondelete="SET NULL"))

    items: Mapped[list["DatasetVersionItem"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", passive_deletes=True
    )


class DatasetVersionItem(Base):
    """Satu gambar output di versi (gambar asli, hasil preprocessing, atau augmentasi)."""

    __tablename__ = "dataset_version_items"
    __table_args__ = (Index("ix_dataset_version_items_version_split", "version_id", "split"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE")
    )
    # Tanpa ON DELETE: gambar yang dipakai versi tidak bisa dihapus (dicek di akhir statement,
    # jadi menghapus seluruh project tetap bisa karena versinya ikut terhapus).
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id"), index=True)
    split: Mapped[str] = mapped_column(String(8))
    variant: Mapped[int] = mapped_column(Integer, default=0)  # 0 = asli, 1..n = augmentasi
    storage_key: Mapped[str | None] = mapped_column(String(500))  # None = pakai gambar asli
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    # [[class_index, x_min, y_min, x_max, y_max], ...] ternormalisasi terhadap gambar output
    annotations: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    version: Mapped["DatasetVersion"] = relationship(back_populates="items")
