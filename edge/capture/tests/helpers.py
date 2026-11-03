from pathlib import Path

from lfcapture.config import load_config

BASE_ENV = {
    "SG_URL": "https://127.0.0.1:8080",
    "SG_USERNAME": "perekam",
    "SG_PASSWORD": "rahasia-uji",
}


def make_config(out_dir: Path, **overrides):
    # Batas disk dilonggarkan: isi disk mesin yang menjalankan test tidak boleh memengaruhi hasil.
    env = {**BASE_ENV, "CAPTURE_DIR": str(out_dir), "CAPTURE_DISK_MAX_USED_PCT": "100",
           "CAPTURE_DISK_MIN_FREE_MB": "0"}  # fmt: skip
    env.update({k: str(v) for k, v in overrides.items()})
    return load_config(env)


def det_msg(camera_id=3, ts=1762156712.5, tracks=(), items=(), size=(1280, 720)) -> dict:
    return {"type": "detections", "camera_id": camera_id, "ts": ts, "frame_size": list(size),
            "tracks": list(tracks), "items": list(items), "zones": {}, "lines": {}}


def track(tid=1, box=(0.4, 0.2, 0.5, 0.8), score=0.9, missing=(), name="Budi"):
    return {"id": tid, "box": list(box), "score": score, "kpts": [], "name": name, "face": None,
            "ppe_missing": list(missing), "safety": []}


def item(cls="Helmet", box=(0.42, 0.18, 0.48, 0.25), score=0.8):
    return {"cls": cls, "box": list(box), "score": score}


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"
