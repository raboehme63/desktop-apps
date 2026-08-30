from pathlib import Path

from jpeg_fixtures import write_plain_jpeg
from PIL import Image, ImageFilter
from sqlalchemy import select

from travelcore.database.models import Photo, PhotoAnalysis, Project, SourceFile
from travelcore.image_analysis.analyze import analyze_project_photos
from travelcore.image_analysis.quality import (
    GREEN_MIN,
    QUALITY_GREEN,
    QUALITY_RED,
    QUALITY_YELLOW,
    YELLOW_MIN,
    PillowQualityAnalyzer,
    analyze_photo,
    quality_light,
    quality_tooltip,
)
from travelcore.media.gallery import list_gallery_items
from travelcore.media.indexer import FileIndexer
from travelcore.timeline.build import set_photo_sort_status


def _checkerboard(path: Path, size: tuple[int, int] = (1920, 1280)) -> Path:
    tile = Image.new("RGB", (2, 2))
    tile.putpixel((0, 0), (240, 240, 240))
    tile.putpixel((1, 1), (240, 240, 240))
    tile.putpixel((0, 1), (20, 20, 20))
    tile.putpixel((1, 0), (20, 20, 20))
    tile.resize(size, Image.Resampling.NEAREST).save(path, format="JPEG", quality=95)
    return path


def test_quality_light_thresholds() -> None:
    assert quality_light(None) is None
    assert quality_light(GREEN_MIN) == QUALITY_GREEN
    assert quality_light(YELLOW_MIN) == QUALITY_YELLOW
    assert quality_light(YELLOW_MIN - 0.01) == QUALITY_RED


def test_quality_tooltip_names_decisive_parts() -> None:
    assert quality_tooltip(technical_quality=None) is None
    assert quality_tooltip(technical_quality=0.8) == "Qualität gut"
    tiny = quality_tooltip(
        technical_quality=0.2,
        resolution_score=0.1,
        width=32,
        height=24,
    )
    assert tiny is not None
    assert tiny.startswith("Qualität schwach")
    assert "Auflösung schwach" in tiny
    dark = quality_tooltip(
        technical_quality=0.5,
        resolution_score=0.8,
        sharpness=20.0,
        contrast=0.2,
        underexposed=True,
        width=1920,
        height=1280,
    )
    assert dark is not None
    assert dark.startswith("Qualität mittel")
    assert "unterbelichtet" in dark
    assert "Auflösung" not in dark


def test_sharp_large_photo_is_green(tmp_path: Path) -> None:
    path = _checkerboard(tmp_path / "sharp.jpg")
    mtime = path.stat().st_mtime
    metrics = PillowQualityAnalyzer().analyze(path)
    assert metrics.light == QUALITY_GREEN
    assert metrics.technical_quality is not None
    assert metrics.technical_quality >= GREEN_MIN
    assert metrics.width == 1920
    assert metrics.height == 1280
    assert metrics.aspect_ratio == 1920 / 1280
    assert metrics.overexposed is False
    assert metrics.underexposed is False
    assert path.stat().st_mtime == mtime


def test_tiny_photo_is_red(tmp_path: Path) -> None:
    path = write_plain_jpeg(tmp_path / "tiny.jpg", size=(32, 24))
    metrics = analyze_photo(path)
    assert metrics.light == QUALITY_RED
    assert metrics.technical_quality is not None
    assert metrics.technical_quality < YELLOW_MIN


def test_dark_photo_is_not_green(tmp_path: Path) -> None:
    path = tmp_path / "dark.jpg"
    Image.new("RGB", (1920, 1280), (3, 3, 3)).save(path, format="JPEG", quality=90)
    metrics = analyze_photo(path)
    assert metrics.underexposed is True
    assert metrics.light in {QUALITY_YELLOW, QUALITY_RED}
    assert metrics.light != QUALITY_GREEN


def test_blurred_photo_scores_below_sharp(tmp_path: Path) -> None:
    sharp = _checkerboard(tmp_path / "sharp.jpg")
    blur = tmp_path / "blur.jpg"
    with Image.open(sharp) as image:
        image.filter(ImageFilter.GaussianBlur(radius=28)).save(blur, format="JPEG", quality=85)
    assert (analyze_photo(sharp).technical_quality or 0) > (analyze_photo(blur).technical_quality or 0)
    assert analyze_photo(blur).light in {QUALITY_YELLOW, QUALITY_RED}


def test_analyze_project_writes_ampel_without_changing_rating(open_project, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    good = _checkerboard(source / "good.jpg")
    write_plain_jpeg(source / "tiny.jpg", size=(32, 24))
    mtime = good.stat().st_mtime
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source)
        session.commit()
    with open_project.session_factory() as session:
        photo = session.scalar(select(Photo).join(SourceFile).where(SourceFile.filename == "good.jpg"))
        assert photo is not None
        set_photo_sort_status(session, photo.source_file_id, "favorite")
        session.commit()

    with open_project.session_factory() as session:
        first = analyze_project_photos(session, open_project.project_id)
        session.commit()
    assert first.analyzed == 2
    assert first.skipped == 0
    assert good.stat().st_mtime == mtime

    with open_project.session_factory() as session:
        again = analyze_project_photos(session, open_project.project_id)
        session.commit()
    assert again.analyzed == 0
    assert again.skipped == 2

    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        items = {item.filename: item for item in list_gallery_items(session, open_project.project_id, thumbs)}
        analyses = list(session.scalars(select(PhotoAnalysis)))
        photo = session.scalar(select(Photo).join(SourceFile).where(SourceFile.filename == "good.jpg"))
    assert items["good.jpg"].quality_light == QUALITY_GREEN
    assert items["good.jpg"].quality_tooltip == "Qualität gut"
    assert items["tiny.jpg"].quality_light == QUALITY_RED
    assert items["tiny.jpg"].quality_tooltip is not None
    assert items["tiny.jpg"].quality_tooltip.startswith("Qualität schwach")
    assert "Auflösung schwach" in items["tiny.jpg"].quality_tooltip
    assert len(analyses) == 2
    assert photo is not None
    assert photo.sort_status == "favorite"
    assert photo.is_favorite is True


def test_analyze_project_reports_progress(open_project, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    _checkerboard(source / "a.jpg")
    write_plain_jpeg(source / "b.jpg", size=(32, 24))
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source)
        session.commit()

    ticks: list[tuple[int, int]] = []
    with open_project.session_factory() as session:
        analyze_project_photos(
            session, open_project.project_id, progress=lambda current, total: ticks.append((current, total))
        )
        session.commit()
    assert ticks[0] == (0, 2)
    assert ticks[-1][0] == 2
    assert ticks[-1][1] == 2
    assert all(total == 2 for _current, total in ticks)
