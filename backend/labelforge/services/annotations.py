from sqlalchemy import delete
from sqlalchemy.orm import Session

from labelforge.core.formats import xyxy_px_to_norm
from labelforge.models import Annotation, Image
from labelforge.models.enums import ImageStatus
from labelforge.providers.base import Detection


def apply_ai_detections(
    db: Session, image: Image, detections: list[Detection], source: str, job_id: int | None
) -> int:
    """Ganti anotasi AI yang belum di-approve dengan hasil deteksi baru.

    Anotasi manual dan anotasi yang sudah di-approve tidak disentuh. Gambar yang sudah
    `reviewed` tetap `reviewed`; selain itu menjadi `auto_labeled`. Caller yang commit.
    """
    db.execute(
        delete(Annotation).where(
            Annotation.image_id == image.id,
            Annotation.source.startswith("ai:"),
            Annotation.is_approved.is_(False),
        )
    )
    for det in detections:
        x1, y1, x2, y2 = xyxy_px_to_norm(det.bbox, image.width, image.height)
        db.add(
            Annotation(
                image_id=image.id,
                class_id=det.class_id,
                x_min=x1,
                y_min=y1,
                x_max=x2,
                y_max=y2,
                source=source,
                confidence=det.confidence,
                is_approved=False,
                job_id=job_id,
            )
        )
    if image.status != ImageStatus.REVIEWED:
        image.status = ImageStatus.AUTO_LABELED
    return len(detections)
