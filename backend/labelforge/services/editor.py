"""Simpan hasil editor anotasi & buat exemplar dari box."""

import io
import uuid

from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.orm import Session

from labelforge.core.formats import clip_norm, is_valid_box, norm_to_xyxy_px
from labelforge.models import Annotation, ClassExemplar, Image, LabelClass
from labelforge.models.enums import SOURCE_MANUAL, ImageStatus
from labelforge.schemas.annotation import AnnotationSet
from labelforge.storage import StorageBackend, project_prefix

MIN_NORM_SIZE = 1e-4


class EditorError(ValueError):
    pass


def save_annotation_set(db: Session, image: Image, body: AnnotationSet) -> None:
    """Ganti seluruh anotasi gambar dengan set dari editor dalam satu transaksi.

    - Box dengan `id` yang ada → diperbarui (sumber & confidence asli dipertahankan).
    - Box tanpa `id` → anotasi manual baru.
    - Anotasi yang tidak dikirim → dihapus.
    - `approve=True` → semua box di-approve dan gambar menjadi `reviewed`.
    Caller yang commit.
    """
    valid_classes = set(
        db.scalars(select(LabelClass.id).where(LabelClass.project_id == image.project_id))
    )
    existing = {a.id: a for a in image.annotations}

    seen: set[int] = set()
    for item in body.annotations:
        if item.class_id not in valid_classes:
            raise EditorError(f"Class {item.class_id} bukan milik project ini")
        box = clip_norm((item.x_min, item.y_min, item.x_max, item.y_max))
        if not is_valid_box(box, MIN_NORM_SIZE):
            raise EditorError("Box terlalu kecil atau di luar gambar")
        approved = item.is_approved or body.approve

        if item.id is not None:
            ann = existing.get(item.id)
            if ann is None:
                raise EditorError(f"Anotasi {item.id} bukan milik gambar ini")
            if item.id in seen:
                raise EditorError(f"Anotasi {item.id} dikirim dua kali")
            seen.add(item.id)
            ann.class_id = item.class_id
            ann.x_min, ann.y_min, ann.x_max, ann.y_max = box
            ann.is_approved = approved
        else:
            db.add(
                Annotation(
                    image_id=image.id,
                    class_id=item.class_id,
                    x_min=box[0], y_min=box[1], x_max=box[2], y_max=box[3],
                    source=SOURCE_MANUAL,
                    is_approved=True,
                )
            )  # fmt: skip

    for ann_id, ann in existing.items():
        if ann_id not in seen:
            db.delete(ann)

    if body.approve:
        image.status = ImageStatus.REVIEWED


def create_exemplar(
    db: Session, storage: StorageBackend, annotation: Annotation
) -> ClassExemplar:
    """Crop box anotasi dari gambar asal menjadi contoh visual class. Caller yang commit."""
    image = annotation.image
    box = norm_to_xyxy_px(
        (annotation.x_min, annotation.y_min, annotation.x_max, annotation.y_max),
        image.width,
        image.height,
    )
    left, top = int(box[0]), int(box[1])
    right, bottom = max(left + 1, round(box[2])), max(top + 1, round(box[3]))
    if right - left < 8 or bottom - top < 8:
        raise EditorError("Box terlalu kecil untuk dijadikan contoh visual (minimal 8x8 px)")

    with storage.local_path(image.storage_key) as path, PILImage.open(path) as src:
        crop = src.convert("RGB").crop((left, top, right, bottom))
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    key = f"{project_prefix(image.project_id)}/exemplars/{uuid.uuid4().hex}.png"
    storage.save_bytes(key, buf.getvalue())

    exemplar = ClassExemplar(
        class_id=annotation.class_id,
        source_image_id=image.id,
        source_annotation_id=annotation.id,
        x_min=annotation.x_min, y_min=annotation.y_min,
        x_max=annotation.x_max, y_max=annotation.y_max,
        crop_storage_key=key,
        width=crop.width,
        height=crop.height,
    )  # fmt: skip
    db.add(exemplar)
    db.flush()
    return exemplar
