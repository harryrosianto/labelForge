"""Pembuatan versi dataset (manifest) dan ringkasannya.

Manifest dibuat langsung saat versi dibuat (operasi DB saja), jadi snapshot tepat sesuai
kondisi project saat itu. File baru (preprocessing, augmentasi) dibuat oleh job worker.
"""

from collections import Counter
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Select, insert, select
from sqlalchemy.orm import Session

from labelforge.augment.pipeline import AugmentationConfig
from labelforge.exporters.split import SPLITS, split_groups, split_ids
from labelforge.models import DatasetVersion, DatasetVersionItem, Image, LabelClass
from labelforge.models.base import utcnow
from labelforge.models.enums import ImageStatus, VersionStatus
from labelforge.services.box_rows import load_images_and_boxes
from labelforge.storage import project_prefix
from labelforge.versions.segments import ImageMeta, frame_key, segment_groups
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
    # random = acak per gambar; segment = per segmen waktu per sumber (lihat versions.segments)
    split_mode: Literal["random", "segment"] = "random"
    segment_size: int = Field(50, ge=1, le=100_000)
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


def _assign_splits(
    db: Session, images_query: Select, ids: list[int], settings: VersionSettings
) -> tuple[dict[str, list[int]], dict | None]:
    ratios = settings.split.model_dump()
    if settings.split_mode == "random":
        return split_ids(ids, ratios, settings.seed), None
    metas = [ImageMeta(*row) for row in db.execute(images_query.with_only_columns(
        Image.id, Image.source_type, Image.source_id, Image.original_filename,
        Image.frame_time_s, Image.captured_at,
    ))]  # fmt: skip
    groups, strata = segment_groups(metas, settings.segment_size)
    info = {"mode": "segment", "segment_size": settings.segment_size, "groups": len(groups),
            "sources": len(set(strata)), "frames": len({frame_key(m)[2] for m in metas})}  # fmt: skip
    return split_groups(groups, strata, ratios, settings.seed), info


def plan(db: Session, project_id: int, settings: VersionSettings) -> tuple[list[LabelClass], list[dict], dict | None]:
    """Seperti `plan_items`, ditambah ringkasan pengelompokan split (None untuk mode acak)."""
    classes = _project_classes(db, project_id)
    index_of = {c.id: i for i, c in enumerate(classes)}
    statuses = [ImageStatus.REVIEWED] + ([] if settings.reviewed_only else [ImageStatus.AUTO_LABELED])
    images_query = select(Image).where(Image.project_id == project_id, Image.status.in_(statuses))
    images, boxes_of = load_images_and_boxes(db, images_query)
    size_of = {image_id: (w, h) for image_id, w, h in images}
    assignment, split_info = (
        _assign_splits(db, images_query, list(size_of), settings) if size_of else ({}, None)
    )
    p = settings.preprocessing

    items = []
    for split in SPLITS:
        for image_id in assignment.get(split, []):
            src_w, src_h = size_of[image_id]
            boxes = [
                [index_of[cid], *transform_box((x1, y1, x2, y2), src_w, src_h, p)]
                for cid, x1, y1, x2, y2 in boxes_of.get(image_id, ())
                if cid in index_of
            ]
            w, h = output_size(src_w, src_h, p)
            items.append({"image_id": image_id, "split": split, "variant": 0, "width": w,
                          "height": h, "annotations": boxes})  # fmt: skip
    return classes, items, split_info


def plan_items(db: Session, project_id: int, settings: VersionSettings) -> tuple[list[LabelClass], list[dict]]:
    """Rencana item versi (belum ditulis ke DB): split, ukuran output, dan anotasi tertransformasi."""
    classes, items, _ = plan(db, project_id, settings)
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
    classes, items, split_info = plan(db, project_id, body)
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
        summary={**summarize(class_names, items), "split_groups": split_info},
    )
    db.add(version)
    db.flush()
    # Bulk insert: manifest bisa berisi puluhan ribu baris.
    now = utcnow()
    db.execute(insert(DatasetVersionItem), [
        {**it, "version_id": version.id, "created_at": now,
         "storage_key": item_key(project_id, version.id, it["split"], it["image_id"], it["variant"]) if resize else None}
        for it in items
    ])  # fmt: skip
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
