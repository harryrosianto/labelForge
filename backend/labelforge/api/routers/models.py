from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from labelforge.api.deps import DbSession, Storage, get_project_or_404
from labelforge.models import Annotation, DatasetVersion, MLModel
from labelforge.services.ml_models import (
    ModelRequestError,
    check_version,
    register_onnx,
    validate_class_map,
)

router = APIRouter(tags=["models"])


class ModelOut(BaseModel):
    id: int
    project_id: int
    name: str
    framework: str
    status: str
    provider: str
    dataset_version_id: int | None
    dataset_version_name: str | None
    metrics: dict[str, Any]
    notes: str | None
    names: list[str]
    input_size: list[int]
    class_map: dict[str, int | None]
    size_bytes: int | None
    annotations: int  # box hasil auto-label model ini
    created_at: datetime


def _out(db: DbSession, model: MLModel) -> ModelOut:
    cfg = model.config or {}
    version = db.get(DatasetVersion, model.dataset_version_id) if model.dataset_version_id else None
    count = db.scalar(select(func.count(Annotation.id)).where(Annotation.source == f"ai:model:{model.id}"))
    return ModelOut(
        id=model.id, project_id=model.project_id, name=model.name, framework=model.framework,
        status=model.status, provider=f"model:{model.id}", dataset_version_id=model.dataset_version_id,
        dataset_version_name=version.name if version else None, metrics=model.metrics or {},
        notes=model.notes, names=cfg.get("names", []), input_size=cfg.get("input_size", []),
        class_map=cfg.get("class_map", {}), size_bytes=cfg.get("size_bytes"), annotations=count or 0,
        created_at=model.created_at,
    )  # fmt: skip


def _get_model(db: DbSession, model_id: int) -> MLModel:
    model = db.get(MLModel, model_id)
    if model is None:
        raise HTTPException(404, f"Model {model_id} tidak ditemukan")
    return model


@router.get("/projects/{project_id}/models", response_model=list[ModelOut])
def list_models(project_id: int, db: DbSession):
    get_project_or_404(db, project_id)
    models = db.scalars(select(MLModel).where(MLModel.project_id == project_id).order_by(MLModel.id.desc()))
    return [_out(db, m) for m in models]


@router.post("/projects/{project_id}/models", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
def upload_model(
    project_id: int,
    db: DbSession,
    storage: Storage,
    file: Annotated[UploadFile, File()],
    name: Annotated[str | None, Form()] = None,
    dataset_version_id: Annotated[int | None, Form()] = None,
    map50: Annotated[float | None, Form(ge=0, le=1)] = None,
    map50_95: Annotated[float | None, Form(ge=0, le=1)] = None,
    notes: Annotated[str | None, Form(max_length=5000)] = None,
):
    """Upload model ONNX (mis. best.onnx dari notebook Colab) untuk dipakai auto-label."""
    get_project_or_404(db, project_id)
    try:
        model = register_onnx(db, storage, project_id, file.file, file.filename or "model.onnx",
                              name=name, dataset_version_id=dataset_version_id,
                              metrics={"map50": map50, "map50_95": map50_95}, notes=notes)  # fmt: skip
    except ModelRequestError as e:
        db.rollback()
        raise HTTPException(422, str(e))
    db.commit()
    return _out(db, model)


class ModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)
    dataset_version_id: int | None = None
    metrics: dict[str, float | None] | None = None
    class_map: dict[str, int | None] | None = None


@router.patch("/models/{model_id}", response_model=ModelOut)
def update_model(model_id: int, body: ModelUpdate, db: DbSession):
    model = _get_model(db, model_id)
    fields = body.model_fields_set
    try:
        if "dataset_version_id" in fields:
            check_version(db, model.project_id, body.dataset_version_id)
            model.dataset_version_id = body.dataset_version_id
        if body.class_map is not None:
            model.config = {**(model.config or {}), "class_map": validate_class_map(db, model, body.class_map)}
    except ModelRequestError as e:
        db.rollback()
        raise HTTPException(422, str(e))
    if body.name is not None:
        model.name = body.name.strip()
    if "notes" in fields:
        model.notes = body.notes
    if body.metrics is not None:
        merged = {**(model.metrics or {}), **body.metrics}
        model.metrics = {k: v for k, v in merged.items() if v is not None}
    db.commit()
    return _out(db, model)


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(model_id: int, db: DbSession, storage: Storage):
    """Hapus model dan file-nya. Box yang sudah dibuat model ini tetap ada."""
    model = _get_model(db, model_id)
    key = model.weights_key
    db.delete(model)
    db.commit()
    if key:
        storage.delete(key)
