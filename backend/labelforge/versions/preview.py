"""Pratinjau augmentasi: beberapa contoh hasil dari gambar project, tanpa menyimpan apa pun."""

import base64

import numpy as np
from pydantic import Field
from sqlalchemy.orm import Session

from labelforge.augment.pipeline import augment, rng_for
from labelforge.models import Image
from labelforge.storage import StorageBackend
from labelforge.versions.builder import VersionSettings, plan_items
from labelforge.versions.samples import encode_jpeg, from_boxes, load_base, to_boxes

PREVIEW_MAX_SIDE = 480


class AugmentPreviewRequest(VersionSettings):
    count: int = Field(6, ge=1, le=12)


def preview_augmentation(db: Session, storage: StorageBackend, project_id: int,
                         body: AugmentPreviewRequest) -> dict:  # fmt: skip
    classes, items = plan_items(db, project_id, body)
    # Contoh diambil dari semua gambar versi (bukan hanya train) supaya pratinjau tetap
    # bervariasi pada dataset kecil; augmentasi sebenarnya hanya diterapkan ke split train.
    pool = items
    if not pool:
        return {"classes": [c.name for c in classes], "samples": []}

    keys = {img.id: img.storage_key for img in db.query(Image).filter(Image.id.in_({it["image_id"] for it in pool}))}
    rng = np.random.default_rng(body.seed)
    picked = [pool[int(i)] for i in rng.choice(len(pool), size=min(body.count, len(pool)), replace=False)]
    cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    def base(it: dict) -> tuple[np.ndarray, np.ndarray]:
        if it["image_id"] not in cache:
            img = load_base(storage, keys[it["image_id"]], body.preprocessing)
            cache[it["image_id"]] = (np.asarray(img), to_boxes(it["annotations"]))
        return cache[it["image_id"]]

    def pick_others(r: np.random.Generator, n: int, exclude: int):
        others = [it for it in pool if it["image_id"] != exclude]
        if len(others) < n:
            return []
        return [base(others[int(i)]) for i in r.choice(len(others), size=n, replace=False)]

    cfg = body.augmentation.model_copy(update={"enabled": True})
    samples = []
    for n, it in enumerate(picked, 1):
        img, boxes = augment(base(it), cfg, rng_for(body.seed, it["image_id"], n),
                             lambda r, k, ex=it["image_id"]: pick_others(r, k, ex))  # fmt: skip
        jpeg = encode_jpeg(img, quality=80, max_side=PREVIEW_MAX_SIDE)
        samples.append({
            "image_id": it["image_id"],
            "width": int(img.shape[1]),
            "height": int(img.shape[0]),
            "data_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(),
            "boxes": from_boxes(boxes),
        })  # fmt: skip
    return {"classes": [c.name for c in classes], "samples": samples}
