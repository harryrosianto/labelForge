import importlib
import threading

from labelforge.providers.base import LabelingProvider, ProviderError

_CLASSES: dict[str, type[LabelingProvider]] = {}
_INSTANCES: dict[str, LabelingProvider] = {}
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


def get_provider_class(name: str) -> type[LabelingProvider]:
    _ensure_builtins()
    try:
        return _CLASSES[name]
    except KeyError:
        raise ProviderError(f"Provider '{name}' tidak dikenal (tersedia: {sorted(_CLASSES)})")


def get_provider(name: str) -> LabelingProvider:
    """Instance singleton per proses; model di-load lazy saat detect pertama (atau load())."""
    cls = get_provider_class(name)
    with _LOCK:
        if name not in _INSTANCES:
            available, reason = cls.is_available()
            if not available:
                raise ProviderError(f"Provider '{name}' tidak tersedia: {reason}")
            _INSTANCES[name] = cls()
        return _INSTANCES[name]


def list_provider_classes() -> list[type[LabelingProvider]]:
    _ensure_builtins()
    return list(_CLASSES.values())


def describe_providers() -> list[dict]:
    """Metadata untuk UI / endpoint /providers. Provider default (config) diletakkan pertama."""
    from labelforge.config import get_settings

    settings = get_settings()
    out = []
    for cls in list_provider_classes():
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
            }
        )
    return sorted(out, key=lambda p: not p["is_default"])
