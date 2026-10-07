from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

PALETTE = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231", "#911eb4", "#46f0f0",
    "#f032e6", "#bcf60c", "#fabebe", "#008080", "#e6beff", "#9a6324", "#800000",
]  # fmt: skip


def draw_boxes(
    image: Image.Image,
    boxes: Sequence[tuple[Sequence[float], str, str]],
) -> Image.Image:
    """Gambar box ke salinan gambar. `boxes` = [(xyxy_px, teks_label, warna_hex), ...]."""
    out = image.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    scale = max(out.width, out.height) / 1000
    width = max(2, round(2 * scale))
    font = ImageFont.load_default(size=max(12, round(14 * scale)))
    for box, text, color in boxes:
        x1, y1, x2, y2 = box
        draw.rectangle((x1, y1, x2, y2), outline=color, width=width)
        tx1, ty1, tx2, ty2 = draw.textbbox((x1, y1), text, font=font)
        th = ty2 - ty1 + 4
        ty = y1 - th if y1 - th >= 0 else y1
        draw.rectangle((x1, ty, x1 + (tx2 - tx1) + 6, ty + th), fill=color)
        draw.text((x1 + 3, ty + 1), text, fill="black", font=font)
    return out
