from PIL import Image

from travelcore.media.orientation import (
    apply_display_rotation,
    can_rotate_media,
    normalize_rotation_degrees,
    orient_image,
)


def test_normalize_rotation_degrees_snaps_to_right_angles() -> None:
    assert normalize_rotation_degrees(None) == 0
    assert normalize_rotation_degrees(0) == 0
    assert normalize_rotation_degrees(90) == 90
    assert normalize_rotation_degrees(180) == 180
    assert normalize_rotation_degrees(270) == 270
    assert normalize_rotation_degrees(360) == 0
    assert normalize_rotation_degrees(-90) == 270
    assert normalize_rotation_degrees(45) == 90


def test_apply_display_rotation_clockwise_moves_top_left() -> None:
    image = Image.new("RGB", (40, 20), "red")
    image.putpixel((0, 0), (0, 255, 0))
    rotated = apply_display_rotation(image, 90)
    assert rotated.size == (20, 40)
    assert rotated.getpixel((19, 0)) == (0, 255, 0)


def test_orient_image_applies_exif_then_user_rotation(tmp_path) -> None:
    from jpeg_fixtures import write_jpeg_with_exif

    path = write_jpeg_with_exif(tmp_path / "exif.jpg", size=(40, 20), orientation=1)
    with Image.open(path) as opened:
        rotated = orient_image(opened, rotation_degrees=90)
        assert rotated.size == (20, 40)


def test_can_rotate_photos_and_videos_not_tracks() -> None:
    assert can_rotate_media(".jpg")
    assert can_rotate_media(".HEIC")
    assert can_rotate_media(".mp4")
    assert not can_rotate_media(".gpx")
    assert not can_rotate_media(".igc")
