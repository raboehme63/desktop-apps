"""Import and analysis pipeline. Stages are composable; SQLite stays on one writer."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from travelcore.parallel import WorkerPool

__all__ = ["PipelineStage", "WorkerPool", "run_pipeline"]


@runtime_checkable
class PipelineStage(Protocol):
    """One step of an import or analysis run.

    TravelJournal and PhotoInspector compose different stage lists against the
    same ``ctx`` (session, project, worker pool). Stages must not open SQLite
    in worker processes.
    """

    name: str

    def run(self, ctx: Any) -> None: ...


def run_pipeline(ctx: Any, stages: Sequence[PipelineStage]) -> Any:
    """Run ``stages`` in order. Returns ``ctx`` so callers can read ``ctx.result``."""

    for stage in stages:
        stage.run(ctx)
    return ctx
