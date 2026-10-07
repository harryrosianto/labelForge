from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from labelforge.models.enums import ImageStatus


class AnnotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    class_id: int
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    source: str
    confidence: float | None
    is_approved: bool


class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    original_filename: str
    width: int
    height: int
    status: str
    created_at: datetime
    updated_at: datetime


class ImageListItem(ImageOut):
    annotations: list[AnnotationOut] = []


class ImagePage(BaseModel):
    items: list[ImageListItem]
    total: int
    page: int
    page_size: int


class ImageDetail(ImageListItem):
    prev_id: int | None = None
    next_id: int | None = None
    position: int | None = Field(default=None, description="Urutan (1-based) dalam filter aktif")
    filtered_total: int | None = None


class UploadIssue(BaseModel):
    filename: str
    detail: str
    image_id: int | None = None


class UploadResult(BaseModel):
    uploaded: list[ImageOut]
    duplicates: list[UploadIssue]
    skipped: list[UploadIssue]
    errors: list[UploadIssue]


class ImageIds(BaseModel):
    image_ids: list[int] = Field(min_length=1)


class ImageFilters(BaseModel):
    status: ImageStatus | None = None
    class_id: int | None = None
    source: str | None = Field(default=None, description='"manual", "ai" (semua AI), atau tag lengkap')
    max_conf: float | None = Field(default=None, ge=0, le=1,
                                   description="Punya box AI belum di-approve dengan confidence < nilai ini")  # fmt: skip
