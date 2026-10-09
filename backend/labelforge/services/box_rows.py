"""Muat ukuran gambar & box sebagai tuple ringan (tanpa objek ORM).

Statistik, pratinjau versi, dan pembuatan versi menyentuh semua anotasi project (bisa
ratusan ribu); membangun objek ORM untuk masing-masing jauh lebih lambat daripada membaca
kolom yang dibutuhkan saja.
"""

from collections import defaultdict

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from labelforge.models import Annotation, DatasetVersionItem, Image
from labelforge.models.enums import ShapeType

Box = tuple[int, float, float, float, float]  # (class_id, x_min, y_min, x_max, y_max)


def load_images_and_boxes(
    db: Session, images_query: Select
) -> tuple[list[tuple[int, int, int]], dict[int, list[Box]]]:
    """`images_query` = select(Image).where(...). Hasil: [(id, width, height)] urut id, dan
    {image_id: [box urut id anotasi]} (hanya bbox)."""
    id_query = images_query.with_only_columns(Image.id, Image.width, Image.height).order_by(Image.id)
    images = [tuple(r) for r in db.execute(id_query)]
    ids = images_query.with_only_columns(Image.id).order_by(None).subquery()
    rows = db.execute(
        select(Annotation.image_id, Annotation.class_id, Annotation.x_min, Annotation.y_min,
               Annotation.x_max, Annotation.y_max)
        .where(Annotation.image_id.in_(select(ids.c.id)), Annotation.shape_type == ShapeType.BBOX)
        .order_by(Annotation.image_id, Annotation.id)
    )  # fmt: skip
    boxes: dict[int, list[Box]] = defaultdict(list)
    for image_id, class_id, x1, y1, x2, y2 in rows:
        boxes[image_id].append((class_id, x1, y1, x2, y2))
    return images, boxes


def version_rows(db: Session, version_id: int) -> list:
    """Item versi sebagai baris ringan: image_id, split, variant, width, height, annotations, storage_key."""
    return list(db.execute(
        select(DatasetVersionItem.image_id, DatasetVersionItem.split, DatasetVersionItem.variant,
               DatasetVersionItem.width, DatasetVersionItem.height, DatasetVersionItem.annotations,
               DatasetVersionItem.storage_key)
        .where(DatasetVersionItem.version_id == version_id)
        .order_by(DatasetVersionItem.id)
    ))  # fmt: skip
