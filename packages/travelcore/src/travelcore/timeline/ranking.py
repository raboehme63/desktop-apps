"""Replaceable photo-ranking strategies.

Example score (later phases):
    photo_score = technical_quality * uniqueness * sharpness * resolution
                  - duplicate_penalty
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PhotoFeatures:
    technical_quality: float = 0.0
    uniqueness: float = 1.0
    sharpness: float = 0.0
    resolution: float = 0.0
    duplicate_penalty: float = 0.0


class RankingStrategy(Protocol):
    def score(self, features: PhotoFeatures) -> float:
        """Return a higher score for photos that should rank first."""
        ...
