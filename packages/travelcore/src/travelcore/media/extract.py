"""Hash and metadata extraction without touching SQLite.

Worker processes return ``FileFacts`` dataclasses. The indexer applies them
on a single writer thread.
"""

from __future__ import annotations

import atexit
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from travelcore.exceptions import MetadataError
from travelcore.media.hashing import sha256_file
from travelcore.metadata.composite import DefaultMetadataProvider
from travelcore.metadata.provider import CapturedTime, MediaMetadata, MetadataProvider
from travelcore.metadata.time import filesystem_captured_time
from travelcore.parallel import WorkerPool, map_in_processes, resolve_worker_count

ProgressFn = Callable[[int, int, str], None]

_worker_provider: DefaultMetadataProvider | None = None


@dataclass(frozen=True, slots=True)
class ExtractRequest:
    path: str
    compute_hash: bool
    read_metadata: bool
    hash_chunk_size: int = 1024 * 1024


@dataclass(frozen=True, slots=True)
class FileFacts:
    path: str
    sha256: str | None = None
    metadata: MediaMetadata | None = None
    metadata_error: str | None = None
    io_error: str | None = None
    filesystem_captured: CapturedTime | None = None


def extract_file_facts(
    request: ExtractRequest,
    *,
    provider: MetadataProvider | None = None,
) -> FileFacts:
    """Read hash and/or metadata for one file. Originals are never written."""

    return _extract_one(request, provider or _process_provider())


def extract_file_facts_batch(requests: tuple[ExtractRequest, ...]) -> list[FileFacts]:
    """Module-level pool entry: process a chunk in one worker process."""

    provider = _process_provider()
    return [_extract_one(request, provider) for request in requests]


def extract_many(
    requests: Sequence[ExtractRequest],
    *,
    provider: MetadataProvider | None = None,
    max_workers: int | None = None,
    progress: ProgressFn | None = None,
    pool: WorkerPool | None = None,
) -> dict[str, FileFacts]:
    """Extract facts for many files. SQLite is not used here."""

    if not requests:
        return {}
    workers = resolve_worker_count(max_workers)
    use_pool = workers > 1 and len(requests) > 1 and _pool_safe(provider)

    def on_progress(done: int, total: int) -> None:
        if progress is None or not requests:
            return
        path = requests[min(done, len(requests)) - 1].path if done else requests[0].path
        progress(done, total, path)

    if use_pool:
        results = map_in_processes(
            extract_file_facts_batch,
            requests,
            max_workers=workers,
            progress=on_progress,
            initializer=_init_extract_worker,
            pool=pool,
        )
    else:
        active = provider or _process_provider()
        results = []
        for index, request in enumerate(requests, start=1):
            results.append(_extract_one(request, active))
            on_progress(index, len(requests))
    return {item.path: item for item in results}


def _pool_safe(provider: MetadataProvider | None) -> bool:
    return provider is None or isinstance(provider, DefaultMetadataProvider)


def _extract_one(request: ExtractRequest, provider: MetadataProvider) -> FileFacts:
    path = Path(request.path)
    digest: str | None = None
    try:
        if request.compute_hash:
            digest = sha256_file(path, chunk_size=request.hash_chunk_size)
        if not request.read_metadata:
            return FileFacts(path=request.path, sha256=digest)
        try:
            metadata = provider.read(path)
        except (MetadataError, OSError, ValueError) as exc:
            return FileFacts(
                path=request.path,
                sha256=digest,
                metadata_error=str(exc),
                filesystem_captured=filesystem_captured_time(path),
            )
        return FileFacts(path=request.path, sha256=digest, metadata=metadata)
    except OSError as exc:
        return FileFacts(path=request.path, sha256=digest, io_error=str(exc))


def _process_provider() -> DefaultMetadataProvider:
    global _worker_provider
    if _worker_provider is None:
        _worker_provider = DefaultMetadataProvider.from_environment()
    return _worker_provider


def _init_extract_worker() -> None:
    atexit.register(_shutdown_extract_worker)


init_extract_worker = _init_extract_worker


def _shutdown_extract_worker() -> None:
    global _worker_provider
    if _worker_provider is None:
        return
    closer = getattr(_worker_provider, "close", None)
    if callable(closer):
        closer()
    _worker_provider = None
