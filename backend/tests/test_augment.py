import numpy as np
import pytest

from labelforge.augment import ops
from labelforge.augment.pipeline import AugmentationConfig, augment, rng_for

W, H = 320, 200  # non-persegi
COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]


def scene(box=(0.3, 0.25, 0.6, 0.7), color=(255, 0, 0), cls=0, size=(W, H)):
    """Gambar abu-abu dengan satu kotak berwarna penuh di posisi box."""
    w, h = size
    img = np.full((h, w, 3), 40, dtype=np.uint8)
    x1, y1, x2, y2 = box
    img[round(y1 * h):round(y2 * h), round(x1 * w):round(x2 * w)] = color
    return img, np.array([[cls, *box]], dtype=np.float64)


def color_bbox(img, color):
    """Bounding box ternormalisasi dari piksel yang dekat dengan `color`."""
    mask = np.all(np.abs(img.astype(int) - np.array(color)) < 60, axis=2)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    h, w = img.shape[:2]
    return np.array([xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h])


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union


def assert_box_matches(img, boxes, color=(255, 0, 0), min_iou=0.93):
    assert len(boxes) == 1
    actual = color_bbox(img, color)
    assert actual is not None
    assert iou(boxes[0, 1:], actual) >= min_iou, (boxes[0, 1:], actual)


def test_hflip():
    img, boxes = scene()
    out, b = ops.hflip(img, boxes)
    assert b[0, 1:] == pytest.approx([0.4, 0.25, 0.7, 0.7])
    assert_box_matches(out, b, min_iou=0.99)


@pytest.mark.parametrize("scale,sx,sy", [(1.5, 0, 0), (0.6, 0.1, -0.1), (1.2, -0.15, 0.1)])
def test_scale_translate(scale, sx, sy):
    img, boxes = scene()
    out, b = ops.scale_translate(img, boxes, scale, sx, sy, min_visibility=0.0)
    assert out.shape == img.shape
    assert_box_matches(out, b)


@pytest.mark.parametrize("angle", [-30, -10, 7, 25])
def test_rotate_box_contains_rotated_object(angle):
    img, boxes = scene(box=(0.35, 0.3, 0.6, 0.65))
    out, b = ops.rotate(img, boxes, angle, min_visibility=0.0)
    # box hasil = bounding box sudut yang dirotasi → sama dengan batas piksel objek
    assert_box_matches(out, b, min_iou=0.9)


def test_box_mostly_out_of_frame_is_dropped():
    img, boxes = scene(box=(0.85, 0.4, 0.99, 0.6))
    _, kept = ops.scale_translate(img, boxes, 1.0, 0.13, 0.0, min_visibility=0.5)
    assert len(kept) == 0  # tergeser keluar, sisa < 50%
    _, kept = ops.scale_translate(img, boxes, 1.0, 0.13, 0.0, min_visibility=0.0)
    assert len(kept) == 1 and kept[0, 3] == pytest.approx(1.0)


def test_mosaic_each_box_lands_on_its_object():
    samples = [scene(box=(0.3, 0.3, 0.7, 0.7), color=c, cls=i, size=s)
               for i, (c, s) in enumerate(zip(COLORS, [(320, 200), (200, 320), (300, 300), (640, 360)]))]  # fmt: skip
    out, boxes = ops.mosaic(samples, (W, H), (0.45, 0.55), min_visibility=0.0)
    assert out.shape == (H, W, 3)
    assert sorted(boxes[:, 0].astype(int)) == [0, 1, 2, 3]
    for row in boxes:
        actual = color_bbox(out, COLORS[int(row[0])])
        assert iou(row[1:], actual) >= 0.9, (int(row[0]), row[1:], actual)


def test_color_ops_keep_boxes_and_shape():
    img, boxes = scene()
    rng = np.random.default_rng(0)
    for out in (ops.brightness_contrast(img, 0.2, -0.1), ops.hue_saturation(img, 15, 0.3),
                ops.blur(img, 5), ops.noise(img, 10, rng)):  # fmt: skip
        assert out.shape == img.shape and out.dtype == np.uint8
    assert ops.brightness_contrast(img, 0.2, 0).mean() > img.mean()


FULL = AugmentationConfig(enabled=True, hflip=0.5, rotate_deg=15, scale_min=0.8, scale_max=1.3,
                          translate=0.1, brightness=0.3, contrast=0.3, hue_deg=10, saturation=0.3,
                          blur=0.5, noise=0.5, min_visibility=0.0)  # fmt: skip


def test_pipeline_is_deterministic_and_seed_sensitive():
    sample = scene()
    a = augment(sample, FULL, rng_for(42, 7, 1))
    b = augment(sample, FULL, rng_for(42, 7, 1))
    c = augment(sample, FULL, rng_for(42, 7, 2))
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])
    assert not np.array_equal(a[0], c[0])


@pytest.mark.parametrize("seed", range(12))
def test_pipeline_boxes_follow_object(seed):
    """Tanpa operasi warna, box hasil pipeline harus tetap menempel pada objek."""
    cfg = FULL.model_copy(update={"brightness": 0, "contrast": 0, "hue_deg": 0, "saturation": 0,
                                  "blur": 0, "noise": 0})  # fmt: skip
    out, b = augment(scene(box=(0.35, 0.3, 0.65, 0.7)), cfg, rng_for(seed, 1, 1))
    if len(b):
        actual = color_bbox(out, (255, 0, 0))
        assert iou(b[0, 1:], actual) >= 0.85, (seed, b[0, 1:], actual)


def test_pipeline_mosaic_uses_other_samples():
    cfg = AugmentationConfig(enabled=True, mosaic=1.0, hflip=0, brightness=0, contrast=0)
    others = [scene(color=c, cls=i) for i, c in enumerate(COLORS[1:], 1)]
    out, b = augment(scene(), cfg, rng_for(1, 1, 1), pick_others=lambda rng, n: others[:n])
    assert sorted(set(b[:, 0].astype(int))) == [0, 1, 2, 3]


def test_config_validation():
    with pytest.raises(ValueError):
        AugmentationConfig(scale_min=0.5, scale_max=0.4)
    with pytest.raises(ValueError):
        AugmentationConfig(multiplier=9)
