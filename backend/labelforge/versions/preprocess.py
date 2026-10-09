"""Preprocessing gambar versi (resize) beserta transformasi box-nya."""

from typing import Literal

from PIL import Image
from pydantic import BaseModel, Field, model_validator

Box = tuple[float, float, float, float]


class Preprocessing(BaseModel):
    """resize:
    - none    : gambar asli
    - stretch : diubah ke width x height tanpa mempertahankan rasio (box ternormalisasi tetap)
    - fit     : diperkecil/diperbesar agar muat, sisa area diberi padding (letterbox)
    """

    resize: Literal["none", "stretch", "fit"] = "none"
    width: int | None = Field(default=None, ge=32, le=8192)
    height: int | None = Field(default=None, ge=32, le=8192)
    pad_color: tuple[int, int, int] = (114, 114, 114)  # abu-abu, umum untuk letterbox YOLO

    @model_validator(mode="after")
    def _size_required(self):
        if self.resize != "none" and (self.width is None or self.height is None):
            raise ValueError("width dan height wajib diisi untuk resize")
        return self

    @property
    def active(self) -> bool:
        return self.resize != "none"


def fit_geometry(src_w: int, src_h: int, dst_w: int, dst_h: int) -> tuple[int, int, int, int]:
    """(lebar baru, tinggi baru, offset x, offset y) untuk letterbox di tengah."""
    scale = min(dst_w / src_w, dst_h / src_h)
    new_w, new_h = max(1, round(src_w * scale)), max(1, round(src_h * scale))
    return new_w, new_h, (dst_w - new_w) // 2, (dst_h - new_h) // 2


def transform_box(box: Box, src_w: int, src_h: int, p: Preprocessing) -> Box:
    """Box ternormalisasi terhadap gambar asli → ternormalisasi terhadap gambar output."""
    if p.resize != "fit":
        return box  # none & stretch: koordinat relatif tidak berubah
    new_w, new_h, off_x, off_y = fit_geometry(src_w, src_h, p.width, p.height)
    x1, y1, x2, y2 = box
    return (
        (off_x + x1 * new_w) / p.width,
        (off_y + y1 * new_h) / p.height,
        (off_x + x2 * new_w) / p.width,
        (off_y + y2 * new_h) / p.height,
    )


def apply_preprocessing(img: Image.Image, p: Preprocessing) -> Image.Image:
    img = img.convert("RGB")
    if p.resize == "stretch":
        return img.resize((p.width, p.height), Image.Resampling.BILINEAR)
    if p.resize == "fit":
        new_w, new_h, off_x, off_y = fit_geometry(img.width, img.height, p.width, p.height)
        canvas = Image.new("RGB", (p.width, p.height), tuple(p.pad_color))
        canvas.paste(img.resize((new_w, new_h), Image.Resampling.BILINEAR), (off_x, off_y))
        return canvas
    return img


def output_size(src_w: int, src_h: int, p: Preprocessing) -> tuple[int, int]:
    return (p.width, p.height) if p.active else (src_w, src_h)
