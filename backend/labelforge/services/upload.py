"""Upload multi-file dan ZIP."""

import zipfile
from collections.abc import Iterator
from pathlib import PurePosixPath
from typing import BinaryIO

from sqlalchemy.orm import Session

from labelforge.config import get_settings
from labelforge.schemas.image import ImageOut, UploadIssue, UploadResult
from labelforge.services.images import InvalidImageError, ingest_image
from labelforge.storage import StorageBackend

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
MAX_ZIP_ENTRIES = 50_000


def _zip_entries(fileobj: BinaryIO, name: str, result: UploadResult) -> Iterator[tuple[str, bytes]]:
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    try:
        zf = zipfile.ZipFile(fileobj)
    except zipfile.BadZipFile:
        result.errors.append(UploadIssue(filename=name, detail="ZIP rusak atau bukan ZIP"))
        return
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_ZIP_ENTRIES:
            result.errors.append(UploadIssue(filename=name, detail="ZIP berisi terlalu banyak file"))
            return
        # Lindungi dari zip bomb: cek total ukuran setelah ekstrak sebelum membaca isinya.
        if sum(i.file_size for i in infos) > max_bytes:
            result.errors.append(
                UploadIssue(filename=name, detail=f"Isi ZIP melebihi {get_settings().max_upload_mb} MB")
            )
            return
        for info in infos:
            path = PurePosixPath(info.filename)
            if path.parts[0] == "__MACOSX" or path.name.startswith("."):
                continue
            label = f"{name}/{info.filename}"
            if path.suffix.lower() not in IMAGE_EXTS:
                result.skipped.append(UploadIssue(filename=label, detail="bukan file gambar"))
                continue
            yield label, zf.read(info)


def process_uploads(
    db: Session, storage: StorageBackend, project_id: int, files: list[tuple[str, BinaryIO]]
) -> UploadResult:
    result = UploadResult(uploaded=[], duplicates=[], skipped=[], errors=[])

    def entries() -> Iterator[tuple[str, bytes]]:
        for name, fileobj in files:
            suffix = PurePosixPath(name).suffix.lower()
            if suffix == ".zip":
                yield from _zip_entries(fileobj, name, result)
            elif suffix in IMAGE_EXTS:
                yield name, fileobj.read()
            else:
                result.skipped.append(UploadIssue(filename=name, detail="bukan file gambar/ZIP"))

    for name, data in entries():
        try:
            res = ingest_image(db, storage, project_id, name, data)
        except InvalidImageError as e:
            result.errors.append(UploadIssue(filename=name, detail=str(e)))
            continue
        db.commit()  # commit per gambar: upload besar yang terputus tetap menyimpan yang sudah masuk
        if res.duplicate:
            result.duplicates.append(
                UploadIssue(filename=name, detail="duplikat", image_id=res.image.id)
            )
        else:
            result.uploaded.append(ImageOut.model_validate(res.image))
    return result
