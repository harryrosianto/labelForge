from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

HEX_COLOR = r"^#[0-9a-fA-F]{6}$"


def _clean_name(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("Nama class tidak boleh kosong")
    return v


def _clean_prompt(v: str | None) -> str | None:
    if v is None:
        return None
    v = " ".join(v.split())
    return v or None


ClassName = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_clean_name)]
TextPrompt = Annotated[str | None, Field(max_length=500), AfterValidator(_clean_prompt)]
Color = Annotated[str, Field(pattern=HEX_COLOR)]


class ClassCreate(BaseModel):
    name: ClassName
    color: Color | None = None
    text_prompt: TextPrompt = None


class ClassUpdate(BaseModel):
    name: ClassName | None = None
    color: Color | None = None
    text_prompt: TextPrompt = None


class ClassOrder(BaseModel):
    class_ids: list[int]


class ClassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    color: str
    text_prompt: str | None
    effective_prompt: str
    order_index: int
    annotation_count: int = 0
    exemplar_count: int = 0
