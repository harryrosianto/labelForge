from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from labelforge.api.deps import DbSession, get_project_or_404
from labelforge.models import DatasetVersion, LabelClass
from labelforge.schemas.image import ImageFilters
from labelforge.services.box_rows import load_images_and_boxes, version_rows
from labelforge.services.image_query import filtered_images
from labelforge.stats.dataset_stats import StatImage, compute_stats

router = APIRouter(tags=["stats"])


@router.get("/projects/{project_id}/stats/dataset")
def project_dataset_stats(project_id: int, db: DbSession, filters: Annotated[ImageFilters, Depends()]):
    """Statistik anotasi project (semua gambar, atau yang cocok dengan filter galeri)."""
    get_project_or_404(db, project_id)
    classes = list(db.scalars(
        select(LabelClass).where(LabelClass.project_id == project_id).order_by(LabelClass.order_index)
    ))  # fmt: skip
    index_of = {c.id: i for i, c in enumerate(classes)}
    images, boxes_of = load_images_and_boxes(db, filtered_images(project_id, filters))
    stat_images = [
        StatImage(w, h, [(index_of[cid], x1, y1, x2, y2)
                         for cid, x1, y1, x2, y2 in boxes_of.get(image_id, ()) if cid in index_of])
        for image_id, w, h in images
    ]  # fmt: skip
    return compute_stats([c.name for c in classes], stat_images)


@router.get("/versions/{version_id}/stats")
def version_stats(version_id: int, db: DbSession):
    version = db.get(DatasetVersion, version_id)
    if version is None:
        raise HTTPException(404, f"Versi {version_id} tidak ditemukan")
    stat_images = [StatImage(r.width, r.height, [tuple(b) for b in r.annotations])
                   for r in version_rows(db, version_id)]  # fmt: skip
    return compute_stats([c["name"] for c in version.config["classes"]], stat_images)
