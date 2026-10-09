"""Export dan perbandingan versi dataset."""

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from labelforge.exporters.base import (
    ExportBox,
    ExportDataset,
    ExportImage,
    ExportOptions,
    safe_stem,
)
from labelforge.exporters.split import SPLITS
from labelforge.models import DatasetVersion, Image, Project
from labelforge.services.box_rows import version_rows
from labelforge.versions.builder import file_extension, version_items


def version_dataset(db: Session, version: DatasetVersion, fmt: str) -> ExportDataset:
    """ExportDataset dari manifest versi (bukan dari data project yang bisa berubah)."""
    cfg = version.config
    items = version_items(db, version.id)
    originals = {
        img.id: img
        for img in db.scalars(select(Image).where(Image.id.in_({it.image_id for it in items})))
    }
    splits: dict[str, list[ExportImage]] = {s: [] for s in SPLITS}
    for it in items:
        src = originals[it.image_id]
        key = it.storage_key or src.storage_key
        suffix = "" if it.variant == 0 else f"_aug{it.variant}"
        splits[it.split].append(ExportImage(
            id=it.id,
            file_name=f"{it.image_id:06d}{suffix}_{safe_stem(src.original_filename)}{file_extension(key)}",
            storage_key=key, width=it.width, height=it.height,
            boxes=[ExportBox(int(b[0]), (b[1], b[2], b[3], b[4])) for b in it.annotations],
        ))  # fmt: skip
    return ExportDataset(
        project=db.get(Project, version.project_id),
        class_names=[c["name"] for c in cfg["classes"]],
        splits=splits,
        options=ExportOptions(format=fmt, reviewed_only=cfg["reviewed_only"], split=cfg["split"],
                              seed=cfg["seed"]),  # fmt: skip
        exported_at=version.created_at,
        extra_info={"version": {"id": version.id, "name": version.name, "notes": version.notes,
                                "preprocessing": cfg.get("preprocessing")}},  # fmt: skip
    )


def _manifest(db: Session, version: DatasetVersion) -> dict[tuple[int, int], tuple[str, list]]:
    names = [c["name"] for c in version.config["classes"]]
    return {
        (r.image_id, r.variant): (r.split, sorted((names[int(b[0])], *b[1:]) for b in r.annotations))
        for r in version_rows(db, version.id)
    }


def compare_versions(db: Session, a: DatasetVersion, b: DatasetVersion) -> dict:
    ma, mb = _manifest(db, a), _manifest(db, b)
    imgs_a = {k[0] for k in ma}
    imgs_b = {k[0] for k in mb}
    both = imgs_a & imgs_b
    originals = [k for k in ma if k[1] == 0 and k[0] in both]
    changed_labels = sum(1 for k in originals if (k in mb) and ma[k][1] != mb[k][1])
    split_moved = sum(1 for k in originals if (k in mb) and ma[k][0] != mb[k][0])

    def class_boxes(m):
        return Counter(box[0] for _, boxes in m.values() for box in boxes)

    ca, cb = class_boxes(ma), class_boxes(mb)
    settings_a = {k: v for k, v in a.config.items() if k != "classes"}
    settings_b = {k: v for k, v in b.config.items() if k != "classes"}
    return {
        "a": {"id": a.id, "name": a.name, "summary": a.summary},
        "b": {"id": b.id, "name": b.name, "summary": b.summary},
        "images_only_in_a": len(imgs_a - imgs_b),
        "images_only_in_b": len(imgs_b - imgs_a),
        "images_in_both": len(both),
        "labels_changed": changed_labels,
        "split_changed": split_moved,
        "per_class": [
            {"name": n, "a": ca.get(n, 0), "b": cb.get(n, 0)} for n in sorted(set(ca) | set(cb))
        ],
        "settings_changed": {
            k: {"a": settings_a.get(k), "b": settings_b.get(k)}
            for k in sorted(set(settings_a) | set(settings_b))
            if settings_a.get(k) != settings_b.get(k)
        },
    }
