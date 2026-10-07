from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnnotationIn(BaseModel):
    """Satu box dari editor. `id` kosong = box baru (sumber manual)."""

    id: int | None = None
    class_id: int
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    is_approved: bool = True

    @model_validator(mode="after")
    def _ordered(self):
        self.x_min, self.x_max = sorted((self.x_min, self.x_max))
        self.y_min, self.y_max = sorted((self.y_min, self.y_max))
        return self


class AnnotationSet(BaseModel):
    annotations: list[AnnotationIn]
    approve: bool = Field(default=False, description="Approve semua box & tandai gambar reviewed")


class ExemplarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    class_id: int
    source_image_id: int | None
    source_annotation_id: int | None
    width: int
    height: int
    created_at: datetime
