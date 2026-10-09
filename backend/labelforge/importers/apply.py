"""Pemetaan class dan penerapan dataset hasil parsing ke project."""

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from labelforge.core.visualize import PALETTE
from labelforge.importers.base import ParsedDataset, Source
from labelforge.models import Annotation, Image, LabelClass
from labelforge.models.enums import ImageSource, ImageStatus
from labelforge.services.images import InvalidImageError, ingest_image
from labelforge.storage import StorageBackend



class ClassMapping(BaseModel):
    action: Literal["map", "create", "ignore"]
    class_id: int | None = None  # untuk "map"
    name: str | None = None  # untuk "create" (default: nama dari dataset)


class MappingError(ValueError):
    pass


def suggest_mapping(class_names: list[str], existing: list[LabelClass]) -> dict[str, dict]:
    """Class dengan nama sama (tanpa membedakan huruf besar/kecil) dipetakan; sisanya dibuat baru."""
    by_lower = {c.name.strip().lower(): c for c in existing}
    out = {}
    for name in class_names:
        match = by_lower.get(name.strip().lower())
        out[name] = (
            {"action": "map", "class_id": match.id}
            if match
            else {"action": "create", "name": name.strip()}
        )
    return out


def resolve_mapping(
    db: Session, project_id: int, class_names: list[str], mapping: dict[str, ClassMapping]
) -> tuple[dict[str, int | None], list[str]]:
    """Terapkan pemetaan: buat class baru bila perlu. Mengembalikan (nama → class_id/None, class dibuat).

    Caller yang commit.
    """
    missing = [n for n in class_names if n not in mapping]
    if missing:
        raise MappingError(f"Pemetaan belum lengkap untuk class: {', '.join(missing)}")

    classes = list(db.scalars(select(LabelClass).where(LabelClass.project_id == project_id)))
    by_id = {c.id: c for c in classes}
    by_lower = {c.name.lower(): c for c in classes}
    resolved: dict[str, int | None] = {}
    created: list[str] = []

    for name in class_names:
        m = mapping[name]
        if m.action == "ignore":
            resolved[name] = None
        elif m.action == "map":
            if m.class_id not in by_id:
                raise MappingError(f"Class tujuan untuk '{name}' bukan milik project ini")
            resolved[name] = m.class_id
        else:
            new_name = " ".join((m.name or name).split())
            if not new_name:
                raise MappingError(f"Nama class baru untuk '{name}' kosong")
            existing = by_lower.get(new_name.lower())
            if existing is None:
                order = len(by_id)
                existing = LabelClass(project_id=project_id, name=new_name, order_index=order,
                                      color=PALETTE[order % len(PALETTE)])  # fmt: skip
                db.add(existing)
                db.flush()
                by_id[existing.id] = existing
                by_lower[new_name.lower()] = existing
                created.append(new_name)
            resolved[name] = existing.id
    return resolved, created


ItemCallback = Callable[..., None]


def apply_import(
    session_factory: sessionmaker[Session],
    storage: StorageBackend,
    project_id: int,
    source: Source,
    parsed: ParsedDataset,
    class_ids: dict[str, int | None],
    *,
    mark_for_review: bool,
    source_label: str,
    import_id: int | None = None,
    on_item: ItemCallback | None = None,
    check_cancel: Callable[[], None] | None = None,
) -> dict:
    """Masukkan gambar + anotasi ke project. Gambar yang sudah ada (hash sama) dilewati."""
    annotation_source = f"import:{parsed.format}"
    status = ImageStatus.AUTO_LABELED if mark_for_review else ImageStatus.REVIEWED
    stats = {"imported": 0, "duplicates": 0, "failed": 0, "boxes": 0, "boxes_ignored": 0}

    for item in parsed.images:
        if check_cancel:
            check_cancel()
        with session_factory() as db:
            try:
                res = ingest_image(db, storage, project_id, item.path, source.read(item.path))
            except (InvalidImageError, KeyError, OSError) as e:
                db.rollback()
                stats["failed"] += 1
                if on_item:
                    on_item(label=item.path, error=str(e))
                continue
            if res.duplicate:
                db.rollback()
                stats["duplicates"] += 1
                if on_item:
                    on_item(label=item.path, image_id=res.image.id, count=0)
                continue

            image: Image = res.image
            image.source_type = ImageSource.IMPORT
            image.source_id = import_id
            image.source_label = source_label[:200]
            image.status = status
            added = 0
            for box in item.boxes:
                class_id = class_ids.get(box.class_name)
                if class_id is None:
                    stats["boxes_ignored"] += 1
                    continue
                x1, y1, x2, y2 = box.box
                db.add(Annotation(image_id=image.id, class_id=class_id, x_min=x1, y_min=y1,
                                  x_max=x2, y_max=y2, source=annotation_source,
                                  is_approved=not mark_for_review))  # fmt: skip
                added += 1
            db.commit()
            stats["imported"] += 1
            stats["boxes"] += added
            if on_item:
                on_item(label=item.path, image_id=image.id, count=added)
    return stats

