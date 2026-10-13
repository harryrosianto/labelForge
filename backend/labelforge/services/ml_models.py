"""Registry model: upload ONNX hasil training, pemetaan class model → class project."""

import os
import shutil
import tempfile
import uuid
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from labelforge.models import DatasetVersion, LabelClass, MLModel
from labelforge.providers.onnx_yolo import OnnxModelError, read_model_info
from labelforge.storage import StorageBackend, project_prefix


class ModelRequestError(ValueError):
    pass


def default_class_map(names: list[str], classes: list[LabelClass]) -> dict[str, int | None]:
    """Petakan class model ke class project dengan nama sama (tanpa beda huruf besar/kecil)."""
    by_name = {c.name.strip().lower(): c.id for c in classes}
    return {str(i): by_name.get(n.strip().lower()) for i, n in enumerate(names)}


def validate_class_map(db: Session, model: MLModel, class_map: dict) -> dict[str, int | None]:
    names = (model.config or {}).get("names", [])
    valid = set(db.scalars(select(LabelClass.id).where(LabelClass.project_id == model.project_id)))
    out: dict[str, int | None] = {}
    for i in range(len(names)):
        value = class_map.get(str(i), class_map.get(i))
        if value is not None and value not in valid:
            raise ModelRequestError(f"Class {value} bukan milik project ini")
        out[str(i)] = value
    return out


def check_version(db: Session, project_id: int, version_id: int | None) -> None:
    if version_id is None:
        return
    version = db.get(DatasetVersion, version_id)
    if version is None or version.project_id != project_id:
        raise ModelRequestError("Versi dataset tidak ditemukan di project ini")


def register_onnx(
    db: Session,
    storage: StorageBackend,
    project_id: int,
    fileobj: BinaryIO,
    filename: str,
    *,
    name: str | None = None,
    dataset_version_id: int | None = None,
    metrics: dict | None = None,
    notes: str | None = None,
) -> MLModel:
    """Validasi & simpan model ONNX. Caller yang commit."""
    if not filename.lower().endswith(".onnx"):
        raise ModelRequestError("File model harus berformat .onnx (export dari Colab: format='onnx')")
    check_version(db, project_id, dataset_version_id)
    fd, tmp = tempfile.mkstemp(suffix=".onnx", prefix="labelforge-model-")
    try:
        with os.fdopen(fd, "wb") as out:
            shutil.copyfileobj(fileobj, out, length=1024 * 1024)
        try:
            info = read_model_info(tmp)
        except OnnxModelError as e:
            raise ModelRequestError(str(e)) from e
        key = f"{project_prefix(project_id)}/models/{uuid.uuid4().hex}.onnx"
        with open(tmp, "rb") as f:
            size = storage.save_file(key, f)
    finally:
        os.unlink(tmp)

    classes = list(db.scalars(select(LabelClass).where(LabelClass.project_id == project_id)))
    model = MLModel(
        project_id=project_id,
        dataset_version_id=dataset_version_id,
        name=(name or filename.rsplit(".", 1)[0]).strip()[:200] or "model",
        framework="onnx",
        weights_key=key,
        metrics={k: v for k, v in (metrics or {}).items() if v is not None},
        status="ready",
        notes=notes,
        config={**info.to_dict(), "size_bytes": size, "original_filename": filename,
                "class_map": default_class_map(info.names, classes)},  # fmt: skip
    )
    db.add(model)
    db.flush()
    return model
