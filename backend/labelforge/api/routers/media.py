import base64
import uuid
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from labelforge.api.deps import DbSession, Storage, get_project_or_404
from labelforge.api.routers.jobs import Queue
from labelforge.media.rtsp import CameraError, CaptureOptions, grab_one
from labelforge.media.secrets import SecretKeyError, decrypt_url, encrypt_url, mask_url, scrub
from labelforge.media.video import (
    VIDEO_EXTS,
    ExtractOptions,
    VideoInfo,
    VideoReadError,
    probe,
    sample_times,
)
from labelforge.models import CameraSource, LabelingJob, Video
from labelforge.models.enums import JobStatus, JobType
from labelforge.schemas.job import JobOut
from labelforge.services.job_runner import create_job
from labelforge.storage import project_prefix
from labelforge.versions.samples import encode_jpeg

router = APIRouter(tags=["media"])


def _enqueue(db: DbSession, queue: Queue, job: LabelingJob) -> LabelingJob:
    db.commit()
    try:
        job.celery_task_id = queue.enqueue(job.job_type, job.id)
    except Exception as e:
        job.status, job.error = JobStatus.FAILED, f"Gagal mengirim job ke antrian: {e}"
    db.commit()
    db.refresh(job)
    return job


# --- video --------------------------------------------------------------------


class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    original_filename: str
    duration_s: float | None
    fps: float | None
    frame_count: int | None
    width: int | None
    height: int | None
    created_at: datetime


def _get_video(db: DbSession, video_id: int) -> Video:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, f"Video {video_id} tidak ditemukan")
    return video


@router.post("/projects/{project_id}/videos", response_model=VideoOut, status_code=status.HTTP_201_CREATED)
def upload_video(project_id: int, db: DbSession, storage: Storage, file: Annotated[UploadFile, File()]):
    get_project_or_404(db, project_id)
    name = PurePosixPath(file.filename or "video.mp4").name
    ext = PurePosixPath(name).suffix.lower()
    if ext not in VIDEO_EXTS:
        raise HTTPException(422, f"Format video tidak didukung. Didukung: {', '.join(sorted(VIDEO_EXTS))}")
    key = f"{project_prefix(project_id)}/videos/{uuid.uuid4().hex}{ext}"
    storage.save_file(key, file.file)
    try:
        with storage.local_path(key) as path:
            info = probe(str(path))
    except VideoReadError as e:
        storage.delete(key)
        raise HTTPException(422, str(e))
    video = Video(project_id=project_id, original_filename=name, storage_key=key, duration_s=info.duration_s,
                  fps=info.fps, frame_count=info.frame_count, width=info.width, height=info.height)  # fmt: skip
    db.add(video)
    db.commit()
    return video


@router.get("/projects/{project_id}/videos", response_model=list[VideoOut])
def list_videos(project_id: int, db: DbSession):
    get_project_or_404(db, project_id)
    return db.scalars(select(Video).where(Video.project_id == project_id).order_by(Video.id.desc())).all()


@router.delete("/videos/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video(video_id: int, db: DbSession, storage: Storage):
    """Hapus file video. Frame yang sudah diekstrak tetap ada sebagai gambar project."""
    video = _get_video(db, video_id)
    key = video.storage_key
    db.delete(video)
    db.commit()
    storage.delete(key)


@router.post("/videos/{video_id}/extract/preview")
def preview_extract(video_id: int, body: ExtractOptions, db: DbSession):
    """Jumlah frame yang akan diambil (sebelum frame mirip dilewati)."""
    video = _get_video(db, video_id)
    info = VideoInfo(video.duration_s, video.fps, video.frame_count, video.width, video.height)
    return {"frames": len(sample_times(info, body))}


@router.post("/videos/{video_id}/extract", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def extract_frames(video_id: int, body: ExtractOptions, db: DbSession, queue: Queue):
    video = _get_video(db, video_id)
    job = create_job(db, video.project_id, JobType.VIDEO_EXTRACT,
                     {"video_id": video.id, "video": video.original_filename, "options": body.model_dump()})  # fmt: skip
    return _enqueue(db, queue, job)


# --- kamera RTSP --------------------------------------------------------------


class CameraIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=8, max_length=2000)

    @field_validator("url")
    @classmethod
    def _scheme(cls, v: str) -> str:
        v = v.strip()
        if not v.lower().startswith(("rtsp://", "rtsps://", "http://", "https://")):
            raise ValueError("URL harus diawali rtsp://, rtsps://, http:// atau https://")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Nama kamera tidak boleh kosong")
        return v


class CameraOut(BaseModel):
    """URL hanya dikirim dalam bentuk tersamarkan; versi terenkripsi tidak pernah keluar dari server."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    url_masked: str
    created_at: datetime


def _get_camera(db: DbSession, camera_id: int) -> CameraSource:
    camera = db.get(CameraSource, camera_id)
    if camera is None:
        raise HTTPException(404, f"Kamera {camera_id} tidak ditemukan")
    return camera


def _camera_url(camera: CameraSource) -> str:
    try:
        return decrypt_url(camera.url_encrypted)
    except SecretKeyError as e:
        raise HTTPException(422, str(e))


@router.get("/projects/{project_id}/cameras", response_model=list[CameraOut])
def list_cameras(project_id: int, db: DbSession):
    get_project_or_404(db, project_id)
    return db.scalars(
        select(CameraSource).where(CameraSource.project_id == project_id).order_by(CameraSource.id)
    ).all()


@router.post("/projects/{project_id}/cameras", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
def add_camera(project_id: int, body: CameraIn, db: DbSession):
    get_project_or_404(db, project_id)
    try:
        encrypted = encrypt_url(body.url)
    except SecretKeyError as e:
        raise HTTPException(422, str(e))
    camera = CameraSource(project_id=project_id, name=body.name, url_encrypted=encrypted,
                          url_masked=mask_url(body.url))  # fmt: skip
    db.add(camera)
    db.commit()
    return camera


@router.delete("/cameras/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera_id: int, db: DbSession):
    """Hapus kamera. Frame yang sudah di-capture tetap ada sebagai gambar project."""
    db.delete(_get_camera(db, camera_id))
    db.commit()


@router.post("/cameras/{camera_id}/test")
def test_camera(camera_id: int, db: DbSession):
    """Ambil satu frame untuk memastikan kamera bisa diakses dari server."""
    url = _camera_url(_get_camera(db, camera_id))
    try:
        frame = grab_one(url)
    except CameraError as e:
        return {"ok": False, "error": scrub(str(e), url)}
    preview = encode_jpeg(frame, quality=80, max_side=640)
    return {"ok": True, "width": int(frame.shape[1]), "height": int(frame.shape[0]),
            "preview": "data:image/jpeg;base64," + base64.b64encode(preview).decode()}  # fmt: skip


@router.post("/cameras/{camera_id}/capture", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def start_capture(camera_id: int, body: CaptureOptions, db: DbSession, queue: Queue):
    camera = _get_camera(db, camera_id)
    _camera_url(camera)  # pastikan SECRET_KEY masih cocok sebelum job dibuat
    job = create_job(db, camera.project_id, JobType.RTSP_CAPTURE,
                     {"camera_id": camera.id, "camera": camera.name, "options": body.model_dump()})  # fmt: skip
    return _enqueue(db, queue, job)
