"""Application-wide settings (local only, no cloud defaults)."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Covers 200% zoom: map popup 360px, timeline gallery 336px.
DEFAULT_THUMBNAIL_SIZE = 384


class AppSettings(BaseSettings):
    """Runtime settings loaded from environment or optional TOML later."""

    model_config = SettingsConfigDict(env_prefix="TRAVELJOURNAL_", extra="ignore")

    projects_root: str | None = Field(
        default=None,
        description="Default parent folder for creating and opening projects.",
    )

    @field_validator("projects_root", mode="before")
    @classmethod
    def _blank_projects_root(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    default_thumbnail_size: int = Field(default=DEFAULT_THUMBNAIL_SIZE, ge=64, le=1024)
    hash_chunk_size: int = Field(default=1024 * 1024, ge=4096)
    stay_radius_meters: float = Field(default=150.0, gt=0)
    stay_min_duration_minutes: int = Field(default=30, ge=1)
    gps_match_max_delta_seconds: int = Field(default=120, ge=1)
    allow_network_services: bool = Field(
        default=False,
        description="Cloud/AI services stay disabled until explicitly enabled.",
    )
    worker_count: int = Field(
        default=0,
        ge=0,
        le=64,
        description="Process-pool size. 0 means CPU count minus one.",
    )

    @property
    def user_config_dir(self) -> Path:
        return Path.home() / "AppData" / "Local" / "TravelJournal"
