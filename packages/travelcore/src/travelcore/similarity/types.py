"""Similarity grouping: exact SHA-256 duplicates and perceptual hashes later.

The architecture allows additional methods such as CLIP embeddings without
changing callers. Original files are never deleted automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class SimilarityKind(StrEnum):
    EXACT = "exact"
    VISUAL = "visual"


class SimilarityMethod(StrEnum):
    SHA256 = "sha256"
    DHASH = "dhash"
    PHASH = "phash"
    CLIP = "clip"
    MANUAL = "manual"


class ClusterType(StrEnum):
    STACK = "stack"
    GROUP = "group"


class ClusterStatus(StrEnum):
    SUGGESTED = "suggested"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"


@dataclass(frozen=True, slots=True)
class SimilarityMember:
    path: Path
    distance: float | None


@dataclass(frozen=True, slots=True)
class SimilarityGroup:
    kind: SimilarityKind
    method: SimilarityMethod
    members: tuple[SimilarityMember, ...]
