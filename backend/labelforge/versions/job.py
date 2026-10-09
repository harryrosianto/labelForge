"""Job worker pembuatan file versi: hasil preprocessing lalu salinan augmentasi (split train)."""

import time
from functools import lru_cache

import numpy as np
from sqlalchemy import select

from labelforge.augment.pipeline import augment, rng_for
from labelforge.models import DatasetVersion, DatasetVersionItem, Image, LabelingJob
from labelforge.models.enums import JobType, VersionStatus
from labelforge.services.job_runner import JobCancelled, JobContext, register_job_handler
from labelforge.versions.builder import VersionSettings, item_key, summarize, version_items
from labelforge.versions.samples import encode_jpeg, from_boxes, load_base, to_boxes


def _set_status(ctx: JobContext, version_id: int, status: str) -> None:
    with ctx.session_factory() as db:
        version = db.get(DatasetVersion, version_id)
        if version is not None:
            version.status = status
            db.commit()


@register_job_handler(JobType.VERSION_BUILD)
def build_version(ctx: JobContext) -> dict:
    version_id = int(ctx.payload["version_id"])
    with ctx.session_factory() as db:
        version = db.get(DatasetVersion, version_id)
        if version is None:
            raise ValueError(f"Versi {version_id} tidak ditemukan")
        settings = VersionSettings.model_validate(version.config)
        class_names = [c["name"] for c in version.config["classes"]]
        originals = [it for it in version_items(db, version_id) if it.variant == 0]
        existing_aug = {(it.image_id, it.variant) for it in version_items(db, version_id) if it.variant > 0}
        sources = dict(db.execute(select(Image.id, Image.storage_key).where(
            Image.id.in_({it.image_id for it in originals}))).all())  # fmt: skip
        project_id = version.project_id
        # Data item dipakai di luar sesi DB.
        originals = [(it.image_id, it.split, it.storage_key, it.annotations) for it in originals]

    aug = settings.augmentation
    resize_items = [o for o in originals if o[2]]
    train = [o for o in originals if o[1] == "train"]
    aug_jobs = [(o, k) for o in train for k in range(1, aug.multiplier + 1)] if aug.enabled else []
    ctx.set_total(len(resize_items) + len(aug_jobs))

    @lru_cache(maxsize=64)
    def base_sample(image_id: int) -> tuple[np.ndarray, np.ndarray]:
        """Gambar dasar augmentasi = hasil preprocessing (sama dengan item variant 0)."""
        _, _, key, annotations = by_image[image_id]
        img = load_base(ctx.storage, key) if key else load_base(ctx.storage, sources[image_id],
                                                                 settings.preprocessing)  # fmt: skip
        return np.asarray(img), to_boxes(annotations)

    by_image = {o[0]: o for o in originals}
    written = 0
    try:
        # 1) preprocessing gambar asli
        for image_id, _, key, _ in resize_items:
            ctx.check_cancel()
            if ctx.storage.exists(key):  # job dijalankan ulang: lewati yang sudah ada
                ctx.record(label=key, image_id=image_id)
                continue
            start = time.perf_counter()
            try:
                img = load_base(ctx.storage, sources[image_id], settings.preprocessing)
                ctx.storage.save_bytes(key, encode_jpeg(img))
                written += 1
                ctx.record(label=key, image_id=image_id, duration_ms=int((time.perf_counter() - start) * 1000))
            except Exception as e:
                ctx.record(label=key, image_id=image_id, error=f"{type(e).__name__}: {e}")

        # 2) salinan augmentasi untuk split train
        train_ids = [o[0] for o in train]
        for (image_id, _, _, _), variant in aug_jobs:
            ctx.check_cancel()
            key = item_key(project_id, version_id, "train", image_id, variant)
            if (image_id, variant) in existing_aug:
                ctx.record(label=key, image_id=image_id)
                continue
            start = time.perf_counter()
            try:
                others = [i for i in train_ids if i != image_id]

                def pick(rng: np.random.Generator, n: int, pool=others):
                    if len(pool) < n:
                        return []
                    return [base_sample(int(i)) for i in rng.choice(pool, size=n, replace=False)]

                img, boxes = augment(base_sample(image_id), aug, rng_for(settings.seed, image_id, variant), pick)
                ctx.storage.save_bytes(key, encode_jpeg(img))
                with ctx.session_factory() as db:
                    db.add(DatasetVersionItem(
                        version_id=version_id, image_id=image_id, split="train", variant=variant,
                        storage_key=key, width=img.shape[1], height=img.shape[0],
                        annotations=from_boxes(boxes),
                    ))  # fmt: skip
                    db.commit()
                written += 1
                ctx.record(label=key, image_id=image_id, count=len(boxes),
                           duration_ms=int((time.perf_counter() - start) * 1000))  # fmt: skip
            except Exception as e:
                ctx.record(label=key, image_id=image_id, error=f"{type(e).__name__}: {e}")
    except JobCancelled:
        _set_status(ctx, version_id, VersionStatus.FAILED)
        raise
    except Exception:
        _set_status(ctx, version_id, VersionStatus.FAILED)
        raise

    with ctx.session_factory() as db:
        failed = db.get(LabelingJob, ctx.job_id).failed_count
        version = db.get(DatasetVersion, version_id)
        items = [{"image_id": it.image_id, "split": it.split, "variant": it.variant,
                  "annotations": it.annotations} for it in version_items(db, version_id)]  # fmt: skip
        version.summary = summarize(class_names, items)
        version.image_count = len(items)
        # Versi hanya siap jika semua file berhasil dibuat.
        version.status = VersionStatus.FAILED if failed else VersionStatus.READY
        db.commit()
    return {"written": written, "failed": failed, "augmented": len(aug_jobs)}
