from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select

from labelforge.api.deps import DbSession, Storage, get_class_or_404
from labelforge.models import Annotation, ClassExemplar, Image
from labelforge.models.enums import ImageStatus
from labelforge.schemas.annotation import AnnotationSet, ExemplarOut
from labelforge.schemas.image import ImageListItem
from labelforge.services.editor import EditorError, create_exemplar, save_annotation_set

router = APIRouter(tags=["annotations"])


def _get_image(db: DbSession, image_id: int) -> Image:
    image = db.get(Image, image_id)
    if image is None:
        raise HTTPException(404, f"Gambar {image_id} tidak ditemukan")
    return image


@router.put("/images/{image_id}/annotations", response_model=ImageListItem)
def save_annotations(image_id: int, body: AnnotationSet, db: DbSession):
    """Simpan seluruh set box dari editor (satu transaksi). `approve=true` sekaligus approve."""
    image = _get_image(db, image_id)
    try:
        save_annotation_set(db, image, body)
    except EditorError as e:
        db.rollback()
        raise HTTPException(422, str(e))
    db.commit()
    db.refresh(image)
    return image


@router.post("/images/{image_id}/approve", response_model=ImageListItem)
def approve_image(image_id: int, db: DbSession):
    image = _get_image(db, image_id)
    for ann in image.annotations:
        ann.is_approved = True
    image.status = ImageStatus.REVIEWED
    db.commit()
    db.refresh(image)
    return image


# --- exemplars --------------------------------------------------------------


@router.post(
    "/annotations/{annotation_id}/exemplar",
    response_model=ExemplarOut,
    status_code=status.HTTP_201_CREATED,
)
def make_exemplar(annotation_id: int, db: DbSession, storage: Storage):
    """Jadikan box sebagai contoh visual untuk class-nya (mode image-guided OWLv2)."""
    annotation = db.get(Annotation, annotation_id)
    if annotation is None:
        raise HTTPException(404, f"Anotasi {annotation_id} tidak ditemukan")
    try:
        exemplar = create_exemplar(db, storage, annotation)
    except EditorError as e:
        db.rollback()
        raise HTTPException(422, str(e))
    db.commit()
    return exemplar


@router.get("/classes/{class_id}/exemplars", response_model=list[ExemplarOut])
def list_exemplars(class_id: int, db: DbSession):
    get_class_or_404(db, class_id)
    return db.scalars(
        select(ClassExemplar).where(ClassExemplar.class_id == class_id).order_by(ClassExemplar.id)
    ).all()


def _get_exemplar(db: DbSession, exemplar_id: int) -> ClassExemplar:
    exemplar = db.get(ClassExemplar, exemplar_id)
    if exemplar is None:
        raise HTTPException(404, f"Exemplar {exemplar_id} tidak ditemukan")
    return exemplar


@router.get("/exemplars/{exemplar_id}/image")
def exemplar_image(exemplar_id: int, db: DbSession, storage: Storage):
    key = _get_exemplar(db, exemplar_id).crop_storage_key
    path = storage.local_file_for_response(key)
    if path is not None:
        return FileResponse(path, media_type="image/png")
    return Response(storage.read_bytes(key), media_type="image/png")


@router.delete("/exemplars/{exemplar_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_exemplar(exemplar_id: int, db: DbSession, storage: Storage):
    exemplar = _get_exemplar(db, exemplar_id)
    key = exemplar.crop_storage_key
    db.delete(exemplar)
    db.commit()
    storage.delete(key)
