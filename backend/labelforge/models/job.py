from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from labelforge.models.base import Base, utcnow
from labelforge.models.enums import JobItemStatus, JobStatus, JobTarget, JobType


class LabelingJob(Base):
    __tablename__ = "labeling_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(32), default=JobType.AUTOLABEL)
    provider: Mapped[str | None] = mapped_column(String(64))  # hanya job autolabel
    mode: Mapped[str | None] = mapped_column(String(32))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    target: Mapped[str] = mapped_column(String(16), default=JobTarget.UNLABELED)
    image_ids: Mapped[list | None] = mapped_column(JSON)
    include_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED, index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict | None] = mapped_column(JSON)  # input job non-autolabel
    result: Mapped[dict | None] = mapped_column(JSON)  # ringkasan hasil
    error: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(String(64))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["LabelingJobItem"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )


class LabelingJobItem(Base):
    __tablename__ = "labeling_job_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("labeling_jobs.id", ondelete="CASCADE"), index=True
    )
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"))
    label: Mapped[str | None] = mapped_column(String(500))  # nama file / frame bila tanpa gambar
    status: Mapped[str] = mapped_column(String(16), default=JobItemStatus.PENDING)
    num_detections: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    job: Mapped["LabelingJob"] = relationship(back_populates="items")
