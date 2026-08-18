"""Quality metrics used as recommendations only — never for automatic deletion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class QualityMetrics:
    width: int | None
    height: int | None
    aspect_ratio: float | None
    brightness: float | None
    contrast: float | None
    sharpness: float | None
    overexposed: bool | None
    underexposed: bool | None
    technical_quality: float | None


class QualityAnalyzer(Protocol):
    def analyze(self, path: Path) -> QualityMetrics:
        """Inspect a photo without modifying it."""
        ...
