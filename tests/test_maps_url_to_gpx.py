from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from travelcore.gps.maps_url import (
    Directions,
    MapsGpxError,
    Waypoint,
    convert_maps_url,
    directions_to_gpx,
    main,
    parse_directions_html,
    parse_directions_url,
    resolve_directions,
    route_filename_stem,
    route_geometry,
)

SAMPLE_DIR_URL = (
    "https://www.google.de/maps/dir/Bad+T%C3%B6lz,+83646/47.4777279,10.8178003/"
    "CAMPING+RUDI,+Luxnach+122,+6651+H%C3%A4selgehr,+%C3%96sterreich/"
    "@47.322918,10.4541274,10.5z/"
    "data=!4m15!4m14!1m5!1m1!1s0x479d94490fd26e55:0x5f031a0b2eb1fdc0"
    "!2m2!1d11.5661182!2d47.7619244!1m0!1m5!1m1!1s0x479c95302f1024fb:0xa6642050eee3e12b"
    "!2m2!1d10.4985014!2d47.3154519!3e0"
)
SAMPLE_HTML = (
    '<!DOCTYPE html><html lang="de"><head>'
    '<link href="/maps/preview/directions?hl=de&amp;pb='
    "%211m6%211sBad+T%C3%B6lz%2C+83646"
    "%212s0x479d94490fd26e55%3A0x5f031a0b2eb1fdc0"
    "%213m2%213d47.7619244%214d11.5661182%216e0"
    "%211m4%213m2%213d47.4777279%214d10.8178003%216e2"
    "%211m6%211sCAMPING+RUDI%2C+Luxnach+122%2C+6651+H%C3%A4selgehr%2C+%C3%96sterreich"
    "%212s0x479c95302f1024fb%3A0xa6642050eee3e12b"
    "%213m2%213d47.3154519%214d10.4985014%216e0%213"
    '" rel="stylesheet"></head>'
    "<body>https://www.google.de/maps/dir/Bad+Tölz,+83646/"
    "47.4777279,10.8178003/CAMPING+RUDI/</body></html>"
)
COORD_START_NAMED_END_URL = (
    "https://www.google.de/maps/dir/47.315353,10.4985014/"
    "Parkplatz+Wasserauen,+Schwendetalstrasse,+9050+Schwende/"
    "@47.2,9.5,9z/data=!4m2!4m1!3e0"
)


def _osrm_body(points: list[tuple[float, float]]) -> bytes:
    coordinates = [[lon, lat] for lat, lon in points]
    return json.dumps(
        {"code": "Ok", "routes": [{"geometry": {"type": "LineString", "coordinates": coordinates}}]}
    ).encode()


def test_parse_sample_dir_url_reads_named_stops_and_driving_mode() -> None:
    directions = parse_directions_url(SAMPLE_DIR_URL)
    assert directions.complete
    assert directions.travel_mode == "driving"
    assert len(directions.waypoints) == 3
    first, via, last = directions.waypoints
    assert first.name == "Bad Tölz"
    assert first.latitude == pytest.approx(47.7619244)
    assert first.longitude == pytest.approx(11.5661182)
    assert via.latitude == pytest.approx(47.4777279)
    assert via.longitude == pytest.approx(10.8178003)
    assert last.name == "CAMPING RUDI"
    assert last.latitude == pytest.approx(47.3154519)
    assert last.longitude == pytest.approx(10.4985014)


def test_parse_api_directions_url() -> None:
    url = (
        "https://www.google.com/maps/dir/?api=1"
        "&origin=47.7619244,11.5661182"
        "&destination=CAMPING+RUDI"
        "&waypoints=47.4777279,10.8178003"
        "&travelmode=walking"
    )
    directions = parse_directions_url(url)
    assert directions.travel_mode == "foot"
    assert len(directions.waypoints) == 3
    assert directions.waypoints[0].has_coords
    assert directions.waypoints[1].has_coords
    assert directions.waypoints[2].name == "CAMPING RUDI"
    assert not directions.waypoints[2].has_coords


def test_parse_walking_enum_from_data_blob() -> None:
    url = "https://www.google.com/maps/dir/47.0,11.0/47.1,11.1/data=!4m2!4m1!3e2"
    assert parse_directions_url(url).travel_mode == "foot"


def test_parse_directions_html_preview_protobuf() -> None:
    directions = parse_directions_html(SAMPLE_HTML)
    assert len(directions.waypoints) >= 3
    first, via, last = directions.waypoints[:3]
    assert first.name == "Bad Tölz"
    assert first.latitude == pytest.approx(47.7619244)
    assert via.latitude == pytest.approx(47.4777279)
    assert last.name == "CAMPING RUDI"
    assert last.longitude == pytest.approx(10.4985014)


def test_resolve_short_link_uses_redirect_and_html() -> None:
    short = "https://maps.app.goo.gl/Z43u4CMs69sSY79dA"

    def fake_get(url: str) -> tuple[str, bytes]:
        assert url == short
        return SAMPLE_DIR_URL, SAMPLE_HTML.encode()

    directions = resolve_directions(short, http_get=fake_get)
    assert directions.complete
    assert directions.waypoints[0].name == "Bad Tölz"
    assert directions.waypoints[-1].name == "CAMPING RUDI"


def test_current_location_is_rejected() -> None:
    url = "https://www.google.com/maps/dir/Current+Location/47.3,10.5"
    with pytest.raises(MapsGpxError, match="aktuellen Standort"):
        parse_directions_url(url)


def test_place_url_without_route_is_rejected() -> None:
    with pytest.raises(MapsGpxError, match="Kein Routenlink"):

        def fake_get(_url: str) -> tuple[str, bytes]:
            return "https://www.google.de/maps/place/Bad+Tölz", b"<html>place</html>"

        resolve_directions("https://maps.app.goo.gl/place", http_get=fake_get)


def test_directions_to_gpx_writes_waypoints_and_track(tmp_path: Path) -> None:
    directions = parse_directions_url(SAMPLE_DIR_URL)
    xml = directions_to_gpx(
        directions,
        [(47.76191, 11.56611), (47.47773, 10.81780), (47.31545, 10.49850)],
        created_at=datetime(2026, 9, 2, 12, 49, 54, tzinfo=UTC),
    )
    assert 'creator="maps_url_to_gpx"' in xml
    assert "<name>Bad Tölz</name>" in xml
    assert "<name>CAMPING RUDI</name>" in xml
    assert "<name>Bad Tölz to CAMPING RUDI</name>" in xml
    assert "<time>2026-09-02T12:49:54Z</time>" in xml
    assert 'lat="47.76191"' in xml
    path = tmp_path / "sample.gpx"
    path.write_text(xml, encoding="utf-8")
    from travelcore.gps.parse import parse_gpx

    parsed = parse_gpx(path)
    assert len(parsed) == 1
    assert len(parsed[0].points) == 3


def test_route_geometry_reads_osrm_geojson() -> None:
    directions = parse_directions_url(SAMPLE_DIR_URL)

    def fake_get(url: str) -> tuple[str, bytes]:
        assert "router.project-osrm.org/route/v1/driving/" in url
        assert "11.5661182,47.7619244" in url
        assert "geometries=geojson" in url
        return url, _osrm_body(
            [(47.76191, 11.56611), (47.6, 11.2), (47.47773, 10.81780), (47.31545, 10.49850)]
        )

    points = route_geometry(directions, http_get=fake_get)
    assert len(points) == 4
    assert points[0] == pytest.approx((47.76191, 11.56611))
    assert points[-1] == pytest.approx((47.31545, 10.49850))


def test_convert_writes_gpx_and_follows_roads(tmp_path: Path) -> None:
    dest = tmp_path / "route.gpx"
    road = [(47.76191, 11.56611), (47.70, 11.20), (47.47773, 10.81780), (47.31545, 10.49850)]

    def fake_get(url: str) -> tuple[str, bytes]:
        if "router.project-osrm.org" in url:
            return url, _osrm_body(road)
        raise AssertionError(url)

    written = convert_maps_url(SAMPLE_DIR_URL, dest, http_get=fake_get)
    assert written == dest
    text = dest.read_text(encoding="utf-8")
    assert 'lat="47.7"' in text
    assert text.count("<trkpt ") == 4
    assert text.count("<wpt ") == 3
    from travelcore.gps.parse import parse_gpx

    parsed = parse_gpx(dest)
    assert len(parsed[0].points) == 4


def test_waypoints_only_skips_router(tmp_path: Path) -> None:
    dest = tmp_path / "stops.gpx"

    def fake_get(url: str) -> tuple[str, bytes]:
        raise AssertionError(f"unexpected request {url}")

    convert_maps_url(SAMPLE_DIR_URL, dest, waypoints_only=True, http_get=fake_get)
    text = dest.read_text(encoding="utf-8")
    assert text.count("<trkpt ") == 3
    assert 'lat="47.7619244"' in text
    assert 'lat="47.3154519"' in text


def test_main_writes_named_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dest = tmp_path / "out.gpx"

    def fake_get(url: str) -> tuple[str, bytes]:
        if "router.project-osrm.org" in url:
            return url, _osrm_body([(47.76191, 11.56611), (47.31545, 10.49850)])
        raise AssertionError(url)

    assert main([SAMPLE_DIR_URL, "-o", str(dest)], http_get=fake_get) == 0
    line = capsys.readouterr().out.strip()
    assert line == str(dest)
    assert dest.is_file()


def test_main_reports_router_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dest = tmp_path / "fail.gpx"

    def fake_get(url: str) -> tuple[str, bytes]:
        return url, json.dumps({"code": "NoRoute"}).encode()

    assert main([SAMPLE_DIR_URL, "-o", str(dest)], http_get=fake_get) == 1
    err = capsys.readouterr().err
    assert "Keine Straße" in err
    assert not dest.exists()


def test_route_filename_stem_uses_start_and_end() -> None:
    directions = parse_directions_url(SAMPLE_DIR_URL)
    assert route_filename_stem(directions) == "Bad-Tölz-to-CAMPING-RUDI"


def test_route_filename_stem_uses_place_name_from_address() -> None:
    url = (
        "https://www.google.de/maps/dir/"
        "L%C3%A4hnwald,+6600,+%C3%96sterreich/"
        "H%C3%A4selgehr+122,+6651+H%C3%A4selgehr,+%C3%96sterreich/"
    )
    directions = parse_directions_url(url)
    assert directions.waypoints[0].name == "Lähnwald"
    assert directions.waypoints[-1].name == "Häselgehr"
    assert route_filename_stem(directions) == "Lähnwald-to-Häselgehr"


def test_route_filename_stem_uses_numbered_placeholder_without_name() -> None:
    directions = Directions(
        waypoints=(
            Waypoint(47.7619, 11.5661),
            Waypoint(47.4777, 10.8178),
            Waypoint(47.3155, 10.4985),
        )
    )
    assert route_filename_stem(directions) == "Stop-1-to-Stop-3"


def test_coord_start_is_not_used_as_place_name() -> None:
    directions = parse_directions_url(COORD_START_NAMED_END_URL)
    assert directions.waypoints[0].name == ""
    assert directions.waypoints[-1].name == "Parkplatz Wasserauen"
    assert route_filename_stem(directions) == "Stop-1-to-Parkplatz-Wasserauen"


def test_resolve_uses_nominatim_when_maps_has_only_coords() -> None:
    html = (
        "<!DOCTYPE html><html><head>"
        '<link href="/maps/preview/directions?hl=de&amp;pb='
        "%211m4%213m2%213d47.315353%214d10.4985014%216e2"
        "%211m6%211sParkplatz+Wasserauen%2C+Schwendetalstrasse"
        "%213m2%213d47.28%214d9.49%216e0"
        '" rel="stylesheet"></head>'
        "<body>https://www.google.de/maps/dir/47.315353,10.4985014/"
        "Parkplatz+Wasserauen/</body></html>"
    )
    nominatim = json.dumps(
        {"address": {"village": "Häselgehr", "city": "Häselgehr", "road": "Staudig"}}
    ).encode()

    def fake_get(url: str) -> tuple[str, bytes]:
        if "nominatim.openstreetmap.org" in url:
            assert "47.315353" in url
            return url, nominatim
        return COORD_START_NAMED_END_URL, html.encode()

    directions = resolve_directions(COORD_START_NAMED_END_URL, http_get=fake_get)
    assert directions.waypoints[0].name == "Häselgehr"
    assert route_filename_stem(directions) == "Häselgehr-to-Parkplatz-Wasserauen"


def test_resolve_fills_start_name_from_html_when_path_is_coords() -> None:
    html = (
        '<!DOCTYPE html><html><head><link href="/maps/preview/directions?hl=de&amp;pb='
        "%211m6%211sH%C3%A4selgehr+122%2C+6651+H%C3%A4selgehr%2C+%C3%96sterreich"
        "%213m2%213d47.315353%214d10.4985014%216e0"
        "%211m6%211sParkplatz+Wasserauen%2C+Schwendetalstrasse"
        "%213m2%213d47.28%214d9.49%216e0%213"
        '" rel="stylesheet"></head>'
        "<body>https://www.google.de/maps/dir/47.315353,10.4985014/"
        "Parkplatz+Wasserauen/</body></html>"
    )

    def fake_get(url: str) -> tuple[str, bytes]:
        assert url == COORD_START_NAMED_END_URL
        return COORD_START_NAMED_END_URL, html.encode()

    directions = resolve_directions(COORD_START_NAMED_END_URL, http_get=fake_get)
    assert directions.waypoints[0].name == "Häselgehr"
    assert route_filename_stem(directions) == "Häselgehr-to-Parkplatz-Wasserauen"


def test_route_filename_stem_mixes_place_name_and_placeholder() -> None:
    directions = Directions(
        waypoints=(
            Waypoint(47.48, 10.72, name="Lähnwald", description="Lähnwald, 6600, Österreich"),
            Waypoint(47.3155, 10.4985),
        )
    )
    assert route_filename_stem(directions) == "Lähnwald-to-Stop-2"


def test_gpx_escapes_ampersand_in_name() -> None:
    xml = directions_to_gpx(
        Directions(
            waypoints=(
                Waypoint(47.0, 11.0, name="A & B", description="A & B"),
                Waypoint(47.1, 11.1, name="C", description="C"),
            )
        ),
        [(47.0, 11.0), (47.1, 11.1)],
    )
    assert "A &amp; B" in xml
