"""Pembuatan versi dataset (manifest) dan ringkasannya.

Manifest dibuat langsung saat versi dibuat (operasi DB saja), jadi snapshot tepat sesuai
kondisi project saat itu. File baru (preprocessing, augmentasi) dibuat oleh job worker.
"""

from collections import Counter
from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from labelforge.augment.pipeline import AugmentationConfig
from labelforge.exporters.split import SPLITS, split_ids
from labelforge.models import DatasetVersion, DatasetVersionItem, Image, LabelClass
from labelforge.models.enums import ImageStatus, VersionStatus
from labelforge.storage import project_prefix
from labelforge.versions.preprocess import Preprocessing, output_size, transform_box


class SplitRatio(BaseModel):
    train: float = Field(0.8, ge=0, le=1)
    val: float = Field(0.2, ge=0, le=1)
    test: float = Field(0.0, ge=0, le=1)

    @model_validator(mode="after")
    def _positive(self):
        if self.train <= 0:
            raise ValueError("Split train harus > 0")
        return self


class VersionSettings(BaseModel):
    """Pengaturan yang menentukan isi versi (disimpan di dataset_versions.config)."""

    reviewed_only: bool = True
    split: SplitRatio = SplitRatio()
    seed: int = 42
    preprocessing: Preprocessing = Preprocessing()
    augmentation: AugmentationConfig = AugmentationConfig()


class VersionCreate(VersionSettings):
    name: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Nama versi tidak boleh kosong")
        return v


def _project_classes(db: Session, project_id: int) -> list[LabelClass]:
    return list(db.scalars(
        select(LabelClass).where(LabelClass.project_id == project_id).order_by(LabelClass.order_index)
    ))  # fmt: skip


def _source_images(db: Session, project_id: int, reviewed_only: bool) -> list[Image]:
    statuses = [ImageStatus.REVIEWED] + ([] if reviewed_only else [ImageStatus.AUTO_LABELED])
    return list(db.scalars(
        select(Image)
        .where(Image.project_id == project_id, Image.status.in_(statuses))
        .options(selectinload(Image.annotations))
        .order_by(Image.id)
    ))  # fmt: skip


def plan_items(db: Session, project_id: int, settings: VersionSettings) -> tuple[list[LabelClass], list[dict]]:
    """Rencana item versi (belum ditulis ke DB): split, ukuran output, dan anotasi tertransformasi."""
    classes = _project_classes(db, project_id)
    index_of = {c.id: i for i, c in enumerate(classes)}
    images = _source_images(db, project_id, settings.reviewed_only)
    by_id = {img.id: img for img in images}
    assignment = split_ids(list(by_id), settings.split.model_dump(), settings.seed) if by_id else {}
    p = settings.preprocessing

    items = []
    for split in SPLITS:
        for image_id in assignment.get(split, []):
            img = by_id[image_id]
            boxes = [
                [index_of[a.class_id], *transform_box((a.x_min, a.y_min, a.x_max, a.y_max),
                                                      img.width, img.height, p)]
                for a in sorted(img.annotations, key=lambda a: a.id)
                if a.shape_type == "bbox" and a.class_id in index_of
            ]  # fmt: skip
            w, h = output_size(img.width, img.height, p)
            items.append({"image_id": image_id, "split": split, "variant": 0, "width": w,
                          "height": h, "annotations": boxes})  # fmt: skip
    return classes, items


def summarize(class_names: list[str], items: list[dict]) -> dict:
    boxes = Counter()
    images_per_class = Counter()
    for it in items:
        idx = [b[0] for b in it["annotations"]]
        boxes.update(idx)
        images_per_class.update(set(idx))
    splits = Counter(it["split"] for it in items)
    return {
        "images": len(items),
        "source_images": len({it["image_id"] for it in items}),
        "augmented": sum(1 for it in items if it["variant"] > 0),
        "annotations": sum(boxes.values()),
        "splits": {s: splits.get(s, 0) for s in SPLITS},
        "per_class": [
            {"name": n, "boxes": boxes.get(i, 0), "images": images_per_class.get(i, 0)}
            for i, n in enumerate(class_names)
        ],
        "empty_images": sum(1 for it in items if not it["annotations"]),
    }


def item_key(project_id: int, version_id: int, split: str, image_id: int, variant: int) -> str:
    return f"{project_prefix(project_id)}/versions/{version_id}/{split}/{image_id}_{variant}.jpg"


def create_version(db: Session, project_id: int, body: VersionCreate) -> tuple[DatasetVersion, bool]:
    """Buat versi + manifest. Mengembalikan (versi, perlu_job_build). Caller yang commit."""
    classes, items = plan_items(db, project_id, body)
    if not items:
        raise ValueError(
            "Belum ada gambar reviewed untuk dibuat versi" if body.reviewed_only
            else "Belum ada gambar berlabel untuk dibuat versi"
        )
    class_names = [c.name for c in classes]
    # File gambar asli perlu dibuat ulang hanya bila ada preprocessing; augmentasi selalu
    # menghasilkan file baru (dibuat job, item augmentasi ditambahkan oleh job).
    resize = body.preprocessing.active
    needs_files = resize or body.augmentation.enabled
    version = DatasetVersion(
        project_id=project_id,
        name=body.name,
        notes=body.notes,
        config={
            **body.model_dump(exclude={"name", "notes"}),
            "classes": [{"name": c.name, "color": c.color} for c in classes],
        },
        status=VersionStatus.BUILDING if needs_files else VersionStatus.READY,
        image_count=len(items),
        summary=summarize(class_names, items),
    )
    db.add(version)
    db.flush()
    for it in items:
        key = item_key(project_id, version.id, it["split"], it["image_id"], it["variant"]) if resize else None
        db.add(DatasetVersionItem(version_id=version.id, storage_key=key, **it))
    db.flush()
    return version, needs_files


def version_items(db: Session, version_id: int) -> list[DatasetVersionItem]:
    return list(db.scalars(
        select(DatasetVersionItem)
        .where(DatasetVersionItem.version_id == version_id)
        .order_by(DatasetVersionItem.id)
    ))  # fmt: skip


def file_extension(storage_key: str) -> str:
    return PurePosixPath(storage_key).suffix.lower() or ".jpg"


def planned_augmented(settings: VersionSettings, summary: dict) -> int:
    """Jumlah salinan augmentasi yang akan dibuat (hanya split train)."""
    aug = settings.augmentation
    return summary["splits"]["train"] * aug.multiplier if aug.enabled else 0
