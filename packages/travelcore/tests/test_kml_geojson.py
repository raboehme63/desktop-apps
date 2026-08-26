from pathlib import Path

from travelcore.gps.geojson import parse_geojson
from travelcore.gps.kml import parse_kml


def test_parse_kml_linestring(tmp_path: Path) -> None:
    path = tmp_path / "route.kml"
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark>'
        "<LineString><coordinates>11.0,46.0,200 11.2,46.1,210</coordinates>"
        "</LineString></Placemark></kml>",
        encoding="utf-8",
    )
    tracks = parse_kml(path)
    assert len(tracks) == 1
    assert tracks[0].format == "kml"
    assert len(tracks[0].points) == 2
    assert tracks[0].points[0].longitude == 11.0
    assert tracks[0].points[0].latitude == 46.0
    assert tracks[0].points[1].altitude == 210.0


def test_parse_kml_gx_track(tmp_path: Path) -> None:
    path = tmp_path / "flug.kml"
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2" '
        'xmlns:gx="http://www.google.com/kml/ext/2.2"><Placemark><gx:Track>'
        "<gx:coord>11.0 46.0 200</gx:coord>"
        "<gx:coord>11.2 46.1 210</gx:coord>"
        "</gx:Track></Placemark></kml>",
        encoding="utf-8",
    )
    tracks = parse_kml(path)
    assert len(tracks) == 1
    assert [point.longitude for point in tracks[0].points] == [11.0, 11.2]


def test_parse_geojson_linestring(tmp_path: Path) -> None:
    path = tmp_path / "route.geojson"
    path.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":'
        '{"type":"LineString","coordinates":[[11.0,46.0],[11.2,46.1,210]]}}]}',
        encoding="utf-8",
    )
    tracks = parse_geojson(path)
    assert len(tracks) == 1
    assert tracks[0].format == "geojson"
    assert len(tracks[0].points) == 2
    assert tracks[0].points[1].altitude == 210.0
