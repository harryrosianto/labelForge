"""Inference model deteksi YOLO hasil export ONNX (mis. dari notebook Colab) dengan onnxruntime.

Tidak memakai library training (cukup numpy + onnxruntime), jadi bisa berjalan di CPU laptop.
Mendukung dua bentuk output:
- standar   [1, 4 + jumlah_class, N]  (cx, cy, w, h, skor per class), NMS dilakukan di sini;
- end2end   [1, N, 6]                 (x1, y1, x2, y2, skor, class), sudah tanpa duplikat.
Koordinat output berada di ruang gambar letterbox (input model), dikembalikan ke gambar asli.
"""

import ast
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

PAD_VALUE = 114  # warna padding letterbox standar YOLO


class OnnxModelError(ValueError):
    pass


@dataclass(frozen=True)
class OnnxModelInfo:
    names: list[str]  # nama class model, urut index
    input_size: tuple[int, int]  # (tinggi, lebar)
    end2end: bool
    description: str = ""

    def to_dict(self) -> dict:
        return {"names": self.names, "input_size": list(self.input_size), "end2end": self.end2end,
                "description": self.description}  # fmt: skip


def _session(path: str | Path):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.log_severity_level = 3
    return ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])


def _parse_literal(text: str | None, default):
    if not text:
        return default
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return default


def read_model_info(path: str | Path, session=None) -> OnnxModelInfo:
    """Baca & validasi model: harus model deteksi dengan satu input gambar [1, 3, H, W]."""
    try:
        session = session or _session(path)
    except Exception as e:  # file bukan ONNX / rusak
        raise OnnxModelError("File bukan model ONNX yang valid atau rusak") from e
    meta = session.get_modelmeta().custom_metadata_map or {}
    if meta.get("task", "detect") != "detect":
        raise OnnxModelError(f"Model untuk tugas '{meta['task']}', bukan deteksi objek (detect)")
    inputs, outputs = session.get_inputs(), session.get_outputs()
    if len(inputs) != 1 or len(inputs[0].shape) != 4:
        raise OnnxModelError("Model harus punya satu input gambar berbentuk [1, 3, tinggi, lebar]")

    shape = inputs[0].shape
    size = _parse_literal(meta.get("imgsz"), None)
    if isinstance(size, int):
        size = [size, size]
    if not size:
        if not all(isinstance(v, int) for v in shape[2:]):
            raise OnnxModelError("Ukuran input model dinamis dan tidak tercatat di metadata (imgsz)")
        size = shape[2:]
    out = outputs[0].shape
    end2end = str(meta.get("end2end", "")).lower() == "true" or (len(out) == 3 and out[-1] == 6)

    names_meta = _parse_literal(meta.get("names"), {})
    if isinstance(names_meta, dict) and names_meta:
        names = [str(names_meta[k]) for k in sorted(names_meta)]
    elif isinstance(names_meta, list) and names_meta:
        names = [str(n) for n in names_meta]
    elif not end2end and len(out) == 3 and isinstance(out[1], int) and out[1] > 4:
        names = [f"class{i}" for i in range(out[1] - 4)]
    else:
        raise OnnxModelError("Nama class tidak ditemukan di metadata model")
    if not end2end and len(out) == 3 and isinstance(out[1], int) and out[1] != 4 + len(names):
        raise OnnxModelError(f"Output model {out} tidak cocok dengan {len(names)} class")
    return OnnxModelInfo(names, (int(size[0]), int(size[1])), end2end, meta.get("description", ""))


def letterbox(image: Image.Image, size: tuple[int, int]) -> tuple[np.ndarray, float, tuple[float, float]]:
    """Resize dengan rasio tetap + padding di tengah. Hasil: (tensor 1x3xHxW float32, skala, (pad_x, pad_y))."""
    h, w = size
    scale = min(h / image.height, w / image.width)
    new_w, new_h = round(image.width * scale), round(image.height * scale)
    pad_x, pad_y = (w - new_w) / 2, (h - new_h) / 2
    canvas = Image.new("RGB", (w, h), (PAD_VALUE,) * 3)
    resized = image.resize((new_w, new_h), Image.Resampling.BILINEAR)
    canvas.paste(resized, (round(pad_x - 0.1), round(pad_y - 0.1)))
    tensor = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
    return np.ascontiguousarray(tensor), scale, (round(pad_x - 0.1), round(pad_y - 0.1))


def decode(
    output: np.ndarray,
    end2end: bool,
    score_threshold: float,
    scale: float,
    pad: tuple[float, float],
    max_det: int = 300,
) -> list[tuple[int, float, float, float, float, float]]:
    """Output model → [(index_class, x1, y1, x2, y2, skor)] di koordinat gambar asli."""
    out = np.asarray(output)[0]
    if end2end:
        boxes, scores, cls = out[:, :4], out[:, 4], out[:, 5].astype(int)
    else:
        pred = out.T  # [N, 4 + nc]
        class_scores = pred[:, 4:]
        cls = class_scores.argmax(axis=1)
        scores = class_scores[np.arange(len(pred)), cls]
        cx, cy, bw, bh = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
        boxes = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)
    keep = scores >= score_threshold
    boxes, scores, cls = boxes[keep], scores[keep], cls[keep]
    order = np.argsort(-scores)[: max_det * 10]  # NMS di provider; batasi kandidat
    px, py = pad
    boxes = (boxes[order] - np.array([px, py, px, py], dtype=np.float32)) / scale
    return [(int(c), float(b[0]), float(b[1]), float(b[2]), float(b[3]), float(s))
            for b, s, c in zip(boxes, scores[order], cls[order])]  # fmt: skip


class OnnxDetector:
    """Satu model ONNX yang sudah dimuat (dipakai provider model kustom)."""

    def __init__(self, path: str | Path):
        self.session = _session(path)
        self.info = read_model_info(path, self.session)
        self.input_name = self.session.get_inputs()[0].name

    def detect(self, image: Image.Image, score_threshold: float, max_det: int = 300):
        tensor, scale, pad = letterbox(image, self.info.input_size)
        output = self.session.run(None, {self.input_name: tensor})[0]
        return decode(output, self.info.end2end, score_threshold, scale, pad, max_det)
