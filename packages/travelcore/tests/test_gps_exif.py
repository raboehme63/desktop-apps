from travelcore.metadata.gps import dms_to_decimal, position_from_coordinates_text, position_from_exif


def test_dms_north_east() -> None:
    lat = dms_to_decimal((46.0, 29.0, 53.0), "N")
    lon = dms_to_decimal((11.0, 21.0, 12.0), "E")
    assert lat is not None
    assert lon is not None
    assert abs(lat - (46 + 29 / 60 + 53 / 3600)) < 1e-9
    assert abs(lon - (11 + 21 / 60 + 12 / 3600)) < 1e-9


def test_dms_south_west_is_negative() -> None:
    assert dms_to_decimal((33.0, 51.0, 0.0), "S") == -(33 + 51 / 60)
    assert dms_to_decimal((151.0, 12.0, 0.0), "W") == -(151 + 12 / 60)


def test_signed_decimal_does_not_double_negate() -> None:
    assert dms_to_decimal(-46.498, "S") == -46.498
    assert dms_to_decimal(11.353, "E") == 11.353


def test_position_from_exif_sets_source_and_confidence() -> None:
    position = position_from_exif(
        latitude=(46.0, 30.0, 0.0),
        latitude_ref="N",
        longitude=(11.0, 21.0, 0.0),
        longitude_ref="E",
        altitude=262.0,
        altitude_ref=0,
    )
    assert position is not None
    assert position.source == "exif"
    assert position.confidence == 1.0
    assert position.time_delta_seconds is None
    assert position.altitude == 262.0


def test_incomplete_gps_returns_none() -> None:
    assert (
        position_from_exif(
            latitude=(46.0, 0.0, 0.0),
            latitude_ref="N",
            longitude=None,
            longitude_ref="E",
        )
        is None
    )


def test_iso6709_iphone_location() -> None:
    position = position_from_coordinates_text("+46.498011+011.353000+0262.000/")
    assert position is not None
    assert abs(position.latitude - 46.498011) < 1e-6
    assert abs(position.longitude - 11.353) < 1e-6
    assert position.altitude == 262.0
    assert position.source == "quicktime"


def test_gps_coordinates_decimal_pair() -> None:
    position = position_from_coordinates_text("46.498011 11.353000 262")
    assert position is not None
    assert abs(position.latitude - 46.498011) < 1e-6
    assert abs(position.longitude - 11.353) < 1e-6
    assert position.altitude == 262.0


def test_gps_coordinates_dms_text() -> None:
    position = position_from_coordinates_text("""46 deg 29' 53.00" N, 11 deg 21' 12.00" E""")
    assert position is not None
    assert position.source == "quicktime"
