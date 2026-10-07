import pytest

from labelforge.core import formats as f

# Gambar non-persegi supaya tertukarnya width/height langsung ketahuan.
W, H = 1920, 1080


def approx(box, rel=1e-9, abs_=1e-9):
    return pytest.approx(tuple(box), rel=rel, abs=abs_)


class TestPixelNormalized:
    def test_basic(self):
        assert f.xyxy_px_to_norm((192, 108, 960, 540), W, H) == approx((0.1, 0.1, 0.5, 0.5))

    def test_roundtrip(self):
        box = (13.5, 77.25, 1001.0, 999.9)
        assert f.norm_to_xyxy_px(f.xyxy_px_to_norm(box, W, H), W, H) == approx(box)

    def test_clips_outside_image(self):
        assert f.xyxy_px_to_norm((-50, -10, 2000, 1200), W, H) == approx((0, 0, 1, 1))

    def test_swapped_corners_are_ordered(self):
        assert f.xyxy_px_to_norm((960, 540, 192, 108), W, H) == approx((0.1, 0.1, 0.5, 0.5))

    @pytest.mark.parametrize("w,h", [(0, 10), (10, 0), (-1, 5)])
    def test_invalid_size(self, w, h):
        with pytest.raises(ValueError):
            f.xyxy_px_to_norm((0, 0, 1, 1), w, h)


class TestYolo:
    def test_norm_to_yolo(self):
        assert f.norm_xyxy_to_yolo((0.1, 0.2, 0.5, 0.6)) == approx((0.3, 0.4, 0.4, 0.4))

    def test_yolo_to_norm(self):
        assert f.yolo_to_norm_xyxy((0.3, 0.4, 0.4, 0.4)) == approx((0.1, 0.2, 0.5, 0.6))

    def test_pixel_yolo_roundtrip_non_square(self):
        box = (100, 50, 400, 1000)
        yolo = f.xyxy_px_to_yolo(box, W, H)
        # cx dibagi width, cy dibagi height
        assert yolo == approx((250 / W, 525 / H, 300 / W, 950 / H))
        assert f.yolo_to_xyxy_px(yolo, W, H) == approx(box, abs_=1e-6)

    def test_full_image(self):
        assert f.norm_xyxy_to_yolo((0, 0, 1, 1)) == approx((0.5, 0.5, 1, 1))

    def test_box_at_edge_stays_in_range(self):
        cx, cy, w, h = f.xyxy_px_to_yolo((1800, 1000, 1920, 1080), W, H)
        assert 0 <= cx - w / 2 and cx + w / 2 <= 1 + 1e-12
        assert 0 <= cy - h / 2 and cy + h / 2 <= 1 + 1e-12

    def test_yolo_overflowing_is_clipped(self):
        assert f.yolo_to_norm_xyxy((0.95, 0.5, 0.2, 0.2)) == approx((0.85, 0.4, 1.0, 0.6))

    def test_negative_size_rejected(self):
        with pytest.raises(ValueError):
            f.yolo_to_norm_xyxy((0.5, 0.5, -0.1, 0.1))

    def test_format_line(self):
        assert f.format_yolo_line(2, (0.1, 0.2, 0.5, 0.6)) == "2 0.300000 0.400000 0.400000 0.400000"


class TestCoco:
    def test_px_to_coco(self):
        assert f.xyxy_px_to_coco((10, 20, 110, 70)) == approx((10, 20, 100, 50))

    def test_coco_to_px(self):
        assert f.coco_to_xyxy_px((10, 20, 100, 50)) == approx((10, 20, 110, 70))

    def test_norm_coco_roundtrip(self):
        norm = (0.1, 0.2, 0.35, 0.9)
        coco = f.norm_xyxy_to_coco(norm, W, H)
        assert coco == approx((192, 216, 480, 756), abs_=1e-6)
        assert f.coco_to_norm_xyxy(coco, W, H) == approx(norm)

    def test_negative_size_rejected(self):
        with pytest.raises(ValueError):
            f.coco_to_xyxy_px((0, 0, -5, 5))


class TestYoloCocoConsistency:
    @pytest.mark.parametrize(
        "box", [(0, 0, 1920, 1080), (1, 1, 2, 2), (500.5, 300.25, 1500.75, 1079.9)]
    )
    def test_same_box_through_both_formats(self, box):
        norm = f.xyxy_px_to_norm(box, W, H)
        via_yolo = f.yolo_to_xyxy_px(f.norm_xyxy_to_yolo(norm), W, H)
        via_coco = f.coco_to_xyxy_px(f.norm_xyxy_to_coco(norm, W, H))
        assert via_yolo == approx(box, abs_=1e-6)
        assert via_coco == approx(box, abs_=1e-6)


class TestHelpers:
    def test_area(self):
        assert f.box_area((0, 0, 10, 5)) == 50
        assert f.box_area((10, 10, 5, 5)) == 0

    def test_is_valid(self):
        assert f.is_valid_box((0, 0, 2, 2), min_size=1)
        assert not f.is_valid_box((0, 0, 0.5, 2), min_size=1)
        assert not f.is_valid_box((3, 3, 3, 9))
