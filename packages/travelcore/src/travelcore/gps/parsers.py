"""Exchangeable GPS track parsers. Ingest uses this registry, not hardcoded suffixes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from travelcore.exceptions import GpsError
from travelcore.gps.igc import parse_igc
from travelcore.gps.parse import ParsedTrack, parse_gpx


@runtime_checkable
class TrackParser(Protocol):
    """Read a track file into typed points. Originals are never written."""

    suffixes: frozenset[str]
    stage: str

    def parse(self, path: Path) -> tuple[ParsedTrack, ...]: ...


class GpxParser:
    suffixes = frozenset({".gpx"})
    stage = "gpx"

    def parse(self, path: Path) -> tuple[ParsedTrack, ...]:
        return parse_gpx(path)


class IgcParser:
    suffixes = frozenset({".igc"})
    stage = "igc"

    def parse(self, path: Path) -> tuple[ParsedTrack, ...]:
        return parse_igc(path)


DEFAULT_TRACK_PARSERS: tuple[TrackParser, ...] = (GpxParser(), IgcParser())

_PARSER_BY_SUFFIX: dict[str, TrackParser] = {
    suffix: parser for parser in DEFAULT_TRACK_PARSERS for suffix in parser.suffixes
}


def parser_for_path(
    path: Path,
    parsers: tuple[TrackParser, ...] = DEFAULT_TRACK_PARSERS,
) -> TrackParser | None:
    """Return the parser for ``path``'s suffix, or None if the format is not ingested."""

    suffix = path.suffix.lower()
    if parsers is DEFAULT_TRACK_PARSERS:
        return _PARSER_BY_SUFFIX.get(suffix)
    for parser in parsers:
        if suffix in parser.suffixes:
            return parser
    return None


@dataclass(frozen=True, slots=True)
class TrackParseOutcome:
    """DTO from a worker process. No SQLAlchemy objects."""

    path: str
    tracks: tuple[ParsedTrack, ...] = ()
    error: str | None = None
    stage: str = "gpx"


def parse_track_batch(paths: tuple[str, ...]) -> list[TrackParseOutcome]:
    """Module-level pool entry: parse a chunk of GPX/IGC files."""

    results: list[TrackParseOutcome] = []
    for path_str in paths:
        path = Path(path_str)
        parser = parser_for_path(path)
        if parser is None:
            results.append(TrackParseOutcome(path=path_str))
            continue
        try:
            tracks = parser.parse(path)
        except GpsError as exc:
            results.append(TrackParseOutcome(path=path_str, error=str(exc), stage=parser.stage))
            continue
        results.append(TrackParseOutcome(path=path_str, tracks=tracks, stage=parser.stage))
    return results
