from functools import lru_cache

from labelforge.config import get_settings
from labelforge.storage.base import StorageBackend
from labelforge.storage.local import LocalStorage


@lru_cache
def get_storage() -> StorageBackend:
    """Backend storage aktif. Nanti dipilih via config (mis. STORAGE_BACKEND=s3)."""
    return LocalStorage(get_settings().data_dir)


def project_prefix(project_id: int) -> str:
    return f"projects/{project_id}"


__all__ = ["LocalStorage", "StorageBackend", "get_storage", "project_prefix"]
