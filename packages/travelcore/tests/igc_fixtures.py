"""Synthetic IGC flight logs for tests. Coordinates are documentary, not personal tracks."""

from __future__ import annotations

from pathlib import Path


def write_igc(
    path: Path,
    points: list[tuple[str, str, str, str, str]],
    *,
    date_ddmmyy: str = "150525",
    pilot: str = "Testpilot",
    glider: str | None = "Ozone",
) -> Path:
    """Write a minimal IGC file.

    Each point is ``(hhmmss, lat, lat_hem, lon, lon_hem)`` in IGC DDMMmmm / DDDMMmmm form.
    """

    lines = [
        "AXXX TRAVELCORE",
        f"HFDTEDATE:{date_ddmmyy}",
        f"HFPLTPILOTINCHARGE:{pilot}",
    ]
    if glider:
        lines.append(f"HFGTYGLIDERTYPE:{glider}")
    for hhmmss, lat, lat_hem, lon, lon_hem in points:
        lines.append(f"B{hhmmss}{lat}{lat_hem}{lon}{lon_hem}A0123401234")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def bozen_points() -> list[tuple[str, str, str, str, str]]:
    """Two IGC B-records near Bozen (46.498 / 11.353)."""

    return [
        ("123150", "4629881", "N", "01121180", "E"),
        ("123210", "4630000", "N", "01121600", "E"),
    ]
