from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from labelforge.api.deps import DbSession, Storage, get_class_or_404, get_project_or_404
from labelforge.models import Annotation, ClassExemplar, LabelClass
from labelforge.schemas.label_class import ClassCreate, ClassOrder, ClassOut, ClassUpdate

router = APIRouter(tags=["classes"])

# Palet default untuk class baru (kontras tinggi di atas foto gudang).
PALETTE = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231", "#911eb4", "#46f0f0",
    "#f032e6", "#bcf60c", "#fabebe", "#008080", "#e6beff", "#9a6324", "#800000",
]  # fmt: skip


def _project_classes(db: Session, project_id: int) -> list[LabelClass]:
    return list(
        db.scalars(
            select(LabelClass)
            .where(LabelClass.project_id == project_id)
            .order_by(LabelClass.order_index, LabelClass.id)
        )
    )


def _to_out(db: Session, classes: list[LabelClass]) -> list[ClassOut]:
    ids = [c.id for c in classes]
    if not ids:
        return []
    ann = dict(
        db.execute(
            select(Annotation.class_id, func.count())
            .where(Annotation.class_id.in_(ids))
            .group_by(Annotation.class_id)
        ).all()
    )
    ex = dict(
        db.execute(
            select(ClassExemplar.class_id, func.count())
            .where(ClassExemplar.class_id.in_(ids))
            .group_by(ClassExemplar.class_id)
        ).all()
    )
    return [
        ClassOut.model_validate(c).model_copy(
            update={"annotation_count": ann.get(c.id, 0), "exemplar_count": ex.get(c.id, 0)}
        )
        for c in classes
    ]


def _ensure_unique_name(db: Session, project_id: int, name: str, exclude_id: int | None = None):
    query = select(LabelClass.id).where(
        LabelClass.project_id == project_id, func.lower(LabelClass.name) == name.lower()
    )
    if exclude_id is not None:
        query = query.where(LabelClass.id != exclude_id)
    if db.scalar(query) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Class '{name}' sudah ada di project ini")


def _reindex(classes: list[LabelClass]) -> None:
    for i, c in enumerate(classes):
        c.order_index = i


@router.get("/projects/{project_id}/classes", response_model=list[ClassOut])
def list_classes(project_id: int, db: DbSession):
    get_project_or_404(db, project_id)
    return _to_out(db, _project_classes(db, project_id))


@router.post(
    "/projects/{project_id}/classes", response_model=ClassOut, status_code=status.HTTP_201_CREATED
)
def create_class(project_id: int, body: ClassCreate, db: DbSession):
    get_project_or_404(db, project_id)
    _ensure_unique_name(db, project_id, body.name)
    existing = _project_classes(db, project_id)
    label_class = LabelClass(
        project_id=project_id,
        name=body.name,
        color=body.color or PALETTE[len(existing) % len(PALETTE)],
        text_prompt=body.text_prompt,
        order_index=len(existing),
    )
    db.add(label_class)
    db.commit()
    return _to_out(db, [label_class])[0]


@router.patch("/classes/{class_id}", response_model=ClassOut)
def update_class(class_id: int, body: ClassUpdate, db: DbSession):
    label_class = get_class_or_404(db, class_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("name") is not None:
        _ensure_unique_name(db, label_class.project_id, data["name"], exclude_id=class_id)
        label_class.name = data["name"]
    if data.get("color") is not None:
        label_class.color = data["color"]
    if "text_prompt" in data:  # null = kembali ke default (nama class)
        label_class.text_prompt = data["text_prompt"]
    db.commit()
    return _to_out(db, [label_class])[0]


@router.delete("/classes/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_class(class_id: int, db: DbSession, storage: Storage):
    """Menghapus class beserta anotasi dan exemplar-nya; urutan class lain dirapatkan."""
    label_class = get_class_or_404(db, class_id)
    project_id = label_class.project_id
    crop_keys = list(
        db.scalars(select(ClassExemplar.crop_storage_key).where(ClassExemplar.class_id == class_id))
    )
    db.delete(label_class)
    db.flush()
    _reindex(_project_classes(db, project_id))
    db.commit()
    for key in crop_keys:
        storage.delete(key)


@router.put("/projects/{project_id}/classes/order", response_model=list[ClassOut])
def reorder_classes(project_id: int, body: ClassOrder, db: DbSession):
    get_project_or_404(db, project_id)
    classes = {c.id: c for c in _project_classes(db, project_id)}
    if sorted(body.class_ids) != sorted(classes):
        raise HTTPException(422, "class_ids harus berisi semua class project tepat satu kali")
    _reindex([classes[cid] for cid in body.class_ids])
    db.commit()
    return _to_out(db, _project_classes(db, project_id))
