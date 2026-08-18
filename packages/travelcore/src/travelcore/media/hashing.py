"""SHA-256 hashing of source files. Original files are only read, never written."""

from __future__ import annotations

import hashlib
from pathlib import Path

DEFAULT_CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """Return the hex SHA-256 digest of a file.

    The file is read in chunks so large photos and videos do not need to fit
    into memory. The original file is never modified.
    """

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
