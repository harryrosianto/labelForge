from typing import Any

from PIL import Image

from labelforge.config import get_settings
from labelforge.providers.base import (
    require_ml_deps,
    ClassDef,
    Detection,
    LabelingProvider,
    ParamSpec,
    load_image,
)
from labelforge.providers.registry import register_provider

TEXT = "text"
IMAGE_GUIDED = "image_guided"
# "a photo of a " + frasa harus muat 16 token; ~8 kata adalah batas aman.
MAX_QUERY_WORDS = 8


@register_provider
class Owlv2Provider(LabelingProvider):
    """OWLv2: deteksi berdasarkan teks atau contoh visual (exemplar crop)."""

    name = "owlv2"
    label = "OWLv2"
    modes = (TEXT, IMAGE_GUIDED)
    per_class_nms_param = "nms_threshold"

    @classmethod
    def param_specs(cls, mode: str) -> list[ParamSpec]:
        s = get_settings()
        default_score = s.owlv2_score_threshold if mode == TEXT else s.owlv2_image_score_threshold
        specs = [
            ParamSpec("score_threshold", "float", default_score, "Score threshold",
                      min=0.0, max=1.0, step=0.01),
            ParamSpec("nms_threshold", "float", s.owlv2_nms_threshold, "IoU NMS per class",
                      min=0.05, max=1.0, step=0.05),
        ]  # fmt: skip
        if mode == IMAGE_GUIDED:
            specs.append(ParamSpec("max_exemplars", "int", 5, "Maks. exemplar per class",
                                   "Tiap exemplar = satu forward pass; batasi agar tetap cepat",
                                   min=1, max=50, step=1))  # fmt: skip
        return specs

    @classmethod
    def source_tag(cls, mode: str) -> str:
        return "ai:owlv2_image" if mode == IMAGE_GUIDED else "ai:owlv2_text"

    @classmethod
    def class_warnings(cls, mode: str, classes: list[ClassDef]) -> list[str]:
        if mode != IMAGE_GUIDED:
            # Query teks OWLv2 dibatasi 16 token; kalimat panjang dipotong dan akurasinya buruk.
            return [
                f"Prompt class '{c.name}' terlalu panjang dan akan dipotong: \"{p}\". "
                "OWLv2 paling akurat dengan frasa benda singkat, mis. \"cardboard box\"."
                for c in classes
                for p in c.prompts
                if len(p.split()) > MAX_QUERY_WORDS
            ]
        return [
            f"Class '{c.name}' tidak punya contoh visual, dilewati pada mode image-guided"
            for c in classes
            if not c.exemplar_paths
        ]

    def _load(self) -> None:
        require_ml_deps("torch", "torchvision", "transformers")
        import torch
        from transformers import Owlv2ForObjectDetection, Owlv2Processor

        from labelforge.core.device import resolve_device, resolve_dtype

        s = get_settings()
        self.device = resolve_device(s.device)
        self.dtype = resolve_dtype(self.device, s.use_fp16)
        self.processor = Owlv2Processor.from_pretrained(s.owlv2_model_id)
        self.model = (
            Owlv2ForObjectDetection.from_pretrained(s.owlv2_model_id, dtype=self.dtype)
            .to(self.device)
            .eval()
        )
        self._torch = torch

    def _to_device(self, inputs) -> dict:
        out = {}
        for key, value in dict(inputs).items():
            value = value.to(self.device)
            if key in ("pixel_values", "query_pixel_values") and self.dtype != self._torch.float32:
                value = value.to(self.dtype)
            out[key] = value
        return out

    def _detect(
        self, image: Image.Image, classes: list[ClassDef], params: dict[str, Any]
    ) -> list[Detection]:
        if params["mode"] == IMAGE_GUIDED:
            return self._detect_image_guided(image, classes, params)
        return self._detect_text(image, classes, params)

    def _text_inputs(self, image: Image.Image, classes: list[ClassDef]) -> tuple[dict, list[int]]:
        """Input model untuk mode teks. Satu query per frasa sinonim; list kedua memetakan
        indeks query → class_id."""
        queries, query_class = [], []
        for c in classes:
            for phrase in c.prompts:
                queries.append(f"a photo of a {phrase.lower()}")
                query_class.append(c.id)
        # padding + truncation: tiap query panjangnya beda dan dibatasi 16 token oleh model.
        inputs = self.processor(text=[queries], images=image, return_tensors="pt",
                                padding="max_length", truncation=True)  # fmt: skip
        return self._to_device(inputs), query_class

    def _detect_text(
        self, image: Image.Image, classes: list[ClassDef], params: dict[str, Any]
    ) -> list[Detection]:
        torch = self._torch
        inputs, query_class = self._text_inputs(image, classes)
        with torch.inference_mode():
            outputs = self.model(**inputs)
        result = self.processor.post_process_grounded_object_detection(
            outputs, threshold=params["score_threshold"], target_sizes=[(image.height, image.width)]
        )[0]
        return [
            Detection(query_class[int(label)], tuple(box), float(score))
            for box, score, label in zip(
                result["boxes"].tolist(), result["scores"].tolist(), result["labels"].tolist()
            )
        ]

    # --- image-guided -----------------------------------------------------------
    #
    # Tidak memakai `model.image_guided_detection` + `post_process_image_guided_detection`
    # bawaan HF karena (dicek pada transformers 5.19, foto gudang asli):
    # 1. Embedding query diambil dari box dengan objectness tertinggi di gambar exemplar,
    #    yang sering hanya sebagian objek (IoU ~0.4 terhadap crop). Untuk exemplar berupa crop,
    #    yang benar adalah box yang menutupi seluruh crop.
    # 2. Skor post-process adalah "alpha" relatif (box terbaik selalu 1.0), dan sigmoid logit
    #    mentah jenuh (ratusan box > 0.99) → threshold tidak bermakna.
    # Di sini: embedding query dipilih berdasarkan IoU, skor = cosine similarity (maks. atas
    # semua exemplar class), dan fitur gambar target dihitung sekali per gambar.

    def _image_features(self, image: Image.Image):
        """(class_embeds ternormalisasi [P,D], boxes xyxy relatif persegi ter-pad [P,4], objectness [P])."""
        torch = self._torch
        pixel_values = self._to_device(self.processor(images=image, return_tensors="pt"))[
            "pixel_values"
        ]
        with torch.inference_mode():
            feature_map = self.model.image_embedder(pixel_values=pixel_values)[0]
            b, h, w, d = feature_map.shape
            feats = feature_map.reshape(b, h * w, d)
            boxes = self.model.box_predictor(feats, feature_map)[0].float()
            _, class_embeds = self.model.class_predictor(feats)
            objectness = self.model.objectness_predictor(feats)[0].float()
        embeds = class_embeds[0].float()
        embeds = embeds / (embeds.norm(dim=-1, keepdim=True) + 1e-6)
        cx, cy, bw, bh = boxes.unbind(-1)
        xyxy = torch.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], dim=-1)
        return embeds, xyxy, objectness

    def _exemplar_embedding(self, path):
        """Embedding satu exemplar crop, di-cache per (path, mtime) selama proses hidup."""
        key = (str(path), path.stat().st_mtime_ns)
        cache = self.__dict__.setdefault("_exemplar_cache", {})
        if key not in cache:
            torch = self._torch
            crop = load_image(path)
            embeds, boxes, objectness = self._image_features(crop)
            # Crop menempati [0, 0, w/s, h/s] di gambar persegi ter-pad (pad kanan/bawah).
            s = max(crop.size)
            full = torch.tensor([0.0, 0.0, crop.width / s, crop.height / s], device=boxes.device)
            lt = torch.maximum(boxes[:, :2], full[:2])
            rb = torch.minimum(boxes[:, 2:], full[2:])
            inter = (rb - lt).clamp(min=0).prod(-1)
            area = (boxes[:, 2:] - boxes[:, :2]).clamp(min=0).prod(-1)
            iou = inter / (area + (full[2] * full[3]) - inter + 1e-6)
            # Kandidat = box yang hampir menutupi seluruh crop; pilih yang objectness-nya tertinggi.
            candidates = (iou >= iou.max() * 0.8).nonzero()[:, 0]
            best = candidates[objectness[candidates].argmax()]
            if len(cache) > 256:
                cache.clear()
            cache[key] = embeds[best]
        return cache[key]

    def _detect_image_guided(
        self, image: Image.Image, classes: list[ClassDef], params: dict[str, Any]
    ) -> list[Detection]:
        torch = self._torch
        with_exemplars = [c for c in classes if c.exemplar_paths]
        if not with_exemplars:
            return []
        embeds, boxes, _ = self._image_features(image)
        boxes = boxes * max(image.width, image.height)  # relatif persegi ter-pad → pixel

        detections: list[Detection] = []
        for cls in with_exemplars:
            queries = torch.stack(
                [self._exemplar_embedding(p) for p in cls.exemplar_paths[: params["max_exemplars"]]]
            )
            scores = (embeds @ queries.T).max(dim=-1).values
            keep = scores >= params["score_threshold"]
            for box, score in zip(boxes[keep].tolist(), scores[keep].tolist()):
                detections.append(Detection(cls.id, tuple(box), float(score)))
        return detections
