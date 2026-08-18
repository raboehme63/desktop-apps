"""Media discovery, typing, hashing, and source-file indexing."""

from travelcore.media.hashing import sha256_file
from travelcore.media.indexer import FileIndexer, IndexProgress, IndexResult
from travelcore.media.scanner import ScannedFile, scan_source_directory
from travelcore.media.thumbnails import (
    ThumbnailResult,
    cached_thumbnail_path,
    ensure_thumbnail,
    generate_project_thumbnails,
)
from travelcore.media.types import FileKind, classify_path, mime_for_path

__all__ = [
    "FileIndexer",
    "FileKind",
    "IndexProgress",
    "IndexResult",
    "ScannedFile",
    "ThumbnailResult",
    "cached_thumbnail_path",
    "classify_path",
    "ensure_thumbnail",
    "generate_project_thumbnails",
    "mime_for_path",
    "scan_source_directory",
    "sha256_file",
]
