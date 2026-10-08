import cv2
import numpy as np
import pytest
from cryptography.fernet import Fernet

from labelforge.config import get_settings
from labelforge.media import rtsp
from labelforge.media.dedup import SimilarFilter, dhash, hamming
from labelforge.media.rtsp import CameraError, CaptureOptions, capture_frames
from labelforge.media.secrets import SecretKeyError, decrypt_url, encrypt_url, mask_url, scrub
from labelforge.media.video import ExtractOptions, VideoInfo, iter_frames, probe, sample_times
from labelforge.models import Image, Video

FPS = 10
URL = "rtsp://admin:Rahasia123@10.0.0.5:554/Streaming/101?token=abc"


def frame_for(i: int, w=160, h=120) -> np.ndarray:
    """Frame RGB: 0-19 statis (gudang sepi), 20+ kotak bergerak. Blok kiri atas = penanda indeks."""
    img = np.full((h, w, 3), 90, np.uint8)
    img[:16, :16] = (i * 4) % 256
    if i >= 20:
        x = 20 + (i - 20) * 3
        img[50:90, x:x + 30] = (220, 60, 40)
    return img


@pytest.fixture
def video_path(tmp_path):
    path = tmp_path / "cctv gudang.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (160, 120))
    for i in range(60):  # 6 detik
        writer.write(cv2.cvtColor(frame_for(i), cv2.COLOR_RGB2BGR))
    writer.release()
    return path


@pytest.fixture
def secret_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "secret_key", Fernet.generate_key().decode())


# --- dHash ---------------------------------------------------------------------


def test_dhash_similarity():
    a = frame_for(5)
    noisy = np.clip(a.astype(int) + np.random.default_rng(0).integers(-4, 5, a.shape), 0, 255).astype(np.uint8)
    moved = frame_for(40)
    assert hamming(dhash(a), dhash(a)) == 0
    assert hamming(dhash(a), dhash(noisy)) <= 6
    assert hamming(dhash(a), dhash(moved)) > 6
    assert len(dhash(a)) == 16


def test_similar_filter():
    f = SimilarFilter(threshold=6)
    hashes = [dhash(frame_for(i)) for i in (0, 5, 10, 30, 31, 45)]
    accepted = [f.accept(h) for h in hashes]
    assert accepted[0] and not accepted[1] and not accepted[2] and accepted[3]
    assert f.skipped == accepted.count(False)
    assert all(SimilarFilter(0).accept(h) for h in hashes[:2])  # 0 = nonaktif


# --- enkripsi & penyamaran URL --------------------------------------------------


def test_encrypt_roundtrip_and_mask(secret_key):
    token = encrypt_url(URL)
    assert "Rahasia123" not in token and decrypt_url(token) == URL
    assert mask_url(URL) == "rtsp://***@10.0.0.5:554/Streaming/101?token=***"
    assert mask_url("rtsp://10.0.0.5/live") == "rtsp://10.0.0.5/live"
    msg = scrub(f"gagal membuka {URL} (Rahasia123)", URL)
    assert "Rahasia123" not in msg and "admin" not in msg


def test_missing_or_changed_key(monkeypatch, secret_key):
    token = encrypt_url(URL)
    monkeypatch.setattr(get_settings(), "secret_key", Fernet.generate_key().decode())
    with pytest.raises(SecretKeyError, match="berubah"):
        decrypt_url(token)
    monkeypatch.setattr(get_settings(), "secret_key", None)
    with pytest.raises(SecretKeyError, match="belum diatur"):
        encrypt_url(URL)


# --- video ---------------------------------------------------------------------


def test_probe_and_sample_times(video_path):
    info = probe(str(video_path))
    assert (info.fps, info.frame_count, info.width, info.height) == (10, 60, 160, 120)
    assert info.duration_s == pytest.approx(6.0)
    assert sample_times(info, ExtractOptions(every_s=1)) == [0, 1, 2, 3, 4, 5]
    assert len(sample_times(info, ExtractOptions(fps=2))) == 12
    assert sample_times(info, ExtractOptions(every_s=1, start_s=2.5, end_s=4.6)) == [2.5, 3.5, 4.5]
    assert len(sample_times(info, ExtractOptions(every_s=0.1, max_frames=7))) == 7
    with pytest.raises(ValueError):
        ExtractOptions(every_s=1, start_s=3, end_s=2)


def test_iter_frames_returns_frame_at_requested_time(video_path):
    times = [0.0, 1.5, 3.2, 5.9]
    got = dict(iter_frames(str(video_path), times, FPS))
    for t in times:
        index = round(t * FPS)
        marker = got[t][:16, :16].mean()
        assert abs(marker - (index * 4) % 256) <= 8, (t, marker)


# --- API video -------------------------------------------------------------------


def test_video_upload_extract_with_dedup(client, project, db, video_path, storage):
    pid = project["id"]
    with open(video_path, "rb") as f:
        r = client.post(f"/api/projects/{pid}/videos", files={"file": ("cctv gudang.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    video = r.json()
    assert (video["fps"], video["frame_count"], video["width"]) == (10, 60, 160)

    opts = {"every_s": 0.5, "dedup_threshold": 6}
    assert client.post(f"/api/videos/{video['id']}/extract/preview", json=opts).json() == {"frames": 12}
    job = client.post(f"/api/videos/{video['id']}/extract", json=opts).json()
    job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["job_type"] == "video_extract" and job["status"] == "completed", job
    res = job["result"]
    # 0-2 detik statis: hanya frame pertama yang disimpan
    assert res["sampled"] == 12 and res["skipped_similar"] >= 3
    assert res["frames_added"] == 12 - res["skipped_similar"] - res["duplicates"]

    images = client.get(f"/api/projects/{pid}/images", params={"source_type": "video"}).json()["items"]
    assert len(images) == res["frames_added"]
    first = min(images, key=lambda i: i["frame_time_s"])
    assert first["frame_time_s"] == 0 and first["source_label"] == "cctv gudang.mp4"
    assert first["status"] == "unlabeled" and first["original_filename"].startswith("cctv_gudang_t")
    assert all(db.get(Image, i["id"]).dhash for i in images)

    # hapus video: file hilang, frame tetap
    key = db.get(Video, video["id"]).storage_key
    assert storage.exists(key)
    assert client.delete(f"/api/videos/{video['id']}").status_code == 204
    assert not storage.exists(key)
    assert client.get(f"/api/projects/{pid}/images", params={"source_type": "video"}).json()["total"] == len(images)
    assert client.get(f"/api/projects/{pid}/videos").json() == []


def test_video_upload_errors(client, project):
    pid = project["id"]
    r = client.post(f"/api/projects/{pid}/videos", files={"file": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 422 and "Format video" in r.json()["detail"]
    r = client.post(f"/api/projects/{pid}/videos", files={"file": ("rusak.mp4", b"bukan video", "video/mp4")})
    assert r.status_code == 422


# --- RTSP ------------------------------------------------------------------------


class FakeCamera:
    """Kamera tiruan: tiap grab menggerakkan jam 0.1 dtk; bisa putus setelah n grab."""

    opened = 0

    def __init__(self, clock, fail_after=None, never_open=False):
        FakeCamera.opened += 1
        self.clock, self.fail_after, self.never_open, self.grabs = clock, fail_after, never_open, 0

    def isOpened(self):  # noqa: N802
        return not self.never_open

    def grab(self):
        self.grabs += 1
        self.clock.t += 0.1
        return self.fail_after is None or self.grabs <= self.fail_after

    def retrieve(self):
        return True, cv2.cvtColor(frame_for(20 + int(self.clock.t * 2)), cv2.COLOR_RGB2BGR)

    def release(self):
        pass


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_capture_interval_and_duration():
    clock = Clock()
    frames = list(capture_frames(URL, CaptureOptions(interval_s=1.0, duration_s=5.0, dedup_threshold=0),
                                 opener=lambda *a: FakeCamera(clock), clock=clock, sleep=lambda s: None))  # fmt: skip
    assert len(frames) == 5 and frames[0].shape == (120, 160, 3)
    clock2 = Clock()
    limited = list(capture_frames(URL, CaptureOptions(interval_s=0.5, duration_s=None, max_frames=3),
                                  opener=lambda *a: FakeCamera(clock2), clock=clock2, sleep=lambda s: None))  # fmt: skip
    assert len(limited) == 3


def test_capture_reconnects_then_gives_up():
    clock = Clock()
    cams = iter([FakeCamera(clock, fail_after=12), FakeCamera(clock)])
    reconnects = []
    frames = list(capture_frames(URL, CaptureOptions(interval_s=1.0, duration_s=4.0), opener=lambda *a: next(cams),
                                 clock=clock, sleep=lambda s: None, on_reconnect=reconnects.append))  # fmt: skip
    assert reconnects == [1] and len(frames) >= 3

    with pytest.raises(CameraError, match="2 percobaan"):
        list(capture_frames(URL, CaptureOptions(duration_s=4.0, reconnect_attempts=2),
                            opener=lambda *a: FakeCamera(clock, never_open=True), clock=clock, sleep=lambda s: None))  # fmt: skip


def test_capture_options_need_limit():
    with pytest.raises(ValueError):
        CaptureOptions(duration_s=None, max_frames=None)


# --- API kamera ----------------------------------------------------------------------


def test_camera_requires_secret_key(client, project, monkeypatch):
    monkeypatch.setattr(get_settings(), "secret_key", None)
    r = client.post(f"/api/projects/{project['id']}/cameras", json={"name": "Dock 1", "url": URL})
    assert r.status_code == 422 and "SECRET_KEY" in r.json()["detail"]


def test_camera_crud_never_exposes_credentials(client, project, secret_key):
    pid = project["id"]
    assert client.post(f"/api/projects/{pid}/cameras", json={"name": "x", "url": "ftp://a"}).status_code == 422
    r = client.post(f"/api/projects/{pid}/cameras", json={"name": "  Dock   1 ", "url": URL})
    assert r.status_code == 201
    cam = r.json()
    assert cam["name"] == "Dock 1" and cam["url_masked"] == "rtsp://***@10.0.0.5:554/Streaming/101?token=***"
    listed = client.get(f"/api/projects/{pid}/cameras").text
    assert "Rahasia123" not in listed and "url_encrypted" not in listed and "abc" not in listed
    assert client.delete(f"/api/cameras/{cam['id']}").status_code == 204


def test_camera_test_and_capture_job(client, project, secret_key, monkeypatch, db):
    pid = project["id"]
    cam = client.post(f"/api/projects/{pid}/cameras", json={"name": "Dock 1", "url": URL}).json()

    clock = Clock()
    monkeypatch.setattr(rtsp, "open_capture", lambda *a: FakeCamera(clock))
    monkeypatch.setattr(rtsp, "_now", clock)
    monkeypatch.setattr(rtsp, "_sleep", lambda s: None)

    t = client.post(f"/api/cameras/{cam['id']}/test").json()
    assert t["ok"] and (t["width"], t["height"]) == (160, 120) and t["preview"].startswith("data:image/jpeg")

    job = client.post(f"/api/cameras/{cam['id']}/capture",
                      json={"interval_s": 1, "duration_s": 6, "dedup_threshold": 0}).json()  # fmt: skip
    job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "completed", job
    assert job["result"]["frames_added"] >= 5
    imgs = client.get(f"/api/projects/{pid}/images", params={"source_type": "rtsp"}).json()["items"]
    assert len(imgs) == job["result"]["frames_added"]
    assert imgs[0]["source_label"] == "Dock 1" and imgs[0]["original_filename"].startswith("Dock_1_")
    assert "Rahasia123" not in str(job["payload"])


def test_capture_failure_message_has_no_credentials(client, project, secret_key, monkeypatch):
    cam = client.post(f"/api/projects/{project['id']}/cameras", json={"name": "Dock 2", "url": URL}).json()
    monkeypatch.setattr(rtsp, "open_capture", lambda *a: FakeCamera(Clock(), never_open=True))
    monkeypatch.setattr(rtsp, "_sleep", lambda s: None)
    t = client.post(f"/api/cameras/{cam['id']}/test").json()
    assert not t["ok"] and "tidak bisa dihubungi" in t["error"]
    job = client.post(f"/api/cameras/{cam['id']}/capture", json={"duration_s": 5, "reconnect_attempts": 1}).json()
    job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "failed" and "Rahasia123" not in job["error"] and "admin" not in job["error"]


def test_capture_without_any_frame_fails(client, project, secret_key, monkeypatch):
    """Kamera tersambung tapi stream tidak pernah memberi frame → job gagal, bukan selesai 0 frame."""
    cam = client.post(f"/api/projects/{project['id']}/cameras", json={"name": "Kosong", "url": URL}).json()
    clock = Clock()
    monkeypatch.setattr(rtsp, "open_capture", lambda *a: FakeCamera(clock, fail_after=0))
    monkeypatch.setattr(rtsp, "_now", clock)
    monkeypatch.setattr(rtsp, "_sleep", lambda s: setattr(clock, "t", clock.t + s))
    job = client.post(f"/api/cameras/{cam['id']}/capture", json={"duration_s": 20, "reconnect_attempts": 20}).json()
    job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "failed" and "Tidak ada frame" in job["error"]
