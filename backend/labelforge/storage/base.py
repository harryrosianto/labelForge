from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class StorageBackend(ABC):
    """Abstraksi penyimpanan file. Key selalu path relatif dengan '/', mis. 'projects/1/images/x.jpg'."""

    @abstractmethod
    def save_bytes(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def read_bytes(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Hapus satu file; tidak error jika tidak ada."""

    @abstractmethod
    def delete_prefix(self, prefix: str) -> None:
        """Hapus semua file di bawah prefix (mis. seluruh folder project)."""

    @abstractmethod
    @contextmanager
    def local_path(self, key: str) -> Iterator[Path]:
        """Path lokal yang bisa dibaca model/PIL. Backend remote (S3) men-download ke temp file."""

    @abstractmethod
    def local_file_for_response(self, key: str) -> Path | None:
        """Path untuk FileResponse jika file ada di disk lokal, else None (pakai streaming/URL)."""
