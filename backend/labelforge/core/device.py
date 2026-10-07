"""Pemilihan device & dtype. Import torch dilakukan lazy supaya proses web tidak butuh torch."""

from typing import Any


def resolve_device(setting: str = "auto") -> str:
    import torch

    setting = (setting or "auto").lower()
    if setting == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if setting.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(f"DEVICE={setting} diminta tetapi CUDA tidak tersedia")
    return setting


def resolve_dtype(device: str, use_fp16: bool) -> Any:
    import torch

    # fp16 di CPU lambat/tidak didukung banyak op → hanya dipakai di CUDA.
    return torch.float16 if use_fp16 and device.startswith("cuda") else torch.float32
