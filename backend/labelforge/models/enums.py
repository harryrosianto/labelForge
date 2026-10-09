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
    IMPORT = "import"
    VERSION_BUILD = "version_build"
    VIDEO_EXTRACT = "video_extract"
    RTSP_CAPTURE = "rtsp_capture"
    EXPORT = "export"
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


class ImageSource(StrEnum):
    UPLOAD = "upload"
    IMPORT = "import"
    VIDEO = "video"
    RTSP = "rtsp"


class VersionStatus(StrEnum):
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


class ImportStatus(StrEnum):
    ANALYZED = "analyzed"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"


SOURCE_MANUAL = "manual"
