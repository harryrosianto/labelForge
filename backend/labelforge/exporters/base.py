"""Kumpulkan data project menjadi struktur netral sebelum ditulis ke format tertentu."""

import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from labelforge.exporters.split import SPLITS, split_ids
from labelforge.models import Image, LabelClass, Project
from labelforge.models.enums import ImageStatus


@dataclass
class ExportBox:
    class_index: int  # 0-based, urut order_index class
    box: tuple[float, float, float, float]  # xyxy ternormalisasi


@dataclass
class ExportImage:
    id: int
    file_name: str  # nama unik di dalam export
    storage_key: str
    width: int
    height: int
    boxes: list[ExportBox] = field(default_factory=list)


@dataclass
class ExportOptions:
    format: str = "yolo"
    reviewed_only: bool = True
    split: dict[str, float] = field(default_factory=lambda: {"train": 0.8, "val": 0.2, "test": 0.0})
    seed: int = 42


@dataclass
class ExportDataset:
    project: Project
    class_names: list[str]
    splits: dict[str, list[ExportImage]]
    options: ExportOptions
    # Diisi untuk export dari versi: waktu tetap (ZIP identik setiap unduhan) + info versi.
    exported_at: datetime | None = None
    extra_info: dict | None = None

    @property
    def num_images(self) -> int:
        return sum(len(v) for v in self.splits.values())

    def summary(self) -> dict:
        per_class = [0] * len(self.class_names)
        for images in self.splits.values():
            for img in images:
                for b in img.boxes:
                    per_class[b.class_index] += 1
        return {
            "images": self.num_images,
            "annotations": sum(per_class),
            "splits": {s: len(self.splits[s]) for s in SPLITS},
            "per_class": dict(zip(self.class_names, per_class)),
            "empty_images": sum(1 for v in self.splits.values() for i in v if not i.boxes),
        }


def safe_stem(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", PurePosixPath(name).stem).strip("._")
    return stem[:80] or "image"


def collect_dataset(db: Session, project_id: int, options: ExportOptions) -> ExportDataset:
    """Gambar yang diekspor:
    - reviewed_only=True : hanya `reviewed` (semua box-nya sudah di-approve).
    - reviewed_only=False: `reviewed` + `auto_labeled` (box AI ikut apa adanya).
    Gambar `unlabeled` tidak pernah diekspor: tanpa label ia akan terbaca sebagai gambar
    tanpa objek dan merusak dataset.
    """
    project = db.get(Project, project_id)
    classes = db.scalars(
        select(LabelClass).where(LabelClass.project_id == project_id).order_by(LabelClass.order_index)
    ).all()
    index_of = {c.id: i for i, c in enumerate(classes)}

    statuses = [ImageStatus.REVIEWED]
    if not options.reviewed_only:
        statuses.append(ImageStatus.AUTO_LABELED)
    images = db.scalars(
        select(Image)
        .where(Image.project_id == project_id, Image.status.in_(statuses))
        .options(selectinload(Image.annotations))
        .order_by(Image.id)
    ).all()

    by_id: dict[int, ExportImage] = {}
    for img in images:
        ext = PurePosixPath(img.storage_key).suffix.lower() or ".jpg"
        boxes = [
            ExportBox(index_of[a.class_id], (a.x_min, a.y_min, a.x_max, a.y_max))
            for a in sorted(img.annotations, key=lambda a: a.id)
            if a.shape_type == "bbox" and a.class_id in index_of
        ]
        by_id[img.id] = ExportImage(
            id=img.id,
            file_name=f"{img.id:06d}_{safe_stem(img.original_filename)}{ext}",
            storage_key=img.storage_key,
            width=img.width,
            height=img.height,
            boxes=boxes,
        )

    assignment = split_ids(list(by_id), options.split, options.seed) if by_id else {s: [] for s in SPLITS}
    return ExportDataset(
        project=project,
        class_names=[c.name for c in classes],
        splits={s: [by_id[i] for i in assignment[s]] for s in SPLITS},
        options=options,
    )


def export_info(dataset: ExportDataset) -> dict:
    return {
        "project": dataset.project.name,
        "exported_at": (dataset.exported_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "format": dataset.options.format,
        "reviewed_only": dataset.options.reviewed_only,
        "split_ratio": dataset.options.split,
        "seed": dataset.options.seed,
        "classes": dataset.class_names,
        **dataset.summary(),
        **(dataset.extra_info or {}),
    }


# Tanggal tetap untuk semua entri ZIP agar isi export yang sama menghasilkan file identik.
ZIP_DATE = (2020, 1, 1, 0, 0, 0)


def write_text(zf: zipfile.ZipFile, path: str, text: str) -> None:
    zf.writestr(zipfile.ZipInfo(path, date_time=ZIP_DATE), text, compress_type=zipfile.ZIP_DEFLATED)


def write_bytes(zf: zipfile.ZipFile, path: str, data: bytes) -> None:
    """Gambar sudah terkompresi (JPEG/PNG), jadi disimpan tanpa kompresi ulang."""
    zf.writestr(zipfile.ZipInfo(path, date_time=ZIP_DATE), data, compress_type=zipfile.ZIP_STORED)
