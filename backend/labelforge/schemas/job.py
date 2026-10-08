from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from labelforge.models.enums import JobTarget


class AutolabelJobCreate(BaseModel):
    provider: str | None = Field(default=None, description="Kosong = provider default")
    mode: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    target: JobTarget = JobTarget.UNLABELED
    image_ids: list[int] | None = None
    include_reviewed: bool = False


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    job_type: str
    provider: str | None
    mode: str | None
    params: dict[str, Any]
    target: str
    include_reviewed: bool
    status: str
    total: int
    processed: int
    failed_count: int
    warnings: list[str]
    payload: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @computed_field
    @property
    def progress(self) -> float:
        """0..1"""
        return round(self.processed / self.total, 4) if self.total else 0.0


class JobItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    image_id: int | None
    label: str | None = None
    status: str
    num_detections: int | None
    error: str | None
    duration_ms: int | None
