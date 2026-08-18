"""Cache keys for thumbnails, metadata, hashes, and analysis results.

A file is treated as unchanged when size and modification time still match
(and optionally the stored SHA-256). Re-analysis is skipped in that case.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    path: Path
    size_bytes: int
    modified_at: datetime | None
    sha256: str | None = None
