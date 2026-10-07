from fastapi import APIRouter, status
from sqlalchemy import func, select

from labelforge.api.deps import DbSession, Storage, get_project_or_404
from labelforge.models import Annotation, Image, LabelClass, Project
from labelforge.models.enums import ImageStatus
from labelforge.schemas.project import (
    ClassCount,
    ProjectCreate,
    ProjectOut,
    ProjectStats,
    ProjectUpdate,
)
from labelforge.storage import project_prefix

router = APIRouter(prefix="/projects", tags=["projects"])


def _counts(db: DbSession, model, project_ids: list[int]) -> dict[int, int]:
    if not project_ids:
        return {}
    rows = db.execute(
        select(model.project_id, func.count())
        .where(model.project_id.in_(project_ids))
        .group_by(model.project_id)
    )
    return dict(rows.all())


def _to_out(db: DbSession, projects: list[Project]) -> list[ProjectOut]:
    ids = [p.id for p in projects]
    images = _counts(db, Image, ids)
    classes = _counts(db, LabelClass, ids)
    return [
        ProjectOut.model_validate(p).model_copy(
            update={"image_count": images.get(p.id, 0), "class_count": classes.get(p.id, 0)}
        )
        for p in projects
    ]


@router.get("", response_model=list[ProjectOut])
def list_projects(db: DbSession):
    projects = db.scalars(select(Project).order_by(Project.updated_at.desc())).all()
    return _to_out(db, list(projects))


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, db: DbSession):
    project = Project(**body.model_dump())
    db.add(project)
    db.commit()
    return _to_out(db, [project])[0]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: DbSession):
    return _to_out(db, [get_project_or_404(db, project_id)])[0]


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, body: ProjectUpdate, db: DbSession):
    project = get_project_or_404(db, project_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "name" and value is None:
            continue
        setattr(project, key, value)
    db.commit()
    return _to_out(db, [project])[0]


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: DbSession, storage: Storage):
    project = get_project_or_404(db, project_id)
    db.delete(project)
    db.commit()
    storage.delete_prefix(project_prefix(project_id))


@router.get("/{project_id}/stats", response_model=ProjectStats)
def project_stats(project_id: int, db: DbSession):
    get_project_or_404(db, project_id)

    by_status = {s.value: 0 for s in ImageStatus}
    by_status.update(
        db.execute(
            select(Image.status, func.count())
            .where(Image.project_id == project_id)
            .group_by(Image.status)
        ).all()
    )

    ann_base = select(Annotation).join(Image).where(Image.project_id == project_id).subquery()
    by_class_rows = db.execute(
        select(LabelClass.id, LabelClass.name, LabelClass.color, func.count(ann_base.c.id))
        .outerjoin(ann_base, ann_base.c.class_id == LabelClass.id)
        .where(LabelClass.project_id == project_id)
        .group_by(LabelClass.id)
        .order_by(LabelClass.order_index)
    ).all()
    by_source = dict(
        db.execute(select(ann_base.c.source, func.count()).group_by(ann_base.c.source)).all()
    )
    unapproved = db.scalar(
        select(func.count()).select_from(ann_base).where(ann_base.c.is_approved.is_(False))
    )

    return ProjectStats(
        total_images=sum(by_status.values()),
        total_annotations=sum(by_source.values()),
        images_by_status=by_status,
        annotations_by_class=[
            ClassCount(class_id=cid, name=name, color=color, annotations=n)
            for cid, name, color, n in by_class_rows
        ],
        annotations_by_source=by_source,
        unapproved_annotations=unapproved or 0,
    )
