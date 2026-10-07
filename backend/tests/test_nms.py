from labelforge.core.nms import apply_nms, batched_nms, nms
from labelforge.providers.base import Detection


def test_nms_removes_overlap_keeps_highest():
    boxes = [(0, 0, 10, 10), (1, 1, 11, 11), (50, 50, 60, 60)]
    assert nms(boxes, [0.6, 0.9, 0.5], iou_threshold=0.5) == [1, 2]


def test_nms_keeps_when_below_threshold():
    boxes = [(0, 0, 10, 10), (5, 0, 15, 10)]  # IoU = 1/3
    assert nms(boxes, [0.9, 0.8], iou_threshold=0.5) == [0, 1]
    assert nms(boxes, [0.9, 0.8], iou_threshold=0.3) == [0]


def test_nms_empty_and_degenerate():
    assert nms([], [], 0.5) == []
    # box berukuran nol tidak menyebabkan pembagian nol
    assert nms([(0, 0, 0, 0), (0, 0, 0, 0)], [0.5, 0.4], 0.5) == [0, 1]


def test_batched_nms_is_per_class():
    boxes = [(0, 0, 10, 10), (0, 0, 10, 10), (0, 0, 10, 10)]
    keep = batched_nms(boxes, [0.9, 0.8, 0.7], groups=[1, 2, 1], iou_threshold=0.5)
    assert keep == [0, 1]


def _d(cid, box, conf):
    return Detection(cid, box, conf)


def test_apply_nms_per_class_then_class_agnostic():
    dets = [
        _d(1, (0, 0, 100, 100), 0.9),   # pallet
        _d(1, (2, 2, 100, 100), 0.6),   # duplikat pallet
        _d(2, (1, 1, 100, 100), 0.7),   # "person" di tempat yang sama
        _d(2, (300, 300, 400, 400), 0.8),
    ]  # fmt: skip
    per_class = apply_nms(dets, per_class_iou=0.5)
    assert [(d.class_id, d.confidence) for d in per_class] == [(1, 0.9), (2, 0.8), (2, 0.7)]

    both = apply_nms(dets, per_class_iou=0.5, class_agnostic_iou=0.5)
    assert [(d.class_id, d.confidence) for d in both] == [(1, 0.9), (2, 0.8)]


def test_apply_nms_disabled():
    dets = [_d(1, (0, 0, 10, 10), 0.5), _d(1, (0, 0, 10, 10), 0.9)]
    assert [d.confidence for d in apply_nms(dets, None, None)] == [0.9, 0.5]
