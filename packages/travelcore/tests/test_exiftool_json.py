from travelcore.metadata.exiftool_provider import metadata_from_exiftool_json


def test_exiftool_json_priority_and_signed_gps() -> None:
    metadata = metadata_from_exiftool_json(
        {
            "DateTimeOriginal": "2025:05:15 08:20:00",
            "CreateDate": "2025:05:15 09:00:00",
            "OffsetTimeOriginal": "+02:00",
            "GPSLatitude": 46.498,
            "GPSLongitude": 11.353,
            "GPSAltitude": 262,
            "Make": "Canon",
            "Model": "EOS R6",
            "ImageWidth": 6000,
            "ImageHeight": 4000,
        }
    )
    assert metadata.captured is not None
    assert metadata.captured.source == "exif_datetime_original"
    assert metadata.captured.timezone_unknown is False
    assert metadata.position is not None
    assert abs(metadata.position.latitude - 46.498) < 1e-9
    assert abs(metadata.position.longitude - 11.353) < 1e-9
    assert metadata.camera == "Canon EOS R6"
    assert metadata.width == 6000


def test_exiftool_json_video_creation_time() -> None:
    metadata = metadata_from_exiftool_json({"MediaCreateDate": "2025:05:15 08:20:00"})
    assert metadata.captured is not None
    assert metadata.captured.source == "video_creation_time"
    assert metadata.captured.timezone_unknown is True


def test_exiftool_json_quicktime_gps_coordinates() -> None:
    metadata = metadata_from_exiftool_json(
        {"GPSCoordinates": "46.498011 11.353000 262", "Make": "Apple", "Model": "iPhone 15"}
    )
    assert metadata.position is not None
    assert abs(metadata.position.latitude - 46.498011) < 1e-6
    assert abs(metadata.position.longitude - 11.353) < 1e-6
    assert metadata.position.source == "quicktime"
    assert metadata.camera == "Apple iPhone 15"
