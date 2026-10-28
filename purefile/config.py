"""Runtime configuration, read from ``PUREFILE_*`` environment variables (or ``.env``)."""

from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

MB = 1024 * 1024


class Settings(BaseSettings):
    """Application settings. Every field maps to ``PUREFILE_<FIELD_NAME>``."""

    model_config = SettingsConfigDict(env_prefix="PUREFILE_", env_file=".env", extra="ignore")

    max_image_mb: int = Field(50, ge=1, description="Maximum upload size for images, in MB.")
    max_video_mb: int = Field(1024, ge=1, description="Maximum upload size for videos, in MB.")
    file_ttl_seconds: int = Field(
        600, ge=30, description="Uploaded and cleaned files are deleted after this many seconds."
    )
    sweep_interval_seconds: int = Field(60, ge=5, description="How often the cleanup job runs.")
    tmp_dir: Path = Field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "purefile",
        description="Working directory for in-flight files. Never used for permanent storage.",
    )
    tool_timeout_seconds: int = Field(
        600, ge=10, description="Timeout for a single exiftool/ffmpeg/c2patool invocation."
    )
    max_concurrent_jobs: int = Field(
        4, ge=1, description="Files processed in parallel; further uploads wait their turn."
    )
    web_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[1] / "web",
        description="Directory containing the static frontend.",
    )

    exiftool_path: str = "exiftool"
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    c2patool_path: str = "c2patool"

    @property
    def max_image_bytes(self) -> int:
        return self.max_image_mb * MB

    @property
    def max_video_bytes(self) -> int:
        return self.max_video_mb * MB


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (cached; call ``cache_clear()`` in tests)."""
    return Settings()
