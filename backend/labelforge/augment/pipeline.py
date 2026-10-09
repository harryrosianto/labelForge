"""Konfigurasi & urutan augmentasi. Deterministik: seed (versi, gambar, salinan) → hasil sama."""

from collections.abc import Callable

import numpy as np
from pydantic import BaseModel, Field, model_validator

from labelforge.augment import ops

Sample = tuple[np.ndarray, np.ndarray]  # (gambar RGB uint8, box Nx5)


class AugmentationConfig(BaseModel):
    enabled: bool = False
    multiplier: int = Field(2, ge=1, le=5, description="Salinan augmentasi per gambar train")
    # geometrik
    hflip: float = Field(0.5, ge=0, le=1, description="Peluang flip horizontal")
    rotate_deg: float = Field(0, ge=0, le=45, description="Rotasi acak ± derajat (0 = mati)")
    scale_min: float = Field(1.0, ge=0.5, le=1.0)
    scale_max: float = Field(1.0, ge=1.0, le=2.0)
    translate: float = Field(0.0, ge=0, le=0.3, description="Geser acak ± pecahan ukuran gambar")
    mosaic: float = Field(0.0, ge=0, le=1, description="Peluang mosaic 2x2")
    # warna
    brightness: float = Field(0.2, ge=0, le=0.5)
    contrast: float = Field(0.2, ge=0, le=0.5)
    hue_deg: float = Field(0, ge=0, le=30)
    saturation: float = Field(0.0, ge=0, le=0.7)
    blur: float = Field(0.0, ge=0, le=1, description="Peluang blur")
    blur_max_kernel: int = Field(5, ge=3, le=11)
    noise: float = Field(0.0, ge=0, le=1, description="Peluang noise")
    noise_std: float = Field(8.0, ge=0, le=30)
    # box
    min_visibility: float = Field(0.3, ge=0, le=1, description="Box dibuang bila sisa luasnya < nilai ini")

    @model_validator(mode="after")
    def _scale_range(self):
        if self.scale_min > self.scale_max:
            raise ValueError("scale_min tidak boleh lebih besar dari scale_max")
        return self


def rng_for(version_seed: int, image_id: int, variant: int) -> np.random.Generator:
    return np.random.default_rng([version_seed, image_id, variant])


def augment(
    sample: Sample,
    cfg: AugmentationConfig,
    rng: np.random.Generator,
    pick_others: Callable[[np.random.Generator, int], list[Sample]] | None = None,
) -> Sample:
    """Satu salinan augmentasi. `pick_others(rng, n)` menyediakan gambar lain untuk mosaic."""
    img, boxes = sample
    vis = cfg.min_visibility

    if cfg.mosaic > 0 and pick_others is not None and rng.random() < cfg.mosaic:
        others = pick_others(rng, 3)
        if len(others) == 3:
            h, w = img.shape[:2]
            center = (rng.uniform(0.3, 0.7), rng.uniform(0.3, 0.7))
            img, boxes = ops.mosaic([(img, boxes), *others], (w, h), center, vis)

    if cfg.hflip > 0 and rng.random() < cfg.hflip:
        img, boxes = ops.hflip(img, boxes)
    if cfg.scale_min != 1.0 or cfg.scale_max != 1.0 or cfg.translate > 0:
        img, boxes = ops.scale_translate(
            img, boxes, rng.uniform(cfg.scale_min, cfg.scale_max),
            rng.uniform(-cfg.translate, cfg.translate), rng.uniform(-cfg.translate, cfg.translate), vis,
        )  # fmt: skip
    if cfg.rotate_deg > 0:
        img, boxes = ops.rotate(img, boxes, rng.uniform(-cfg.rotate_deg, cfg.rotate_deg), vis)

    if cfg.brightness > 0 or cfg.contrast > 0:
        img = ops.brightness_contrast(img, rng.uniform(-cfg.brightness, cfg.brightness),
                                      rng.uniform(-cfg.contrast, cfg.contrast))  # fmt: skip
    if cfg.hue_deg > 0 or cfg.saturation > 0:
        img = ops.hue_saturation(img, rng.uniform(-cfg.hue_deg, cfg.hue_deg),
                                 rng.uniform(-cfg.saturation, cfg.saturation))  # fmt: skip
    if cfg.blur > 0 and rng.random() < cfg.blur:
        img = ops.blur(img, int(rng.integers(3, cfg.blur_max_kernel + 1)))
    if cfg.noise > 0 and rng.random() < cfg.noise:
        img = ops.noise(img, cfg.noise_std, rng)
    return img, boxes
