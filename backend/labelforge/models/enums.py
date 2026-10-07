from enum import StrEnum

# Disimpan sebagai string biasa di DB (bukan enum native) agar menambah nilai baru
# di fase berikutnya tidak butuh migrasi.


class TaskType(StrEnum):
    OBJECT_DETECTION = "object_detection"
    SEGMENTATION = "segmentation"  # Fase 4


class ImageStatus(StrEnum):
    UNLABELED = "unlabeled"
    AUTO_LABELED = "auto_labeled"
    REVIEWED = "reviewed"


class ShapeType(StrEnum):
    BBOX = "bbox"
    POLYGON = "polygon"  # Fase 4 (SAM)


class JobType(StrEnum):
    AUTOLABEL = "autolabel"
    TRAIN = "train"  # Fase 3


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobTarget(StrEnum):
    ALL = "all"
    UNLABELED = "unlabeled"
    SELECTED = "selected"


class JobItemStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    ERROR = "error"


SOURCE_MANUAL = "manual"
