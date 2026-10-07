from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from labelforge.models.enums import TaskType


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    task_type: TaskType = TaskType.OBJECT_DETECTION

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Nama tidak boleh kosong")
        return v


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Nama tidak boleh kosong")
        return v


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    task_type: str
    created_at: datetime
    updated_at: datetime
    image_count: int = 0
    class_count: int = 0


class ClassCount(BaseModel):
    class_id: int
    name: str
    color: str
    annotations: int


class ProjectStats(BaseModel):
    total_images: int
    total_annotations: int
    images_by_status: dict[str, int]
    annotations_by_class: list[ClassCount]
    annotations_by_source: dict[str, int]
    unapproved_annotations: int
