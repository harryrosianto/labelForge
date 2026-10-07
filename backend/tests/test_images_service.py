import io

import pytest
from PIL import Image as PILImage

from labelforge.models import Project
from labelforge.services.images import InvalidImageError, ingest_image


def make_jpeg(size=(320, 200), color="red", exif_orientation: int | None = None) -> bytes:
    buf = io.BytesIO()
    kwargs = {}
    if exif_orientation:
        exif = PILImage.Exif()
        exif[0x0112] = exif_orientation
        kwargs["exif"] = exif
    PILImage.new("RGB", size, color).save(buf, format="JPEG", **kwargs)
    return buf.getvalue()


@pytest.fixture
def pid(db):
    p = Project(name="p")
    db.add(p)
    db.commit()
    return p.id


def test_ingest_stores_image_and_thumbnail(db, storage, pid):
    res = ingest_image(db, storage, pid, "folder/cam1.jpg", make_jpeg((1280, 720)))
    img = res.image
    assert not res.duplicate
    assert (img.width, img.height) == (1280, 720)
    assert img.original_filename == "cam1.jpg"
    assert img.status == "unlabeled"
    assert storage.exists(img.storage_key) and storage.exists(img.thumb_key)
    thumb = PILImage.open(io.BytesIO(storage.read_bytes(img.thumb_key)))
    assert max(thumb.size) == 320


def test_ingest_detects_duplicate(db, storage, pid):
    data = make_jpeg()
    first = ingest_image(db, storage, pid, "a.jpg", data)
    second = ingest_image(db, storage, pid, "copy-of-a.jpg", data)
    assert second.duplicate and second.image.id == first.image.id


def test_ingest_applies_exif_rotation(db, storage, pid):
    img = ingest_image(db, storage, pid, "hp.jpg", make_jpeg((400, 100), exif_orientation=6)).image
    assert (img.width, img.height) == (100, 400)
    stored = PILImage.open(io.BytesIO(storage.read_bytes(img.storage_key)))
    assert stored.size == (100, 400)
    assert stored.getexif().get(0x0112, 1) == 1


def test_ingest_rejects_non_image(db, storage, pid):
    with pytest.raises(InvalidImageError):
        ingest_image(db, storage, pid, "notes.txt", b"hello")
