"""Ingest gambar: validasi, normalisasi orientasi EXIF, thumbnail, deduplikasi via SHA-256."""

import hashlib
import io
import uuid
from dataclasses import dataclass
from pathlib import PurePath

from PIL import Image as PILImage
from PIL import ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from labelforge.config import get_settings
from labelforge.media.dedup import dhash
from labelforge.models import Image
from labelforge.storage import StorageBackend, project_prefix

ALLOWED_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "BMP": ".bmp", "WEBP": ".webp", "TIFF": ".tif"}
EXIF_ORIENTATION = 0x0112


class InvalidImageError(ValueError):
    pass


@dataclass
class IngestResult:
    image: Image
    duplicate: bool


def ingest_image(
    db: Session, storage: StorageBackend, project_id: int, filename: str, data: bytes
) -> IngestResult:
    """Simpan satu gambar ke project. Gambar identik (hash sama) tidak disimpan ulang.

    Caller bertanggung jawab atas `db.commit()`.
    """
    sha256 = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Image).where(Image.project_id == project_id, Image.sha256 == sha256))
    if existing is not None:
        return IngestResult(existing, duplicate=True)

    try:
        with PILImage.open(io.BytesIO(data)) as probe:
            probe.verify()
        img = PILImage.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, PILImage.DecompressionBombError) as e:
        raise InvalidImageError(f"{filename}: bukan gambar yang valid ({e})") from e
    if img.format not in ALLOWED_FORMATS:
        raise InvalidImageError(f"{filename}: format {img.format} tidak didukung")

    # Terapkan orientasi EXIF ke pixel supaya koordinat box selalu sesuai gambar yang tersimpan.
    ext = ALLOWED_FORMATS[img.format]
    stored = data
    if img.getexif().get(EXIF_ORIENTATION, 1) != 1:
        img = ImageOps.exif_transpose(img)
        buf = io.BytesIO()
        if img.format == "JPEG" or ext == ".jpg":
            img.convert("RGB").save(buf, format="JPEG", quality=95)
            ext = ".jpg"
        else:
            img.save(buf, format="PNG")
            ext = ".png"
        stored = buf.getvalue()

    name = uuid.uuid4().hex
    prefix = project_prefix(project_id)
    image_key = f"{prefix}/images/{name}{ext}"
    thumb_key = f"{prefix}/thumbs/{name}.jpg"

    thumb = img.convert("RGB")
    size = get_settings().thumbnail_size
    thumb.thumbnail((size, size))
    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=85)

    storage.save_bytes(image_key, stored)
    storage.save_bytes(thumb_key, buf.getvalue())

    image = Image(
        project_id=project_id,
        original_filename=PurePath(filename).name[:500],
        storage_key=image_key,
        thumb_key=thumb_key,
        width=img.width,
        height=img.height,
        sha256=sha256,
        dhash=dhash(thumb),
    )
    db.add(image)
    db.flush()
    return IngestResult(image, duplicate=False)


def delete_image_files(storage: StorageBackend, image: Image) -> None:
    storage.delete(image.storage_key)
    storage.delete(image.thumb_key)
