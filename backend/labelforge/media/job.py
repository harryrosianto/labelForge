"""Job worker ekstraksi frame video dan capture kamera RTSP (queue `io`)."""

import re
from datetime import datetime, timezone

import numpy as np

from labelforge.media.dedup import SimilarFilter, dhash
from labelforge.media.rtsp import CameraError, CaptureOptions, capture_frames
from labelforge.media.secrets import decrypt_url, scrub
from labelforge.media.video import ExtractOptions, VideoInfo, iter_frames, sample_times
from labelforge.models import CameraSource, Image, Video
from labelforge.models.enums import ImageSource, JobType
from labelforge.services.images import ingest_image
from labelforge.services.job_runner import JobCancelled, JobContext, register_job_handler
from labelforge.versions.samples import encode_jpeg


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")[:60] or "frame"


def save_frame(
    ctx: JobContext, frame: np.ndarray, filename: str, *, source_type: str, source_id: int,
    source_label: str, frame_time_s: float | None = None, captured_at: datetime | None = None,
) -> tuple[int, bool]:  # fmt: skip
    """Simpan frame sebagai gambar unlabeled. (image_id, duplikat?)"""
    with ctx.session_factory() as db:
        res = ingest_image(db, ctx.storage, ctx.project_id, filename, encode_jpeg(frame, quality=92))
        if res.duplicate:
            db.rollback()
            return res.image.id, True
        image: Image = res.image
        image.source_type, image.source_id = source_type, source_id
        image.source_label, image.frame_time_s, image.captured_at = source_label[:200], frame_time_s, captured_at
        db.commit()
        return image.id, False


@register_job_handler(JobType.VIDEO_EXTRACT)
def extract_video(ctx: JobContext) -> dict:
    opts = ExtractOptions.model_validate(ctx.payload["options"])
    with ctx.session_factory() as db:
        video = db.get(Video, int(ctx.payload["video_id"]))
        if video is None:
            raise ValueError("Video tidak ditemukan")
        info = VideoInfo(video.duration_s, video.fps, video.frame_count, video.width, video.height)
        key, name, video_id = video.storage_key, video.original_filename, video.id

    times = sample_times(info, opts)
    ctx.set_total(len(times))
    similar = SimilarFilter(opts.dedup_threshold)
    added = duplicates = 0
    stem = _slug(name.rsplit(".", 1)[0])
    with ctx.storage.local_path(key) as path:
        for t, frame in iter_frames(str(path), times, info.fps):
            ctx.check_cancel()
            label = f"{name} @ {t:.2f}s"
            if frame is None:
                ctx.record(label=label, error="Frame tidak terbaca")
                continue
            if not similar.accept(dhash(frame)):
                ctx.record(label=label, count=0)  # mirip frame sebelumnya: dilewati
                continue
            image_id, dup = save_frame(ctx, frame, f"{stem}_t{t:09.2f}.jpg", source_type=ImageSource.VIDEO,
                                       source_id=video_id, source_label=name, frame_time_s=t)  # fmt: skip
            duplicates += dup
            added += not dup
            ctx.record(label=label, image_id=image_id, count=0 if dup else 1)
    return {"frames_added": added, "skipped_similar": similar.skipped, "duplicates": duplicates,
            "sampled": len(times)}  # fmt: skip


@register_job_handler(JobType.RTSP_CAPTURE)
def capture_rtsp(ctx: JobContext) -> dict:
    opts = CaptureOptions.model_validate(ctx.payload["options"])
    with ctx.session_factory() as db:
        camera = db.get(CameraSource, int(ctx.payload["camera_id"]))
        if camera is None:
            raise ValueError("Kamera tidak ditemukan")
        url, camera_id, camera_name = decrypt_url(camera.url_encrypted), camera.id, camera.name

    # Total tidak diketahui di awal untuk capture berbasis durasi; perkiraan untuk progress.
    expected = opts.max_frames or max(1, int((opts.duration_s or 0) // opts.interval_s) + 1)
    ctx.set_total(expected)
    similar = SimilarFilter(opts.dedup_threshold)
    added = duplicates = reconnects = 0
    stem = _slug(camera_name)

    def stop() -> bool:
        try:
            ctx.check_cancel()
            return False
        except JobCancelled:
            return True

    def reconnected(n: int) -> None:
        nonlocal reconnects
        reconnects += 1
        ctx.warn(f"Koneksi kamera putus, mencoba sambung ulang ({n})")

    try:
        for frame in capture_frames(url, opts, should_stop=stop, on_reconnect=reconnected):
            now = datetime.now(timezone.utc)
            label = f"{camera_name} {now:%Y-%m-%d %H:%M:%S}"
            if not similar.accept(dhash(frame)):
                ctx.record(label=label, count=0)
                continue
            image_id, dup = save_frame(ctx, frame, f"{stem}_{now:%Y%m%d_%H%M%S_%f}.jpg",
                                       source_type=ImageSource.RTSP, source_id=camera_id,
                                       source_label=camera_name, captured_at=now)  # fmt: skip
            duplicates += dup
            added += not dup
            ctx.record(label=label, image_id=image_id, count=0 if dup else 1)
    except CameraError as e:
        # Pesan error tidak boleh membawa URL/kredensial kamera.
        raise CameraError(scrub(str(e), url)) from None
    ctx.check_cancel()  # dibatalkan → status cancelled, bukan completed
    if added + duplicates + similar.skipped == 0:
        # Tidak satu frame pun terbaca: laporkan gagal, bukan "selesai" dengan 0 frame.
        detail = f" setelah {reconnects} kali sambung ulang" if reconnects else ""
        raise CameraError(f"Tidak ada frame yang berhasil diambil dari kamera{detail}")
    return {"frames_added": added, "skipped_similar": similar.skipped, "duplicates": duplicates,
            "reconnects": reconnects}  # fmt: skip
