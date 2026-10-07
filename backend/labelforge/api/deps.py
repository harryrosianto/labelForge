from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from labelforge.db import get_db
from labelforge.models import LabelClass, Project
from labelforge.storage import StorageBackend, get_storage

DbSession = Annotated[Session, Depends(get_db)]
Storage = Annotated[StorageBackend, Depends(get_storage)]


def get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, f"Project {project_id} tidak ditemukan")
    return project


def get_class_or_404(db: Session, class_id: int) -> LabelClass:
    label_class = db.get(LabelClass, class_id)
    if label_class is None:
        raise HTTPException(404, f"Class {class_id} tidak ditemukan")
    return label_class
