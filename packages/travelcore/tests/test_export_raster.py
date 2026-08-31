from pathlib import Path

from PIL import Image

from travelcore.export.document import PhotoElement
from travelcore.export.geometry import Crop, Frame
from travelcore.export.raster import page_pixels, render_photo_page


def _jpeg(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (40, 20)) -> Path:
    Image.new("RGB", size, color).save(path, format="JPEG", quality=95)
    return path


def _banded(path: Path) -> Path:
    image = Image.new("RGB", (300, 100), (255, 255, 255))
    image.paste((200, 20, 20), (0, 0, 100, 100))
    image.paste((20, 180, 40), (100, 0, 200, 100))
    image.paste((20, 40, 200), (200, 0, 300, 100))
    image.save(path, format="JPEG", quality=95)
    return path


def test_page_pixels_a4_at_300dpi() -> None:
    width, height = page_pixels(210, 297, dpi=300)
    assert width == 2480
    assert height == 3508


def test_missing_source_fills_placeholder(tmp_path: Path) -> None:
    element = PhotoElement(id="p1", source_file_id=9, frame=Frame(0, 0, 100, 100), z=1)
    page = render_photo_page((element,), {}, 20, 10)
    assert page.size == (20, 10)
    assert page.getpixel((10, 5)) == (217, 211, 199)


def test_full_page_photo_covers_the_canvas(tmp_path: Path) -> None:
    red = _jpeg(tmp_path / "red.jpg", (180, 10, 10), size=(80, 80))
    element = PhotoElement(id="p1", source_file_id=1, frame=Frame(0, 0, 100, 100), z=1)
    page = render_photo_page((element,), {1: red}, 40, 40)
    pixel = page.getpixel((20, 20))
    assert pixel[0] > 140
    assert pixel[1] < 40
    assert pixel[2] < 40


def test_higher_z_paints_on_top(tmp_path: Path) -> None:
    red = _jpeg(tmp_path / "red.jpg", (180, 10, 10), size=(40, 40))
    blue = _jpeg(tmp_path / "blue.jpg", (10, 20, 180), size=(40, 40))
    bottom = PhotoElement(id="a", source_file_id=1, frame=Frame(0, 0, 100, 100), z=1)
    top = PhotoElement(id="b", source_file_id=2, frame=Frame(0, 0, 50, 100), z=2)
    page = render_photo_page((bottom, top), {1: red, 2: blue}, 40, 20)
    left = page.getpixel((5, 10))
    right = page.getpixel((35, 10))
    assert left[2] > 140
    assert right[0] > 140


def test_pan_selects_the_source_window(tmp_path: Path) -> None:
    banded = _banded(tmp_path / "bands.jpg")
    left = PhotoElement(
        id="l",
        source_file_id=1,
        frame=Frame(0, 0, 100, 100),
        crop=Crop(scale=1.0, pan_x=-1.0, pan_y=0.0),
        z=1,
    )
    right = PhotoElement(
        id="r",
        source_file_id=1,
        frame=Frame(0, 0, 100, 100),
        crop=Crop(scale=1.0, pan_x=1.0, pan_y=0.0),
        z=1,
    )
    left_page = render_photo_page((left,), {1: banded}, 50, 50)
    right_page = render_photo_page((right,), {1: banded}, 50, 50)
    left_px = left_page.getpixel((25, 25))
    right_px = right_page.getpixel((25, 25))
    assert left_px[0] > right_px[0]
    assert right_px[2] > left_px[2]


def test_rotated_photo_still_covers_the_frame(tmp_path: Path) -> None:
    red = _jpeg(tmp_path / "red.jpg", (180, 10, 10), size=(80, 80))
    element = PhotoElement(
        id="p1",
        source_file_id=1,
        frame=Frame(0, 0, 100, 100),
        crop=Crop(angle=17.0),
        z=1,
    )
    page = render_photo_page((element,), {1: red}, 40, 40)
    pixel = page.getpixel((20, 20))
    assert pixel[0] > 140
    assert pixel[1] < 50
