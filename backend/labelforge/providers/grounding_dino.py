from typing import Any

from PIL import Image

from labelforge.config import get_settings
from labelforge.providers.base import ClassDef, Detection, LabelingProvider, ParamSpec
from labelforge.providers.gdino_mapping import build_prompt, map_label_to_class, split_batches
from labelforge.providers.registry import register_provider


@register_provider
class GroundingDinoProvider(LabelingProvider):
    """Zero-shot detection berbasis teks (IDEA-Research Grounding DINO via transformers)."""

    name = "grounding_dino"
    label = "Grounding DINO"
    modes = ("text",)
    per_class_nms_param = "nms_iou"

    @classmethod
    def param_specs(cls, mode: str) -> list[ParamSpec]:
        s = get_settings()
        return [
            ParamSpec("box_threshold", "float", s.gdino_box_threshold, "Box threshold",
                      "Skor minimum sebuah box", min=0.01, max=1.0, step=0.01),
            ParamSpec("text_threshold", "float", s.gdino_text_threshold, "Text threshold",
                      "Skor minimum token teks untuk menentukan label", min=0.01, max=1.0,
                      step=0.01),
            ParamSpec("nms_iou", "float", s.nms_iou_threshold, "IoU NMS per class",
                      min=0.05, max=1.0, step=0.05),
        ]  # fmt: skip

    @classmethod
    def is_available(cls) -> tuple[bool, str | None]:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError as e:
            return False, f"dependency ML belum terpasang ({e.name}); pip install -e .[ml]"
        return True, None

    def _load(self) -> None:
        import torch
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        from labelforge.core.device import resolve_device, resolve_dtype

        s = get_settings()
        self.device = resolve_device(s.device)
        self.dtype = resolve_dtype(self.device, s.use_fp16)
        self.processor = AutoProcessor.from_pretrained(s.gdino_model_id)
        self.model = (
            AutoModelForZeroShotObjectDetection.from_pretrained(s.gdino_model_id, dtype=self.dtype)
            .to(self.device)
            .eval()
        )
        self.max_text_len = int(getattr(self.model.config, "max_text_len", 256))
        self._torch = torch

    def _count_tokens(self, text: str) -> int:
        return len(self.processor.tokenizer(text)["input_ids"])

    def _detect(
        self, image: Image.Image, classes: list[ClassDef], params: dict[str, Any]
    ) -> list[Detection]:
        detections: list[Detection] = []
        for batch in split_batches(classes, self._count_tokens, self.max_text_len):
            detections.extend(self._detect_batch(image, batch, params))
        return detections

    def _detect_batch(
        self, image: Image.Image, classes: list[ClassDef], params: dict[str, Any]
    ) -> list[Detection]:
        torch = self._torch
        prompt = build_prompt(classes)
        inputs = self.processor(images=image, text=prompt, return_tensors="pt").to(self.device)
        if self.dtype != torch.float32:
            inputs["pixel_values"] = inputs["pixel_values"].to(self.dtype)
        with torch.inference_mode():
            outputs = self.model(**inputs)
        result = self.processor.post_process_grounded_object_detection(
            outputs,
            inputs["input_ids"],
            threshold=params["box_threshold"],
            text_threshold=params["text_threshold"],
            target_sizes=[(image.height, image.width)],
        )[0]
        labels = result.get("text_labels") or result["labels"]

        detections = []
        for box, score, label in zip(result["boxes"].tolist(), result["scores"].tolist(), labels):
            class_id = map_label_to_class(str(label), classes)
            if class_id is not None:
                detections.append(Detection(class_id, tuple(box), float(score)))
        return detections
