"""Application-wide settings (local only, no cloud defaults)."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Runtime settings loaded from environment or optional TOML later."""

    model_config = SettingsConfigDict(env_prefix="TRAVELJOURNAL_", extra="ignore")

    default_thumbnail_size: int = Field(default=256, ge=64, le=1024)
    hash_chunk_size: int = Field(default=1024 * 1024, ge=4096)
    stay_radius_meters: float = Field(default=150.0, gt=0)
    stay_min_duration_minutes: int = Field(default=30, ge=1)
    gps_match_max_delta_seconds: int = Field(default=120, ge=1)
    allow_network_services: bool = Field(
        default=False,
        description="Cloud/AI services stay disabled until explicitly enabled.",
    )

    @property
    def user_config_dir(self) -> Path:
        return Path.home() / "AppData" / "Local" / "TravelJournal"
