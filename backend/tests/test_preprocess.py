import pytest
from PIL import Image, ImageDraw

from labelforge.versions.preprocess import (
    Preprocessing,
    apply_preprocessing,
    fit_geometry,
    output_size,
    transform_box,
)

FIT = Preprocessing(resize="fit", width=640, height=640)
STRETCH = Preprocessing(resize="stretch", width=320, height=320)


def test_fit_geometry_landscape_and_portrait():
    assert fit_geometry(400, 200, 640, 640) == (640, 320, 0, 160)
    assert fit_geometry(200, 400, 640, 640) == (320, 640, 160, 0)
    assert fit_geometry(1280, 720, 640, 640) == (640, 360, 0, 140)


def test_transform_box_fit_and_stretch():
    assert transform_box((0, 0, 1, 1), 400, 200, FIT) == pytest.approx((0, 0.25, 1, 0.75))
    assert transform_box((0.1, 0.2, 0.5, 0.6), 400, 200, STRETCH) == (0.1, 0.2, 0.5, 0.6)
    assert transform_box((0.1, 0.2, 0.5, 0.6), 400, 200, Preprocessing()) == (0.1, 0.2, 0.5, 0.6)


def test_requires_size():
    with pytest.raises(ValueError):
        Preprocessing(resize="fit")
    assert output_size(400, 200, Preprocessing()) == (400, 200)
    assert output_size(400, 200, FIT) == (640, 640)


@pytest.mark.parametrize("p", [FIT, STRETCH], ids=["fit", "stretch"])
@pytest.mark.parametrize("src_size", [(400, 200), (200, 400), (1280, 720)])
def test_pixels_inside_transformed_box_match(p, src_size):
    """Isi gambar output di dalam box tertransformasi harus objek yang sama (kotak merah)."""
    w, h = src_size
    box = (0.3, 0.25, 0.6, 0.7)
    img = Image.new("RGB", src_size, "white")
    ImageDraw.Draw(img).rectangle((box[0] * w, box[1] * h, box[2] * w - 1, box[3] * h - 1), fill="red")

    out = apply_preprocessing(img, p)
    assert out.size == (p.width, p.height)
    x1, y1, x2, y2 = transform_box(box, w, h, p)
    ow, oh = out.size
    # titik di dalam box (sedikit menjauh dari tepi karena interpolasi) harus merah
    for fx, fy in [(0.1, 0.1), (0.5, 0.5), (0.9, 0.9), (0.1, 0.9)]:
        px = int((x1 + (x2 - x1) * fx) * ow)
        py = int((y1 + (y2 - y1) * fy) * oh)
        r, g, b = out.getpixel((px, py))
        assert r > 200 and g < 60 and b < 60, (px, py, (r, g, b))
    # titik tepat di luar box harus bukan merah
    r, g, b = out.getpixel((min(ow - 1, int(x2 * ow) + 3), int((y1 + y2) / 2 * oh)))
    assert not (r > 200 and g < 60)


def test_fit_padding_color():
    out = apply_preprocessing(Image.new("RGB", (400, 200), "white"), FIT)
    assert out.getpixel((320, 10)) == (114, 114, 114)  # area padding atas
    assert out.getpixel((320, 320)) == (255, 255, 255)  # area gambar
