from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Konfigurasi aplikasi, dibaca dari environment / file .env."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # Core
    database_url: str = "sqlite:///./data/labelforge.db"
    data_dir: Path = Path("./data")
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:5173"]

    # Inference
    device: str = "auto"  # auto | cpu | cuda | cuda:N
    use_fp16: bool = False
    gdino_model_id: str = "IDEA-Research/grounding-dino-base"
    gdino_box_threshold: float = 0.35
    gdino_text_threshold: float = 0.25
    owlv2_model_id: str = "google/owlv2-base-patch16-ensemble"
    owlv2_score_threshold: float = 0.2
    owlv2_nms_threshold: float = 0.3
    nms_iou_threshold: float = 0.5

    # Remote inference server (RemoteApiProvider)
    remote_inference_url: str | None = None
    remote_inference_token: str | None = None
    remote_inference_timeout: float = 120.0

    # Upload
    thumbnail_size: int = 320
    max_upload_mb: int = 2048


@lru_cache
def get_settings() -> Settings:
    return Settings()
