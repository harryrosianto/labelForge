import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from labelforge.storage.base import StorageBackend


class LocalStorage(StorageBackend):
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"Key keluar dari root storage: {key!r}")
        return path

    def save_bytes(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def save_file(self, key: str, fileobj: BinaryIO) -> int:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "wb") as out:
            shutil.copyfileobj(fileobj, out, length=1024 * 1024)
        os.replace(tmp, path)
        return path.stat().st_size

    def read_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        path = self._path(prefix)
        if path == self.root:
            raise ValueError("Menolak menghapus seluruh root storage")
        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()

    @contextmanager
    def local_path(self, key: str) -> Iterator[Path]:
        yield self._path(key)

    def local_file_for_response(self, key: str) -> Path | None:
        path = self._path(key)
        return path if path.is_file() else None
