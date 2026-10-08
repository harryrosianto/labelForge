from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from labelforge.api.deps import DbSession, get_project_or_404
from labelforge.models import DatasetVersion, Image, LabelClass
from labelforge.schemas.image import ImageFilters
from labelforge.services.image_query import filtered_images
from labelforge.stats.dataset_stats import StatImage, compute_stats
from labelforge.versions.builder import version_items

router = APIRouter(tags=["stats"])


@router.get("/projects/{project_id}/stats/dataset")
def project_dataset_stats(project_id: int, db: DbSession, filters: Annotated[ImageFilters, Depends()]):
    """Statistik anotasi project (semua gambar, atau yang cocok dengan filter galeri)."""
    get_project_or_404(db, project_id)
    classes = list(db.scalars(
        select(LabelClass).where(LabelClass.project_id == project_id).order_by(LabelClass.order_index)
    ))  # fmt: skip
    index_of = {c.id: i for i, c in enumerate(classes)}
    images = db.scalars(filtered_images(project_id, filters).options(selectinload(Image.annotations)))
    stat_images = [
        StatImage(img.width, img.height, [
            (index_of[a.class_id], a.x_min, a.y_min, a.x_max, a.y_max)
            for a in img.annotations if a.shape_type == "bbox" and a.class_id in index_of
        ])  # fmt: skip
        for img in images
    ]
    return compute_stats([c.name for c in classes], stat_images)


@router.get("/versions/{version_id}/stats")
def version_stats(version_id: int, db: DbSession):
    version = db.get(DatasetVersion, version_id)
    if version is None:
        raise HTTPException(404, f"Versi {version_id} tidak ditemukan")
    stat_images = [
        StatImage(it.width, it.height, [tuple(b) for b in it.annotations])
        for it in version_items(db, version_id)
    ]
    return compute_stats([c["name"] for c in version.config["classes"]], stat_images)
