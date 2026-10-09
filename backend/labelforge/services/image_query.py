"""Query galeri dengan filter yang sama untuk listing dan navigasi prev/next editor."""

from sqlalchemy import Select, exists, func, select
from sqlalchemy.orm import Session, selectinload

from labelforge.models import Annotation, Image
from labelforge.schemas.image import ImageFilters


def filtered_images(project_id: int, f: ImageFilters) -> Select:
    query = select(Image).where(Image.project_id == project_id)
    if f.status:
        query = query.where(Image.status == f.status)
    if f.source_type:
        query = query.where(Image.source_type == f.source_type)

    ann = select(Annotation.id).where(Annotation.image_id == Image.id)
    if f.class_id is not None:
        query = query.where(exists(ann.where(Annotation.class_id == f.class_id)))
    if f.source:
        if f.source == "ai":
            cond = Annotation.source.startswith("ai:")
        else:
            cond = Annotation.source == f.source
        query = query.where(exists(ann.where(cond)))
    if f.max_conf is not None:
        query = query.where(
            exists(
                ann.where(
                    Annotation.is_approved.is_(False),
                    Annotation.confidence.is_not(None),
                    Annotation.confidence < f.max_conf,
                )
            )
        )
    return query


def list_images(
    db: Session, project_id: int, f: ImageFilters, page: int, page_size: int
) -> tuple[list[Image], int]:
    base = filtered_images(project_id, f)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = db.scalars(
        base.options(selectinload(Image.annotations))
        .order_by(Image.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(items), total


def neighbours(db: Session, image: Image, f: ImageFilters) -> dict:
    """prev/next id dan posisi gambar dalam filter aktif (urut id)."""
    base = filtered_images(image.project_id, f).subquery()
    prev_id = db.scalar(select(func.max(base.c.id)).where(base.c.id < image.id))
    next_id = db.scalar(select(func.min(base.c.id)).where(base.c.id > image.id))
    total = db.scalar(select(func.count()).select_from(base)) or 0
    in_filter = db.scalar(select(func.count()).select_from(base).where(base.c.id == image.id))
    position = (
        db.scalar(select(func.count()).select_from(base).where(base.c.id <= image.id))
        if in_filter
        else None
    )
    return {"prev_id": prev_id, "next_id": next_id, "position": position, "filtered_total": total}
