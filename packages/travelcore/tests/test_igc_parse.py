from datetime import UTC, datetime
from pathlib import Path

import pytest
from igc_fixtures import bozen_points, write_igc

from travelcore.exceptions import GpsError
from travelcore.gps.igc import parse_igc


def test_parse_igc_pilot_and_points(tmp_path: Path) -> None:
    path = write_igc(tmp_path / "flug.igc", bozen_points(), pilot="Ralf Muster")
    tracks = parse_igc(path)
    assert len(tracks) == 1
    assert tracks[0].format == "igc"
    assert tracks[0].pilot == "Ralf Muster"
    assert tracks[0].name is not None
    assert "Ozone" in (tracks[0].name or "")
    assert len(tracks[0].points) == 2
    first = tracks[0].points[0]
    assert abs(first.latitude - 46.4980167) < 1e-4
    assert abs(first.longitude - 11.353) < 1e-4
    assert first.altitude == 1234.0
    assert first.recorded_at == datetime(2025, 5, 15, 12, 31, 50, tzinfo=UTC)


def test_parse_igc_skips_invalid_fix(tmp_path: Path) -> None:
    path = tmp_path / "mixed.igc"
    path.write_text(
        "AXXX\nHFDTEDATE:150525\nB1231504629881N01121180EV0000000000\nB1232104630000N01121600EA0123401234\n",
        encoding="utf-8",
    )
    tracks = parse_igc(path)
    assert len(tracks) == 1
    assert len(tracks[0].points) == 1


def test_empty_igc_is_not_an_error(tmp_path: Path) -> None:
    path = tmp_path / "empty.igc"
    path.write_text("AXXX TRAVELCORE\nHFDTEDATE:150525\n", encoding="utf-8")
    assert parse_igc(path) == ()


def test_unreadable_igc_raises(tmp_path: Path) -> None:
    path = tmp_path / "missing.igc"
    with pytest.raises(GpsError):
        parse_igc(path)
