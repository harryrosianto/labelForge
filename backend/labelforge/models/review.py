from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from labelforge.models.base import Base, TimestampMixin


class ReviewAudit(TimestampMixin, Base):
    """Sampel acak gambar auto-label untuk mengukur kualitas label sebelum approve massal."""

    __tablename__ = "review_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    filters: Mapped[dict] = mapped_column(JSON, default=dict)  # filter galeri saat sampel diambil
    population: Mapped[int] = mapped_column(Integer)  # jumlah gambar auto-label dalam filter
    sample_size: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)


class ReviewAuditItem(Base):
    """Satu gambar sampel. `fingerprint` = hash label saat sampel diambil (untuk deteksi koreksi)."""

    __tablename__ = "review_audit_items"

    audit_id: Mapped[int] = mapped_column(
        ForeignKey("review_audits.id", ondelete="CASCADE"), primary_key=True
    )
    image_id: Mapped[int] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(40))
