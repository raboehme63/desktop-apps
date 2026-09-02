"""Kind chip for GPS files in the Tracks gallery: Map, Act, igc."""

from __future__ import annotations

from pathlib import Path

from travelcore.gps.fitnesstracks import is_fitness_track_path
from travelcore.gps.igctracks import is_igc_track_path
from travelcore.gps.maptracks import is_map_track_path

TRACK_BADGE_MAP = "map"
TRACK_BADGE_ACT = "act"
TRACK_BADGE_IGC = "igc"
TRACK_BADGES = (TRACK_BADGE_MAP, TRACK_BADGE_ACT, TRACK_BADGE_IGC)


def track_badge_for(path: str | Path, filename: str | None = None) -> str | None:
    """Return ``map``, ``act`` or ``igc`` for a GPS file, else ``None``."""

    resolved = Path(path)
    name = filename if filename else resolved.name
    suffixes = {resolved.suffix.lower(), Path(name).suffix.lower()}
    if is_map_track_path(resolved):
        return TRACK_BADGE_MAP
    if ".igc" in suffixes or is_igc_track_path(resolved):
        return TRACK_BADGE_IGC
    if is_fitness_track_path(resolved):
        return TRACK_BADGE_ACT
    return None
