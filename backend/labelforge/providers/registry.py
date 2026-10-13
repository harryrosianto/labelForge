import importlib
import json
import threading
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from labelforge.providers.base import LabelingProvider, ProviderError
from labelforge.providers.custom_model import make_provider_class, model_id_of

if TYPE_CHECKING:
    from labelforge.storage import StorageBackend

_CLASSES: dict[str, type[LabelingProvider]] = {}
_INSTANCES: dict[str, LabelingProvider] = {}
_CUSTOM: dict[str, tuple[str, type[LabelingProvider]]] = {}  # nama -> (sidik jari, kelas)
_LOCK = threading.Lock()

# Modul provider bawaan; provider baru cukup ditambahkan di sini (atau di-import di tempat lain).
BUILTIN_MODULES = (
    "labelforge.providers.grounding_dino",
    "labelforge.providers.owlv2",
    "labelforge.providers.remote_api",
)
_builtins_loaded = False


def register_provider(cls: type[LabelingProvider]) -> type[LabelingProvider]:
    if cls.name in _CLASSES and _CLASSES[cls.name] is not cls:
        raise ValueError(f"Provider '{cls.name}' sudah terdaftar")
    _CLASSES[cls.name] = cls
    return cls


def _ensure_builtins() -> None:
    global _builtins_loaded
    if not _builtins_loaded:
        for module in BUILTIN_MODULES:
            importlib.import_module(module)
        _builtins_loaded = True


def _custom_class(model, storage: "StorageBackend | None" = None) -> type[LabelingProvider]:
    """Kelas provider untuk satu baris `models`; dibuat ulang bila file/pemetaan berubah."""
    from labelforge.storage import get_storage

    storage = storage or get_storage()
    name = f"model:{model.id}"
    config = model.config or {}
    path = storage.local_file_for_response(model.weights_key) if model.weights_key else None
    fingerprint = json.dumps([str(path), config.get("class_map"), model.name], sort_keys=True)
    with _LOCK:
        cached = _CUSTOM.get(name)
        if cached and cached[0] == fingerprint:
            return cached[1]
        cls = make_provider_class(model.id, model.project_id, f"Model: {model.name}", path,
                                  config.get("class_map") or {})  # fmt: skip
        _CUSTOM[name] = (fingerprint, cls)
        return cls


def get_provider_class(
    name: str, db: Session | None = None, storage: "StorageBackend | None" = None
) -> type[LabelingProvider]:
    """Provider bawaan, atau `model:<id>` (model kustom; dibaca dari DB lewat `db`)."""
    model_id = model_id_of(name)
    if model_id is not None:
        from labelforge.models import MLModel

        def load(session: Session):
            model = session.get(MLModel, model_id)
            if model is None or model.status != "ready":
                raise ProviderError(f"Model {model_id} tidak ditemukan atau belum siap")
            return _custom_class(model, storage)

        if db is not None:
            return load(db)
        from labelforge.db import get_session_factory

        with get_session_factory()() as session:
            return load(session)
    _ensure_builtins()
    try:
        return _CLASSES[name]
    except KeyError:
        raise ProviderError(f"Provider '{name}' tidak dikenal (tersedia: {sorted(_CLASSES)})")


def get_provider(
    name: str, db: Session | None = None, storage: "StorageBackend | None" = None
) -> LabelingProvider:
    """Instance singleton per proses; model di-load lazy saat detect pertama (atau load())."""
    cls = get_provider_class(name, db, storage)
    with _LOCK:
        instance = _INSTANCES.get(name)
        if instance is None or type(instance) is not cls:  # model kustom diubah: muat ulang
            available, reason = cls.is_available()
            if not available:
                raise ProviderError(f"Provider '{name}' tidak tersedia: {reason}")
            _INSTANCES[name] = instance = cls()
        return instance


def list_provider_classes() -> list[type[LabelingProvider]]:
    _ensure_builtins()
    return list(_CLASSES.values())


def describe_providers(
    db: Session | None = None, project_id: int | None = None, storage: "StorageBackend | None" = None
) -> list[dict]:
    """Metadata untuk UI / endpoint /providers. Provider default (config) diletakkan pertama.

    Dengan `project_id`, model kustom project itu ikut didaftar (paling atas: biasanya paling akurat).
    """
    from labelforge.config import get_settings

    settings = get_settings()
    classes = list_provider_classes()
    custom: list[type[LabelingProvider]] = []
    if db is not None and project_id is not None:
        from sqlalchemy import select

        from labelforge.models import MLModel

        models = db.scalars(select(MLModel).where(MLModel.project_id == project_id,
                                                  MLModel.status == "ready").order_by(MLModel.id.desc()))  # fmt: skip
        custom = [_custom_class(m, storage) for m in models]
    out = []
    for cls in custom + classes:
        available, reason = cls.is_available()
        is_default = cls.name == settings.default_provider
        out.append(
            {
                "name": cls.name,
                "label": cls.label or cls.name,
                "is_default": is_default,
                "default_mode": settings.default_mode if is_default else cls.modes[0],
                "modes": list(cls.modes),
                "available": available,
                "unavailable_reason": reason,
                "params": {m: [s.to_dict() for s in cls.all_param_specs(m)] for m in cls.modes},
                "custom": cls in custom,
            }
        )
    return sorted(out, key=lambda p: (not p["custom"], not p["is_default"]))
