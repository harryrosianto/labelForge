from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from labelforge.api.deps import DbSession, get_project_or_404
from labelforge.models import ReviewAudit
from labelforge.models.enums import ImageStatus
from labelforge.schemas.image import ImageFilters
from labelforge.services.review import audit_summary, bulk_set_status, create_audit

router = APIRouter(tags=["review"])


class BulkStatusRequest(BaseModel):
    status: Literal["reviewed", "auto_labeled"]
    filters: ImageFilters = ImageFilters()
    image_ids: list[int] | None = Field(default=None, description="Batasi ke gambar terpilih")
    dry_run: bool = False


@router.post("/projects/{project_id}/images/bulk-status")
def bulk_status(project_id: int, body: BulkStatusRequest, db: DbSession):
    """Approve (auto-label → reviewed) atau kembalikan ke perlu review untuk semua hasil filter.

    `dry_run=true` hanya menghitung, untuk ditampilkan di dialog konfirmasi.
    """
    get_project_or_404(db, project_id)
    result = bulk_set_status(db, project_id, body.filters, body.image_ids,
                             ImageStatus(body.status), body.dry_run)  # fmt: skip
    db.commit()
    return result


class AuditCreate(BaseModel):
    filters: ImageFilters = ImageFilters()
    size: int = Field(200, ge=1, le=2000)
    seed: int | None = None


class AuditOut(BaseModel):
    id: int
    project_id: int
    filters: dict
    population: int
    sample_size: int
    seed: int
    created_at: datetime
    summary: dict


def _out(db: DbSession, audit: ReviewAudit) -> AuditOut:
    return AuditOut(id=audit.id, project_id=audit.project_id, filters=audit.filters,
                    population=audit.population, sample_size=audit.sample_size, seed=audit.seed,
                    created_at=audit.created_at, summary=audit_summary(db, audit))  # fmt: skip


def _get_audit(db: DbSession, audit_id: int) -> ReviewAudit:
    audit = db.get(ReviewAudit, audit_id)
    if audit is None:
        raise HTTPException(404, f"Audit {audit_id} tidak ditemukan")
    return audit


@router.post("/projects/{project_id}/audits", response_model=AuditOut, status_code=status.HTTP_201_CREATED)
def start_audit(project_id: int, body: AuditCreate, db: DbSession):
    """Ambil sampel acak gambar auto-label dari filter untuk diperiksa di editor (?audit_id=)."""
    get_project_or_404(db, project_id)
    try:
        audit = create_audit(db, project_id, body.filters, body.size, body.seed)
    except ValueError as e:
        db.rollback()
        raise HTTPException(422, str(e))
    db.commit()
    return _out(db, audit)


@router.get("/projects/{project_id}/audits", response_model=list[AuditOut])
def list_audits(project_id: int, db: DbSession):
    get_project_or_404(db, project_id)
    audits = db.scalars(select(ReviewAudit).where(ReviewAudit.project_id == project_id)
                        .order_by(ReviewAudit.id.desc()).limit(20))  # fmt: skip
    return [_out(db, a) for a in audits]


@router.get("/audits/{audit_id}", response_model=AuditOut)
def get_audit(audit_id: int, db: DbSession):
    return _out(db, _get_audit(db, audit_id))


@router.delete("/audits/{audit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_audit(audit_id: int, db: DbSession):
    """Hapus catatan audit saja; label dan status gambar tidak berubah."""
    db.delete(_get_audit(db, audit_id))
    db.commit()
