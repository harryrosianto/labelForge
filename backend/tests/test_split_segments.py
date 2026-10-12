from datetime import datetime, timedelta, timezone

import pytest

from labelforge.exporters.split import split_groups
from labelforge.models import Image
from labelforge.versions.segments import ImageMeta, frame_key, segment_groups
from tests.test_api_images import upload
from tests.test_images_service import make_jpeg


def meta(id, name, source_type="import", source_id=None, t=None, captured=None):
    return ImageMeta(id, source_type, source_id, name, t, captured)


@pytest.mark.parametrize("name,source,position", [
    ("kamera3_757_jpg.rf.9e033beb38a248d0feea9e3cfea56ae3.jpg", "kamera3", 757),
    ("kamera3_758.JPG", "kamera3", 758),
    ("s06_with_pallet_20260930_082450_0001.jpg", "s06", 1),
    ("IMG-1234.png", "img", 1234),
])  # fmt: skip
def test_frame_key_from_filename(name, source, position):
    s, pos, _ = frame_key(meta(1, name))
    assert (s, pos) == (source, position)


def test_copies_of_same_frame_share_identity():
    a = frame_key(meta(1, "kamera3_758_jpg.rf.46ce7079.jpg"))[2]
    b = frame_key(meta(2, "kamera3_758_jpg.rf.c60ecd6f.jpg"))[2]
    c = frame_key(meta(3, "kamera3_759_jpg.rf.c60ecd6f.jpg"))[2]
    assert a == b != c


def test_frame_key_video_and_rtsp():
    assert frame_key(meta(1, "x.jpg", "video", 4, t=12.5))[:2] == ("video:4", 12.5)
    at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert frame_key(meta(2, "y.jpg", "rtsp", 2, captured=at))[:2] == ("rtsp:2", at.timestamp())
    assert frame_key(meta(3, "tanpa-nomor.jpg"))[2] == "id:3"  # tanpa nomor: frame sendiri


def test_segment_groups_consecutive_blocks_and_copies():
    metas = [meta(i, f"kam_{n}.jpg") for i, n in enumerate([5, 1, 3, 2, 4, 6], start=1)]
    metas.append(meta(7, "kam_2_jpg.rf.abc.jpg"))  # salinan frame 2
    metas.append(meta(8, "lain_1.jpg"))
    groups, strata = segment_groups(metas, segment_size=2)
    assert strata == ["kam", "kam", "kam", "lain"]
    # id 1..6 = frame 5,1,3,2,4,6 → blok frame 1-2 (id 2,4 + salinan 7), 3-4 (id 3,5), 5-6 (id 1,6)
    assert [sorted(g) for g in groups] == [[2, 4, 7], [3, 5], [1, 6], [8]]


def test_split_groups_keeps_groups_whole_and_balances_per_source():
    groups, strata = [], []
    for cam in ("a", "b", "c"):
        for k in range(10):
            groups.append([hash((cam, k, j)) & 0xFFFFFF for j in range(10)])
            strata.append(cam)
    out = split_groups(groups, strata, {"train": 0.8, "val": 0.2, "test": 0}, seed=3)
    where = {i: s for s, ids in out.items() for i in ids}
    for g in groups:
        assert len({where[i] for i in g}) == 1  # grup tidak pernah dipecah
    for cam in ("a", "b", "c"):
        val = sum(1 for g, s in zip(groups, strata) if s == cam and where[g[0]] == "val")
        assert val == 2  # 20% dari 10 blok di setiap kamera
    assert out == split_groups(groups, strata, {"train": 0.8, "val": 0.2, "test": 0}, seed=3)


def test_split_groups_small_dataset_gets_val():
    out = split_groups([[1, 2, 3], [4]], ["a", "a"], {"train": 0.9, "val": 0.1, "test": 0})
    assert out["val"] and out["train"] and not out["test"]
    with pytest.raises(ValueError):
        split_groups([[1]], ["a"], {"train": 0, "val": 0, "test": 0})


def test_version_segment_split_api(client, project, db):
    pid = project["id"]
    cid = client.post(f"/api/projects/{pid}/classes", json={"name": "pallet"}).json()["id"]
    files = [(f"cam_{n}.jpg", make_jpeg((32, 32), (n * 9, 50, 90))) for n in range(1, 21)]
    ids = [i["id"] for i in upload(client, pid, *files).json()["uploaded"]]
    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for k, iid in enumerate(ids):
        img = db.get(Image, iid)
        img.status = "reviewed"
        if k >= 10:  # 10 gambar terakhir dianggap capture kamera RTSP
            img.source_type, img.source_id, img.captured_at = "rtsp", 7, base + timedelta(seconds=k)
    db.commit()
    assert cid

    body = {"reviewed_only": True, "split_mode": "segment", "segment_size": 5,
            "split": {"train": 0.5, "val": 0.5, "test": 0}}  # fmt: skip
    preview = client.post(f"/api/projects/{pid}/versions/preview", json=body).json()
    assert preview["split_groups"] == {"mode": "segment", "segment_size": 5, "groups": 4,
                                       "sources": 2, "frames": 20}  # fmt: skip
    assert preview["splits"] == {"train": 10, "val": 10, "test": 0}

    v = client.post(f"/api/projects/{pid}/versions", json={"name": "seg", **body}).json()
    assert v["config"]["split_mode"] == "segment" and v["summary"]["split_groups"]["groups"] == 4
    random_preview = client.post(f"/api/projects/{pid}/versions/preview", json={"reviewed_only": True}).json()
    assert random_preview["split_groups"] is None
    bad = client.post(f"/api/projects/{pid}/versions/preview", json={**body, "segment_size": 0})
    assert bad.status_code == 422
