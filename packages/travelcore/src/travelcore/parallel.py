"""Process-pool helpers. SQLite sessions never enter worker processes."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from multiprocessing import get_context
from types import TracebackType

logger = logging.getLogger(__name__)

_MAX_WORKERS = 64
ProgressFn = Callable[[int, int], None]


def resolve_worker_count(requested: int | None = None) -> int:
    """Return a worker count. ``0``/``None`` means CPU count minus one."""

    cpus = os.cpu_count() or 1
    automatic = max(1, cpus - 1)
    if requested is None or requested <= 0:
        return min(automatic, _MAX_WORKERS)
    return min(max(1, requested), _MAX_WORKERS)


def chunk_size_for(item_count: int, workers: int) -> int:
    if item_count <= workers:
        return 1
    return max(1, min(32, item_count // (workers * 2)))


class WorkerPool:
    """Reusable spawned process pool for one import (or app) session.

    Start the pool once, then map extract, GPS parse and JPEG thumbnails
    without paying Windows ``spawn`` on every stage. SQLite stays out.
    """

    def __init__(
        self,
        max_workers: int | None = None,
        *,
        initializer: Callable[[], None] | None = None,
    ) -> None:
        self.max_workers = resolve_worker_count(max_workers)
        self._initializer = initializer
        self._executor: ProcessPoolExecutor | None = None

    def __enter__(self) -> WorkerPool:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        executor = self._executor
        self._executor = None
        if executor is not None:
            executor.shutdown(wait=True)

    def map[ItemT, ResultT](
        self,
        func: Callable[[tuple[ItemT, ...]], list[ResultT]],
        items: Sequence[ItemT],
        *,
        progress: ProgressFn | None = None,
    ) -> list[ResultT]:
        """Map ``func`` over chunks. Falls back to one process if the pool breaks."""

        if not items:
            return []
        workers = min(self.max_workers, len(items))
        if workers <= 1:
            return _map_here(func, items, progress)
        chunks = _as_chunks(items, chunk_size_for(len(items), workers))
        try:
            return self._map_pool(func, chunks, workers, progress, len(items))
        except (BrokenProcessPool, OSError, PermissionError) as exc:
            logger.warning("Process pool unavailable (%s); using one process.", exc)
            self.close()
            return _map_here(func, items, progress)

    def _ensure_executor(self, workers: int) -> ProcessPoolExecutor:
        if self._executor is not None:
            return self._executor
        self._executor = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=get_context("spawn"),
            initializer=_bootstrap_worker,
            initargs=(list(sys.path), self._initializer),
        )
        return self._executor

    def _map_pool[ItemT, ResultT](
        self,
        func: Callable[[tuple[ItemT, ...]], list[ResultT]],
        chunks: Sequence[tuple[ItemT, ...]],
        workers: int,
        progress: ProgressFn | None,
        total: int,
    ) -> list[ResultT]:
        pool = self._ensure_executor(workers)
        ordered: list[list[ResultT] | None] = [None] * len(chunks)
        completed = 0
        futures = {pool.submit(func, chunk): index for index, chunk in enumerate(chunks)}
        for future in as_completed(futures):
            index = futures[future]
            chunk_result = future.result()
            ordered[index] = chunk_result
            completed += len(chunks[index])
            if progress is not None:
                progress(completed, total)
        merged: list[ResultT] = []
        for part in ordered:
            if part is None:
                raise RuntimeError("Process pool returned an incomplete result.")
            merged.extend(part)
        return merged


def map_in_processes[ItemT, ResultT](
    func: Callable[[tuple[ItemT, ...]], list[ResultT]],
    items: Sequence[ItemT],
    *,
    max_workers: int | None = None,
    progress: ProgressFn | None = None,
    initializer: Callable[[], None] | None = None,
    pool: WorkerPool | None = None,
) -> list[ResultT]:
    """Map ``func`` over chunks of ``items`` in spawned processes.

    ``func`` must be a module-level callable that accepts a tuple of items and
    returns a list of results in the same order. Falls back to in-process work
    when a pool cannot be started or only one worker is needed.
    """

    if pool is not None:
        return pool.map(func, items, progress=progress)
    with WorkerPool(max_workers, initializer=initializer) as owned:
        return owned.map(func, items, progress=progress)


def map_in_threads[ItemT, ResultT](
    func: Callable[[tuple[ItemT, ...]], list[ResultT]],
    items: Sequence[ItemT],
    *,
    max_workers: int | None = None,
    progress: ProgressFn | None = None,
    initializer: Callable[[], None] | None = None,
) -> list[ResultT]:
    """Map ``func`` over chunks of ``items`` in threads (safe from a Qt worker)."""

    if not items:
        return []
    workers = min(resolve_worker_count(max_workers), len(items))
    if workers <= 1:
        if initializer is not None:
            initializer()
        return _map_here(func, items, progress)
    chunks = _as_chunks(items, chunk_size_for(len(items), workers))
    ordered: list[list[ResultT] | None] = [None] * len(chunks)
    completed = 0
    with ThreadPoolExecutor(max_workers=workers, initializer=initializer) as pool:
        futures = {pool.submit(func, chunk): index for index, chunk in enumerate(chunks)}
        for future in as_completed(futures):
            index = futures[future]
            chunk_result = future.result()
            ordered[index] = chunk_result
            completed += len(chunks[index])
            if progress is not None:
                progress(completed, len(items))
    merged: list[ResultT] = []
    for part in ordered:
        if part is None:
            raise RuntimeError("Thread pool returned an incomplete result.")
        merged.extend(part)
    return merged


def _as_chunks[ItemT](items: Sequence[ItemT], size: int) -> list[tuple[ItemT, ...]]:
    return [tuple(items[index : index + size]) for index in range(0, len(items), size)]


def _map_here[ItemT, ResultT](
    func: Callable[[tuple[ItemT, ...]], list[ResultT]],
    items: Sequence[ItemT],
    progress: ProgressFn | None,
) -> list[ResultT]:
    result: list[ResultT] = []
    done = 0
    total = len(items)
    for chunk in _as_chunks(items, 1 if total <= 8 else min(8, total)):
        result.extend(func(chunk))
        done += len(chunk)
        if progress is not None:
            progress(done, total)
    return result


def _bootstrap_worker(sys_path: list[str], user_init: Callable[[], None] | None) -> None:
    """Restore import path after Windows spawn, then run the caller initializer."""

    for entry in reversed(sys_path):
        if entry and entry not in sys.path:
            sys.path.insert(0, entry)
    if user_init is not None:
        user_init()
