"""Shared exporter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from travelcore.exceptions import ExportError
from travelcore.trip.models import Trip


@dataclass(frozen=True, slots=True)
class ExportResult:
    output_path: Path
    files_written: tuple[Path, ...]


class Exporter(ABC):
    """Write a trip to an output format without mutating originals."""

    name: str

    @abstractmethod
    def export(self, trip: Trip, destination: Path) -> ExportResult:
        raise NotImplementedError


class NotImplementedExporter(Exporter):
    """Placeholder used until a backend is fully specified and licensed."""

    def export(self, trip: Trip, destination: Path) -> ExportResult:
        raise ExportError(f"Exporter '{self.name}' ist in dieser Version noch nicht implementiert.")
