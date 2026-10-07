from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from labelforge.api.deps import DbSession, Storage, get_project_or_404
from labelforge.models import Image
from labelforge.schemas.image import (
    ImageDetail,
    ImageFilters,
    ImageIds,
    ImageListItem,
    ImagePage,
    UploadResult,
)
from labelforge.services.image_query import list_images, neighbours
from labelforge.services.images import delete_image_files
from labelforge.services.upload import process_uploads

router = APIRouter(tags=["images"])
Filters = Annotated[ImageFilters, Depends()]
# Nama file di storage memakai UUID, jadi konten di URL yang sama tidak pernah berubah.
IMMUTABLE = {"Cache-Control": "private, max-age=31536000, immutable"}


def _get_image(db: DbSession, image_id: int) -> Image:
    image = db.get(Image, image_id)
    if image is None:
        raise HTTPException(404, f"Gambar {image_id} tidak ditemukan")
    return image


@router.post(
    "/projects/{project_id}/images",
    response_model=UploadResult,
    status_code=status.HTTP_201_CREATED,
)
def upload_images(
    project_id: int, db: DbSession, storage: Storage, files: Annotated[list[UploadFile], File()]
):
    """Upload satu/lebih gambar dan/atau ZIP berisi gambar."""
    get_project_or_404(db, project_id)
    return process_uploads(
        db, storage, project_id, [(f.filename or "upload", f.file) for f in files]
    )


@router.get("/projects/{project_id}/images", response_model=ImagePage)
def get_images(
    project_id: int,
    db: DbSession,
    filters: Filters,
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=500),
):
    get_project_or_404(db, project_id)
    items, total = list_images(db, project_id, filters, page, page_size)
    return ImagePage(
        items=[ImageListItem.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/images/{image_id}", response_model=ImageDetail)
def get_image(image_id: int, db: DbSession, filters: Filters):
    """Detail + anotasi + prev/next sesuai filter galeri (untuk navigasi editor)."""
    image = _get_image(db, image_id)
    detail = ImageDetail.model_validate(image)
    return detail.model_copy(update=neighbours(db, image, filters))


def _file_response(storage: Storage, key: str, media_type: str | None = None):
    path = storage.local_file_for_response(key)
    if path is not None:
        return FileResponse(path, media_type=media_type, headers=IMMUTABLE)
    if not storage.exists(key):
        raise HTTPException(404, "File tidak ditemukan di storage")
    return Response(storage.read_bytes(key), media_type=media_type, headers=IMMUTABLE)


@router.get("/images/{image_id}/file")
def get_image_file(image_id: int, db: DbSession, storage: Storage):
    return _file_response(storage, _get_image(db, image_id).storage_key)


@router.get("/images/{image_id}/thumb")
def get_image_thumb(image_id: int, db: DbSession, storage: Storage):
    return _file_response(storage, _get_image(db, image_id).thumb_key, "image/jpeg")


@router.delete("/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(image_id: int, db: DbSession, storage: Storage):
    image = _get_image(db, image_id)
    db.delete(image)
    db.commit()
    delete_image_files(storage, image)


@router.post("/projects/{project_id}/images/bulk-delete")
def bulk_delete_images(project_id: int, body: ImageIds, db: DbSession, storage: Storage):
    get_project_or_404(db, project_id)
    images = db.scalars(
        select(Image).where(Image.project_id == project_id, Image.id.in_(body.image_ids))
    ).all()
    for image in images:
        db.delete(image)
    db.commit()
    for image in images:
        delete_image_files(storage, image)
    return {"deleted": len(images)}
