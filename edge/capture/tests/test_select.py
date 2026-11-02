from lfcapture.select import EMPTY, INTERVAL, UNCERTAIN, VIOLATION, Detections, Selector, iou, similar
from tests.helpers import det_msg, item, make_config, track


def sel(tmp_path, **kw):
    defaults = {"CAPTURE_MIN_GAP_S": 1, "CAPTURE_INTERVAL_S": 10, "CAPTURE_EMPTY_INTERVAL_S": 300}
    return Selector(make_config(tmp_path, **{**defaults, **kw}))


def det(**kw):
    return Detections.from_message(det_msg(**kw))


def save_if(s, d, now):
    decision = s.decide(d, now)
    if decision.reason:
        s.mark_saved(d, decision.reason, now)
    return decision


def test_parse_ignores_other_messages_and_bad_boxes():
    assert Detections.from_message({"type": "camera_stats", "camera_id": 3}) is None
    d = Detections.from_message(det_msg(tracks=[track(), {"id": 2, "box": [0, 0]}],
                                        items=[item(), {"cls": "Mask", "box": None}]))  # fmt: skip
    assert len(d.tracks) == 1 and len(d.items) == 1 and d.frame_size == (1280, 720)


def test_iou_and_similar():
    a = (0.0, 0.0, 0.5, 0.5)
    assert iou(a, a) == 1.0 and iou(a, (0.5, 0.5, 1, 1)) == 0.0
    boxes = [("__person__", a), ("Helmet", (0.1, 0.0, 0.2, 0.1))]
    moved = [("__person__", (0.01, 0.0, 0.51, 0.5)), ("Helmet", (0.1, 0.0, 0.2, 0.1))]
    assert similar(boxes, list(reversed(moved)), 0.85)
    assert not similar(boxes, moved[:1], 0.85)
    assert not similar(boxes, [("__person__", a), ("Mask", (0.1, 0.0, 0.2, 0.1))], 0.85)


def test_priority_and_cooldowns(tmp_path):
    s = sel(tmp_path)
    viol = det(tracks=[track(missing=["Helmet"])], items=[item(score=0.4)])
    assert save_if(s, viol, 0).reason == VIOLATION
    assert s.decide(viol, 0.5).reason is None  # jeda minimum
    # track yang sama masih dalam jeda pelanggaran; box ragu yang bergeser jadi alasannya
    moved = det(tracks=[track(box=(0.1, 0.2, 0.2, 0.8), missing=["Helmet"])],
                items=[item(box=(0.12, 0.18, 0.18, 0.25), score=0.4)])  # fmt: skip
    assert save_if(s, moved, 3).reason == UNCERTAIN
    assert save_if(s, det(tracks=[track(box=(0.6, 0.2, 0.7, 0.8), missing=["Helmet"])]), 8.5).reason == VIOLATION


def test_interval_and_empty(tmp_path):
    s = sel(tmp_path)
    person = det(tracks=[track()], items=[item(score=0.9)])
    assert save_if(s, person, 0).reason == INTERVAL
    other = det(tracks=[track(box=(0.1, 0.2, 0.2, 0.8))], items=[item(score=0.9)])
    assert s.decide(other, 5).reason is None
    assert save_if(s, other, 10).reason == INTERVAL
    assert save_if(s, det(), 11).reason == EMPTY
    assert s.decide(det(), 200).reason is None
    assert s.decide(det(), 311).reason == EMPTY


def test_dedup_and_its_expiry(tmp_path):
    s = sel(tmp_path)
    still = det(tracks=[track()], items=[item(score=0.9)])
    save_if(s, still, 0)
    d = s.decide(still, 20)
    assert d.reason is None and d.skipped == "dedup"
    assert s.decide(still, 301).reason == INTERVAL  # adegan diam tetap disimpan sesekali


def test_quota_per_hour(tmp_path):
    s = sel(tmp_path, CAPTURE_MAX_PER_HOUR=2, CAPTURE_INTERVAL_S=1)
    for n in range(2):
        save_if(s, det(tracks=[track(box=(0.1 * n, 0.2, 0.1 * n + 0.05, 0.8))]), n * 2)
    d = s.decide(det(tracks=[track(box=(0.8, 0.2, 0.9, 0.8))]), 10)
    assert d.skipped == "quota"
    assert s.decide(det(tracks=[track(box=(0.8, 0.2, 0.9, 0.8))]), 3601).reason == INTERVAL


def test_cameras_are_independent(tmp_path):
    s = sel(tmp_path)
    save_if(s, det(camera_id=1, tracks=[track()]), 0)
    assert s.decide(det(camera_id=2, tracks=[track()]), 0.1).reason == INTERVAL
