"""Approve massal berdasarkan filter galeri dan audit sampel acak kualitas label."""

import hashlib
import json
import random
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session

from labelforge.models import Annotation, Image, ReviewAudit, ReviewAuditItem
from labelforge.models.enums import ImageStatus
from labelforge.schemas.image import ImageFilters
from labelforge.services.image_query import filtered_images

CHUNK = 500  # batas jumlah parameter per statement SQLite


def _chunks(ids: list[int]) -> Iterable[list[int]]:
    for i in range(0, len(ids), CHUNK):
        yield ids[i : i + CHUNK]


def _count(db: Session, query) -> int:
    return db.scalar(select(func.count()).select_from(query.subquery())) or 0


def _target_query(project_id: int, filters: ImageFilters, image_ids: list[int] | None):
    query = filtered_images(project_id, filters).with_only_columns(Image.id)
    if image_ids is not None:
        query = query.where(Image.id.in_(image_ids))
    return query


def bulk_set_status(
    db: Session,
    project_id: int,
    filters: ImageFilters,
    image_ids: list[int] | None,
    target: ImageStatus,
    dry_run: bool = False,
) -> dict:
    """Ubah status gambar auto-label → reviewed (approve) atau sebaliknya. Caller yang commit.

    Gambar unlabeled tidak pernah diubah: approve tanpa label akan membuatnya contoh negatif.
    """
    source = ImageStatus.AUTO_LABELED if target == ImageStatus.REVIEWED else ImageStatus.REVIEWED
    base = _target_query(project_id, filters, image_ids)
    changing = base.where(Image.status == source)
    no_boxes = changing.where(~exists(select(Annotation.id).where(Annotation.image_id == Image.id)))
    summary = {
        "matched": _count(db, base),
        "changed": _count(db, changing),
        "without_boxes": _count(db, no_boxes),
        "skipped_unlabeled": _count(db, base.where(Image.status == ImageStatus.UNLABELED)),
    }
    if dry_run or not summary["changed"]:
        return summary

    ids = list(db.scalars(changing.order_by(Image.id)))
    approved = target == ImageStatus.REVIEWED
    for chunk in _chunks(ids):
        db.execute(update(Annotation).where(Annotation.image_id.in_(chunk)).values(is_approved=approved))
        db.execute(update(Image).where(Image.id.in_(chunk)).values(status=target))
    return summary


# --- audit sampel ---------------------------------------------------------------


def label_fingerprints(db: Session, image_ids: list[int]) -> dict[int, str]:
    """Hash set box (id, class, koordinat) per gambar; berubah bila label dikoreksi di editor."""
    boxes: dict[int, list] = defaultdict(list)
    for chunk in _chunks(image_ids):
        rows = db.execute(select(
            Annotation.image_id, Annotation.id, Annotation.class_id,
            Annotation.x_min, Annotation.y_min, Annotation.x_max, Annotation.y_max,
        ).where(Annotation.image_id.in_(chunk)))  # fmt: skip
        for image_id, *box in rows:
            boxes[image_id].append([box[0], box[1], *(round(v, 5) for v in box[2:])])
    return {
        i: hashlib.sha1(json.dumps(sorted(boxes.get(i, []))).encode()).hexdigest()
        for i in image_ids
    }


def create_audit(
    db: Session, project_id: int, filters: ImageFilters, size: int, seed: int | None = None
) -> ReviewAudit:
    """Ambil sampel acak dari gambar auto-label dalam filter. Caller yang commit."""
    population = list(db.scalars(
        filtered_images(project_id, filters.model_copy(update={"audit_id": None}))
        .with_only_columns(Image.id)
        .where(Image.status == ImageStatus.AUTO_LABELED)
        .order_by(Image.id)
    ))  # fmt: skip
    if not population:
        raise ValueError("Tidak ada gambar berstatus auto-label dalam filter ini")
    seed = random.randrange(1_000_000) if seed is None else seed
    sample = sorted(random.Random(seed).sample(population, min(size, len(population))))

    stored = filters.model_dump(exclude_none=True)
    stored.pop("audit_id", None)
    audit = ReviewAudit(project_id=project_id, filters=stored, population=len(population),
                        sample_size=len(sample), seed=seed)  # fmt: skip
    db.add(audit)
    db.flush()
    db.add_all(ReviewAuditItem(audit_id=audit.id, image_id=i, fingerprint=fp)
               for i, fp in label_fingerprints(db, sample).items())  # fmt: skip
    db.flush()
    return audit


def audit_summary(db: Session, audit: ReviewAudit) -> dict:
    """Berapa gambar sampel sudah dicek, berapa yang labelnya dikoreksi, dan perkiraan error rate."""
    rows = db.execute(
        select(ReviewAuditItem.image_id, ReviewAuditItem.fingerprint, Image.status)
        .join(Image, Image.id == ReviewAuditItem.image_id)
        .where(ReviewAuditItem.audit_id == audit.id)
    ).all()
    current = label_fingerprints(db, [r.image_id for r in rows])
    corrected = approved = 0
    for image_id, fingerprint, status in rows:
        if current[image_id] != fingerprint:
            corrected += 1
        elif status == ImageStatus.REVIEWED:
            approved += 1
    checked = corrected + approved
    return {
        "checked": checked,
        "approved_unchanged": approved,
        "corrected": corrected,
        "pending": len(rows) - checked,
        "removed": audit.sample_size - len(rows),
        "error_rate": round(corrected / checked, 4) if checked else None,
    }
