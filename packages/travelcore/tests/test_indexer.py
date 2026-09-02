from datetime import UTC, datetime
from pathlib import Path

import pytest
from gpx_fixtures import write_gpx
from igc_fixtures import bozen_points, write_igc
from jpeg_fixtures import write_jpeg_with_exif, write_plain_jpeg
from sqlalchemy import func, select

from travelcore.database.models import FileError, GpsPoint, GpsTrack, Photo, Project, SourceFile
from travelcore.database.project_store import OpenProject, ProjectStore
from travelcore.gps.ingest import set_track_external_url
from travelcore.media.indexer import FileIndexer, IndexResult, count_by_kind
from travelcore.media.thumbnails import ensure_photo_and_video_rows
from travelcore.media.types import FileKind
from travelcore.project_settings import load_project_settings
from travelcore.timeline import sync_timeline


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def test_indexer_writes_source_files(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_plain_jpeg(source / "foto.jpg")
    (source / "route.gpx").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"></gpx>',
        encoding="utf-8",
    )

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(session, project, source)
        session.commit()

    assert result.scanned == 2
    assert result.indexed == 2
    assert result.errors == 0
    assert result.by_kind[FileKind.PHOTO.value] == 1
    assert result.by_kind[FileKind.GPS.value] == 1

    with open_project.session_factory() as session:
        rows = list(session.scalars(select(SourceFile)))
        assert len(rows) == 2
        photo = next(row for row in rows if row.file_kind == FileKind.PHOTO.value)
        assert photo.sha256
        assert photo.timezone_unknown is True
        assert photo.captured_at is not None
        assert photo.captured_at_source == "filesystem_mtime"
        assert photo.position_source is None
        assert photo.path.endswith("foto.jpg")
        gps = next(row for row in rows if row.file_kind == FileKind.GPS.value)
        assert gps.captured_at is None
        assert gps.gps_latitude is None
        assert gps.gps_longitude is None
        assert gps.position_source is None

    stored = load_project_settings(open_project.directory)
    assert stored.paths.source_root is not None
    assert Path(stored.paths.source_root) == source.resolve()


def test_indexer_reads_exif_time_and_gps(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "bozen.jpg",
        datetime_original="2025:05:15 15:10:00",
        offset_original="+02:00",
        latitude=(46.0, 30.0, 0.0),
        longitude=(11.0, 21.0, 0.0),
        heading=123.5,
        heading_ref="T",
        focal_length=8.0,
        focal_length_35mm=24,
    )

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source)
        session.commit()

    with open_project.session_factory() as session:
        photo = session.scalar(select(SourceFile))
        assert photo is not None
        assert photo.captured_at_raw == "2025:05:15 15:10:00"
        assert photo.captured_at_source == "exif_datetime_original"
        assert photo.timezone_unknown is False
        assert photo.gps_latitude is not None
        assert photo.gps_longitude is not None
        assert photo.position_source == "exif"
        assert photo.camera == "Canon EOS R6"
        assert photo.heading_degrees is not None
        assert abs(photo.heading_degrees - 123.5) < 1e-6
        assert photo.heading_ref == "T"
        assert photo.heading_source == "gps_img_direction"
        assert photo.focal_length == 8.0
        assert photo.focal_length_35mm == 24.0


def test_indexer_skips_unchanged_files(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_plain_jpeg(source / "foto.jpg")

    indexer = FileIndexer()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        indexer.index(session, project, source)
        session.commit()

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = indexer.index(session, project, source)
        session.commit()

    assert result.skipped_unchanged == 1
    assert result.indexed == 0


def test_corrupt_jpeg_does_not_abort_import(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_plain_jpeg(source / "ok.jpg")
    (source / "broken.jpg").write_bytes(b"not-a-jpeg")

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(session, project, source)
        session.commit()

    assert result.indexed == 2
    assert result.errors == 1
    with open_project.session_factory() as session:
        files = list(session.scalars(select(SourceFile)))
        errors = list(session.scalars(select(FileError)))
        assert len(files) == 2
        assert any(row.stage == "metadata" for row in errors)
        broken = next(row for row in files if row.filename == "broken.jpg")
        assert broken.captured_at is not None
        assert broken.captured_at_source == "filesystem_mtime"


def test_indexer_reads_heic_quicktime_gps(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    (source / "IMG_0001.HEIC").write_bytes(
        b"ftypheic\x00" + b"com.apple.quicktime.location.ISO6709\x00" + b"+46.498011+011.353000+0262.000/"
    )

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(session, project, source)
        session.commit()

    assert result.indexed == 1
    assert result.errors == 0
    with open_project.session_factory() as session:
        photo = session.scalar(select(SourceFile))
        assert photo is not None
        assert photo.gps_latitude is not None
        assert abs(photo.gps_latitude - 46.498011) < 1e-6
        assert photo.position_source == "quicktime"


def test_indexer_reads_heic_embedded_exif_camera_and_gps(open_project: OpenProject, tmp_path: Path) -> None:
    from jpeg_fixtures import jpeg_exif_app1

    source = tmp_path / "media"
    source.mkdir()
    jpeg = write_jpeg_with_exif(
        source / "_template.jpg",
        datetime_original="2025:05:15 15:10:00",
        make="Apple",
        model="iPhone 15 Pro",
        latitude=(46.0, 30.0, 0.0),
        longitude=(11.0, 21.0, 0.0),
    )
    (source / "IMG_0002.HEIC").write_bytes(b"ftypheic" + jpeg_exif_app1(jpeg))
    jpeg.unlink()

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source)
        session.commit()

    with open_project.session_factory() as session:
        photo = session.scalar(select(SourceFile))
        assert photo is not None
        assert photo.camera == "Apple iPhone 15 Pro"
        assert photo.gps_latitude is not None
        assert photo.position_source == "exif"
        assert photo.captured_at_source == "exif_datetime_original"


def test_indexer_matches_photo_without_gps_to_gpx(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "ohne_gps.jpg",
        datetime_original="2025:05:15 15:32:00",
        offset_original="+02:00",
        make="Canon",
        model="EOS R6",
    )
    write_gpx(
        source / "spur.gpx",
        [
            (46.0, 11.0, 260.0, "2025-05-15T13:31:50Z"),
            (46.2, 11.2, 280.0, "2025-05-15T13:32:10Z"),
        ],
    )

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(session, project, source)
        session.commit()

    assert result.errors == 0
    assert result.tracks_ingested == 1
    assert result.track_points == 2
    assert result.positions_matched == 1
    assert result.positions_unmatched == 0

    with open_project.session_factory() as session:
        counts = count_by_kind(session, open_project.project_id)
        assert counts["located"] == 2
        assert counts["matched"] == 1
        assert counts["unlocated"] == 0
        assert counts["other"] == 1
        assert counts["act"] == 0
        assert counts["map"] == 0
        assert counts["flights"] == 0
        photo = session.scalar(select(SourceFile).where(SourceFile.file_kind == FileKind.PHOTO.value))
        assert photo is not None
        assert photo.position_source == "gpx_interpolated"
        assert photo.gps_latitude is not None
        assert abs(photo.gps_latitude - 46.1) < 1e-6
        assert abs((photo.gps_longitude or 0) - 11.1) < 1e-6
        assert photo.position_time_delta_seconds == 10.0
        gps = session.scalar(select(SourceFile).where(SourceFile.file_kind == FileKind.GPS.value))
        assert gps is not None
        assert gps.position_source == "gpx_track"
        assert abs((gps.gps_latitude or 0) - 46.1) < 1e-6
        assert abs((gps.gps_longitude or 0) - 11.1) < 1e-6
        assert _as_utc(gps.captured_at) == datetime(2025, 5, 15, 13, 31, 50, tzinfo=UTC)
        assert gps.captured_at_source == "gpx_track"
        tracks = list(session.scalars(select(GpsTrack)))
        points = list(session.scalars(select(GpsPoint)))
        assert len(tracks) == 1
        assert len(points) == 2


def test_indexer_does_not_overwrite_exif_gps_with_gpx(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "mit_gps.jpg",
        datetime_original="2025:05:15 15:32:00",
        offset_original="+02:00",
        latitude=(46.0, 30.0, 0.0),
        longitude=(11.0, 21.0, 0.0),
    )
    write_gpx(
        source / "spur.gpx",
        [
            (10.0, 20.0, None, "2025-05-15T13:31:50Z"),
            (10.2, 20.2, None, "2025-05-15T13:32:10Z"),
        ],
    )

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source)
        session.commit()

    with open_project.session_factory() as session:
        counts = count_by_kind(session, open_project.project_id)
        assert counts["matched"] == 0
        assert counts["unlocated"] == 0
        photo = session.scalar(select(SourceFile).where(SourceFile.file_kind == FileKind.PHOTO.value))
        assert photo is not None
        assert photo.position_source == "exif"
        assert photo.gps_latitude is not None
        assert abs(photo.gps_latitude - 46.5) < 1e-6


def test_missing_gpx_after_scan_does_not_abort_import(
    open_project: OpenProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_plain_jpeg(source / "ok.jpg")
    gone = write_gpx(
        source / "gone.gpx",
        [(46.0, 11.0, None, None), (46.1, 11.1, None, None)],
    )

    from travelcore.media import indexer as indexer_mod

    real_scan = indexer_mod.scan_source_directory

    def scan_then_unlink(root: Path):  # noqa: ANN202
        found = list(real_scan(root))
        gone.unlink()
        return found

    monkeypatch.setattr(indexer_mod, "scan_source_directory", scan_then_unlink)

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(session, project, source, generate_thumbnails=False)
        session.commit()

    assert result.indexed >= 1
    assert result.errors >= 1
    with open_project.session_factory() as session:
        names = {row.filename for row in session.scalars(select(SourceFile))}
        assert "ok.jpg" in names
        assert "gone.gpx" not in names
        errors = list(session.scalars(select(FileError)))
        assert any("gone.gpx" in row.path for row in errors)


def test_corrupt_gpx_does_not_abort_import(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_plain_jpeg(source / "ok.jpg")
    (source / "broken.gpx").write_text("not-gpx", encoding="utf-8")

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(session, project, source)
        session.commit()

    assert result.indexed == 2
    assert result.errors >= 1
    assert result.positions_unmatched == 1
    with open_project.session_factory() as session:
        files = list(session.scalars(select(SourceFile)))
        errors = list(session.scalars(select(FileError)))
        assert len(files) == 2
        assert any(row.stage == "gpx" for row in errors)
        broken = next(row for row in files if row.filename == "broken.gpx")
        assert broken.gps_latitude is None
        assert broken.captured_at is None
        counts = count_by_kind(session, open_project.project_id)
        assert counts["unlocated"] == 1
        assert counts["matched"] == 0


def test_indexer_fills_gpx_source_file_position_and_time(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_gpx(
        source / "spur.gpx",
        [
            (46.0, 11.0, 260.0, "2025-05-15T13:31:50Z"),
            (46.2, 11.2, 280.0, "2025-05-15T13:32:10Z"),
        ],
    )

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(session, project, source)
        session.commit()

    assert result.errors == 0
    assert result.tracks_ingested == 1
    with open_project.session_factory() as session:
        gps = session.scalar(select(SourceFile).where(SourceFile.file_kind == FileKind.GPS.value))
        assert gps is not None
        assert abs((gps.gps_latitude or 0) - 46.1) < 1e-6
        assert abs((gps.gps_longitude or 0) - 11.1) < 1e-6
        assert gps.gps_altitude is not None
        assert abs(gps.gps_altitude - 270.0) < 1e-6
        assert gps.position_source == "gpx_track"
        assert gps.position_confidence == 0.9
        assert gps.position_time_delta_seconds is None
        assert _as_utc(gps.captured_at) == datetime(2025, 5, 15, 13, 31, 50, tzinfo=UTC)
        assert gps.captured_at_source == "gpx_track"
        assert gps.captured_at_raw is not None
        assert gps.captured_at_raw.startswith("2025-05-15T13:31:50")
        assert gps.timezone_unknown is False


def test_indexer_gpx_reingest_updates_source_file_metadata(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    gpx_path = write_gpx(
        source / "spur.gpx",
        [
            (46.0, 11.0, None, "2025-05-15T13:31:50Z"),
            (46.2, 11.2, None, "2025-05-15T13:32:10Z"),
        ],
    )

    indexer = FileIndexer()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        indexer.index(session, project, source)
        session.commit()

    write_gpx(
        gpx_path,
        [
            (10.0, 20.0, None, "2026-01-01T08:00:00Z"),
            (10.4, 20.4, None, "2026-01-01T08:00:20Z"),
        ],
    )

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        indexer.index(session, project, source)
        session.commit()

    with open_project.session_factory() as session:
        gps = session.scalar(select(SourceFile).where(SourceFile.file_kind == FileKind.GPS.value))
        assert gps is not None
        assert abs((gps.gps_latitude or 0) - 10.2) < 1e-6
        assert abs((gps.gps_longitude or 0) - 20.2) < 1e-6
        assert _as_utc(gps.captured_at) == datetime(2026, 1, 1, 8, 0, 0, tzinfo=UTC)
        assert gps.position_source == "gpx_track"

    gpx_path.write_text("<gpx></gpx>", encoding="utf-8")
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        indexer.index(session, project, source)
        session.commit()

    with open_project.session_factory() as session:
        gps = session.scalar(select(SourceFile).where(SourceFile.file_kind == FileKind.GPS.value))
        assert gps is not None
        assert gps.gps_latitude is None
        assert gps.captured_at is None
        assert gps.position_source is None
        assert gps.captured_at_source is None


def test_indexer_skips_unchanged_gpx_track_rewrite(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_gpx(
        source / "spur.gpx",
        [
            (46.0, 11.0, 260.0, "2025-05-15T13:31:50Z"),
            (46.2, 11.2, 280.0, "2025-05-15T13:32:10Z"),
        ],
    )
    indexer = FileIndexer()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        first = indexer.index(session, project, source, generate_thumbnails=False)
        session.commit()
        point_ids = [row.id for row in session.scalars(select(GpsPoint))]

    assert first.tracks_ingested == 1
    assert first.tracks_skipped == 0
    assert point_ids

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        second = indexer.index(session, project, source, generate_thumbnails=False)
        session.commit()
        same_ids = [row.id for row in session.scalars(select(GpsPoint))]

    assert second.skipped_unchanged >= 1
    assert second.tracks_ingested == 0
    assert second.tracks_skipped == 1
    assert same_ids == point_ids


def test_indexer_does_not_rehash_unchanged_gpx(
    open_project: OpenProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_gpx(
        source / "spur.gpx",
        [
            (46.0, 11.0, 260.0, "2025-05-15T13:31:50Z"),
            (46.2, 11.2, 280.0, "2025-05-15T13:32:10Z"),
        ],
    )
    indexer = FileIndexer()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        indexer.index(session, project, source, generate_thumbnails=False)
        session.commit()

    def fail_hash(_path: Path, *, chunk_size: int = 0) -> str:
        raise AssertionError("unchanged GPS must not be hashed on the writer thread")

    monkeypatch.setattr("travelcore.media.indexer.sha256_file", fail_hash)
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        second = FileIndexer().index(session, project, source, generate_thumbnails=False)
        session.commit()
    assert second.tracks_skipped == 1


def test_indexer_untimed_gpx_sets_position_without_date(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_gpx(
        source / "ohne_zeit.gpx",
        [
            (46.0, 11.0, None, None),
            (46.2, 11.2, None, None),
        ],
    )

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source)
        session.commit()

    with open_project.session_factory() as session:
        gps = session.scalar(select(SourceFile))
        assert gps is not None
        assert abs((gps.gps_latitude or 0) - 46.1) < 1e-6
        assert gps.captured_at is None
        assert gps.captured_at_source is None
        assert gps.position_source == "gpx_track"


def test_empty_gpx_does_not_abort_import(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_plain_jpeg(source / "ok.jpg")
    (source / "empty.gpx").write_text("<gpx></gpx>", encoding="utf-8")

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(session, project, source)
        session.commit()

    assert result.errors == 0
    with open_project.session_factory() as session:
        gps = session.scalar(select(SourceFile).where(SourceFile.file_kind == FileKind.GPS.value))
        assert gps is not None
        assert gps.gps_latitude is None
        assert gps.captured_at is None


def test_indexer_writes_thumbnail_and_photo_row(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    jpeg = write_plain_jpeg(source / "platz.jpg")
    original_mtime = jpeg.stat().st_mtime

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()

    assert result.thumbnails_written == 1
    thumbs = list((open_project.directory / "thumbnails").glob("*.jpg"))
    assert len(thumbs) == 1
    assert jpeg.stat().st_mtime == original_mtime
    with open_project.session_factory() as session:
        photo = session.scalar(select(Photo))
        assert photo is not None
        assert photo.is_favorite is False


def test_indexer_writes_igc_and_gpx_thumbnails(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_gpx(
        source / "spur.gpx",
        [
            (46.0, 11.0, None, "2025-05-15T13:31:50Z"),
            (46.2, 11.2, None, "2025-05-15T13:32:10Z"),
        ],
    )
    write_igc(source / "flug.igc", bozen_points())

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()

    assert result.thumbnails_written == 2
    thumbs = list((open_project.directory / "thumbnails").glob("*.jpg"))
    assert len(thumbs) == 2


def test_indexer_writes_video_thumbnail(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    jpeg = write_plain_jpeg(tmp_path / "inner.jpg", size=(40, 30))
    (source / "clip.mp4").write_bytes(b"ftypisom" + jpeg.read_bytes())

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()

    assert result.by_kind[FileKind.VIDEO.value] == 1
    assert result.thumbnails_written == 1
    assert list((open_project.directory / "thumbnails").glob("*.jpg"))


def test_indexer_does_not_regenerate_thumbnails_on_reimport(
    open_project: OpenProject, tmp_path: Path
) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_plain_jpeg(source / "platz.jpg")
    indexer = FileIndexer()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        first = indexer.index(session, project, source, project_dir=open_project.directory)
        session.commit()
    thumbs = list((open_project.directory / "thumbnails").glob("*.jpg"))
    assert first.thumbnails_written == 1
    assert first.media_changed is True
    assert len(thumbs) == 1
    stamp = thumbs[0].stat().st_mtime

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        second = indexer.index(session, project, source, project_dir=open_project.directory)
        session.commit()

    assert second.media_changed is False
    assert second.thumbnails_written == 0
    assert thumbs[0].stat().st_mtime == stamp


def test_ensure_photo_rows_then_previews_still_write_thumbs(
    open_project: OpenProject, tmp_path: Path
) -> None:
    """Photo rows from timeline sync must not block thumbnail generation on import."""

    source = tmp_path / "media"
    source.mkdir()
    write_plain_jpeg(source / "platz.jpg")
    indexer = FileIndexer()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        indexer.index(
            session,
            project,
            source,
            project_dir=open_project.directory,
            generate_thumbnails=False,
        )
        session.commit()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        sync_timeline(session, project)
        ensure_photo_and_video_rows(session, project)
        session.commit()
        assert session.scalar(select(func.count()).select_from(Photo)) == 1
    result = IndexResult(media_changed=True)
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        indexer.build_previews(session, project, result, None, open_project.directory)
        session.commit()
        assert session.scalar(select(func.count()).select_from(Photo)) == 1
    assert result.thumbnails_written == 1
    assert list((open_project.directory / "thumbnails").glob("*.jpg"))


def test_reimport_writes_missing_thumbnails(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_plain_jpeg(source / "platz.jpg")
    indexer = FileIndexer()
    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        indexer.index(session, project, source, project_dir=open_project.directory)
        session.commit()
    for path in thumbs.glob("*.jpg"):
        path.unlink()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        second = indexer.index(session, project, source, project_dir=open_project.directory)
        session.commit()
    assert second.media_changed is False
    assert second.thumbnails_written == 1
    assert list(thumbs.glob("*.jpg"))


def test_indexer_does_not_count_thumbnails_when_source_is_project(
    open_project: OpenProject,
) -> None:
    source = open_project.directory
    write_plain_jpeg(source / "foto.jpg")
    indexer = FileIndexer()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        first = indexer.index(session, project, source, project_dir=open_project.directory)
        session.commit()
    assert first.by_kind[FileKind.PHOTO.value] == 1
    assert list((open_project.directory / "thumbnails").glob("*.jpg"))

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        second = indexer.index(session, project, source, project_dir=open_project.directory)
        session.commit()
        counts = count_by_kind(session, open_project.project_id)
    assert second.by_kind[FileKind.PHOTO.value] == 1
    assert counts[FileKind.PHOTO.value] == 1


def test_indexer_drops_previously_indexed_thumbnails(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_plain_jpeg(source / "foto.jpg")
    thumb = open_project.directory / "thumbnails" / "abc_256.jpg"
    write_plain_jpeg(thumb)
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        session.add(
            SourceFile(
                project_id=project.id,
                path=str(thumb),
                filename=thumb.name,
                file_kind="photo",
                extension=".jpg",
                size_bytes=thumb.stat().st_size,
                imported_at=project.created_at,
                status="ok",
                timezone_unknown=True,
            )
        )
        session.commit()

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, generate_thumbnails=False)
        session.commit()
        counts = count_by_kind(session, open_project.project_id)
        paths = [row.path for row in session.scalars(select(SourceFile))]
    assert counts[FileKind.PHOTO.value] == 1
    assert str(thumb) not in paths


def test_plan_source_sync_counts_new_and_missing(open_project: OpenProject, tmp_path: Path) -> None:
    from travelcore.media.purge import plan_source_sync

    source = tmp_path / "media"
    source.mkdir()
    write_plain_jpeg(source / "keep.jpg")
    gone = write_plain_jpeg(source / "gone.jpg")
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, generate_thumbnails=False)
        session.commit()
    gone.unlink()
    write_plain_jpeg(source / "neu.jpg")
    with open_project.session_factory() as session:
        plan = plan_source_sync(session, open_project.project_id, source)
    assert plan.new_count == 1
    assert plan.missing_count == 1
    assert plan.present_count == 1
    assert plan.new_names == ("neu.jpg",)
    assert plan.missing_names == ("gone.jpg",)


def test_indexer_keeps_missing_files_without_sync_flag(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_plain_jpeg(source / "keep.jpg")
    gone = write_plain_jpeg(source / "gone.jpg")
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, generate_thumbnails=False)
        session.commit()
    gone.unlink()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(session, project, source, generate_thumbnails=False)
        session.commit()
        names = {row.filename for row in session.scalars(select(SourceFile))}
    assert result.removed == 0
    assert names == {"keep.jpg", "gone.jpg"}


def test_indexer_sync_removes_missing_photo_from_journal(open_project: OpenProject, tmp_path: Path) -> None:
    from travelcore.config import DEFAULT_THUMBNAIL_SIZE
    from travelcore.database.models import FileError, SectionMember, TripSection
    from travelcore.media.thumbnails import cached_thumbnail_path
    from travelcore.timeline.sections import park_media

    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "keep.jpg",
        datetime_original="2025:06:01 10:00:00",
        offset_original="+02:00",
    )
    gone_path = write_jpeg_with_exif(
        source / "gone.jpg",
        datetime_original="2025:06:01 11:00:00",
        offset_original="+02:00",
    )
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(
            session, project, source, project_dir=open_project.directory, generate_thumbnails=True
        )
        session.commit()
        sync_timeline(session, project, thumbs_dir=open_project.directory / "thumbnails")
        gone = session.scalar(select(SourceFile).where(SourceFile.filename == "gone.jpg"))
        keep = session.scalar(select(SourceFile).where(SourceFile.filename == "keep.jpg"))
        assert gone is not None and keep is not None
        gone_id = gone.id
        keep_id = keep.id
        gone_sha = gone.sha256
        session.add(
            FileError(
                project_id=project.id,
                path=gone.path,
                stage="index",
                message="alte Warnung",
            )
        )
        section = session.scalar(select(TripSection))
        assert section is not None
        section.cover_source_file_id = gone_id
        session.commit()
    thumb = cached_thumbnail_path(
        open_project.directory / "thumbnails",
        source_file_id=gone_id,
        sha256=gone_sha,
        size=DEFAULT_THUMBNAIL_SIZE,
    )
    assert thumb.is_file()
    gone_path.unlink()
    write_jpeg_with_exif(
        source / "neu.jpg",
        datetime_original="2025:06:02 09:00:00",
        offset_original="+02:00",
    )
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(
            session,
            project,
            source,
            project_dir=open_project.directory,
            generate_thumbnails=True,
            remove_missing=True,
        )
        park_media(session, result.new_media_ids)
        sync_timeline(session, project, thumbs_dir=open_project.directory / "thumbnails")
        session.commit()
        names = {row.filename: row for row in session.scalars(select(SourceFile))}
        member_ids = set(session.scalars(select(SectionMember.source_file_id)))
        errors = list(session.scalars(select(FileError)))
        section = session.scalar(select(TripSection).where(TripSection.cover_source_file_id == gone_id))
    assert result.removed == 1
    assert result.indexed == 1
    assert "gone.jpg" not in names
    assert "keep.jpg" in names
    assert "neu.jpg" in names
    assert names["neu.jpg"].parked is True
    assert keep_id in member_ids
    assert names["neu.jpg"].id not in member_ids
    assert errors == []
    assert section is None
    assert not thumb.is_file()


def test_indexer_sync_deletes_gps_track_for_missing_gpx(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_plain_jpeg(source / "foto.jpg")
    gpx = write_gpx(
        source / "spur.gpx",
        [
            (46.0, 11.0, 260.0, "2025-05-15T13:31:50Z"),
            (46.2, 11.2, 280.0, "2025-05-15T13:32:10Z"),
        ],
    )
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, generate_thumbnails=False)
        session.commit()
        assert session.scalar(select(func.count()).select_from(GpsTrack)) == 1
        assert session.scalar(select(func.count()).select_from(GpsPoint)) >= 2
    gpx.unlink()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(
            session, project, source, generate_thumbnails=False, remove_missing=True
        )
        session.commit()
        names = {row.filename for row in session.scalars(select(SourceFile))}
        tracks = session.scalar(select(func.count()).select_from(GpsTrack))
        points = session.scalar(select(func.count()).select_from(GpsPoint))
    assert result.removed == 1
    assert names == {"foto.jpg"}
    assert tracks == 0
    assert points == 0


def test_indexer_can_defer_thumbnails(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_plain_jpeg(source / "platz.jpg")
    indexer = FileIndexer()
    thumbs = open_project.directory / "thumbnails"

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = indexer.index(
            session,
            project,
            source,
            project_dir=open_project.directory,
            generate_thumbnails=False,
        )
        session.commit()

    assert result.thumbnails_written == 0
    assert not list(thumbs.glob("*.jpg"))

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        indexer.build_previews(session, project, result, None, open_project.directory)
        session.commit()

    assert result.thumbnails_written == 1
    assert list(thumbs.glob("*.jpg"))


def test_indexer_writes_thumbnails_in_parallel(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    for index in range(4):
        write_plain_jpeg(source / f"foto_{index}.jpg", size=(16 + index, 12 + index))

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer(max_workers=2).index(
            session,
            project,
            source,
            project_dir=open_project.directory,
        )
        session.commit()

    assert result.thumbnails_written == 4
    assert result.errors == 0
    assert len(list((open_project.directory / "thumbnails").glob("*.jpg"))) == 4


def test_indexer_checkpoint_commits_partial_progress(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    for index in range(5):
        write_plain_jpeg(source / f"foto_{index}.jpg")
    visible: list[int] = []
    indexer = FileIndexer()

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None

        def checkpoint() -> None:
            session.commit()
            with open_project.session_factory() as other:
                visible.append(other.scalar(select(func.count()).select_from(SourceFile)) or 0)

        indexer.index(
            session,
            project,
            source,
            project_dir=open_project.directory,
            generate_thumbnails=False,
            checkpoint=checkpoint,
            checkpoint_every=2,
        )
        session.commit()

    assert visible[0] >= 1
    assert visible[-1] == 5
    assert any(count < 5 for count in visible[:-1])


def test_indexer_parallel_matches_sequential(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    for index in range(4):
        write_jpeg_with_exif(
            source / f"foto_{index}.jpg",
            datetime_original="2025:05:15 15:10:00",
            make="Canon",
            model="EOS R6",
        )

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        sequential = FileIndexer(max_workers=1).index(session, project, source, generate_thumbnails=False)
        session.commit()

    hashes = _source_hashes(open_project)

    other_dir = tmp_path / "projekt_pool"
    pooled_project = ProjectStore().create(other_dir, "Pool")
    with pooled_project.session_factory() as session:
        project = session.get(Project, pooled_project.project_id)
        assert project is not None
        pooled = FileIndexer(max_workers=2).index(session, project, source, generate_thumbnails=False)
        session.commit()

    assert sequential.indexed == pooled.indexed == 4
    assert sequential.errors == pooled.errors == 0
    assert hashes == _source_hashes(pooled_project)


def _source_hashes(opened: OpenProject) -> dict[str, str | None]:
    with opened.session_factory() as session:
        rows = list(session.scalars(select(SourceFile)))
        return {Path(row.path).name: row.sha256 for row in rows}


def test_indexer_reads_igc_pilot_and_track(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_igc(source / "flug.igc", bozen_points(), pilot="Ralf Muster")

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(session, project, source, generate_thumbnails=False)
        session.commit()

    assert result.errors == 0
    assert result.tracks_ingested == 1
    assert result.track_points == 2
    with open_project.session_factory() as session:
        gps = session.scalar(select(SourceFile).where(SourceFile.file_kind == FileKind.GPS.value))
        assert gps is not None
        assert gps.camera == "Ralf Muster"
        assert gps.position_source == "igc_track"
        assert gps.captured_at_source == "igc_track"
        track = session.scalar(select(GpsTrack))
        assert track is not None
        assert track.track_format == "igc"
        assert track.pilot == "Ralf Muster"
        assert track.external_url is None


def test_indexer_matches_photo_without_gps_to_igc(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "ohne_gps.jpg",
        datetime_original="2025:05:15 14:32:00",
        offset_original="+02:00",
        make="Canon",
        model="EOS R6",
    )
    write_igc(source / "flug.igc", bozen_points())

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(session, project, source, generate_thumbnails=False)
        session.commit()

    assert result.positions_matched == 1
    with open_project.session_factory() as session:
        photo = session.scalar(select(SourceFile).where(SourceFile.file_kind == FileKind.PHOTO.value))
        assert photo is not None
        assert photo.position_source == "igc_interpolated"
        assert photo.gps_latitude is not None


def test_indexer_preserves_igc_dhv_url_on_reingest(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_igc(source / "flug.igc", bozen_points())
    indexer = FileIndexer()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        indexer.index(session, project, source, generate_thumbnails=False)
        gps = session.scalar(select(SourceFile).where(SourceFile.file_kind == FileKind.GPS.value))
        assert gps is not None
        set_track_external_url(session, gps.id, "https://de.dhv.de/dbnx/nx.php?id=42")
        session.commit()

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        indexer.index(session, project, source, generate_thumbnails=False)
        session.commit()

    with open_project.session_factory() as session:
        track = session.scalar(select(GpsTrack))
        assert track is not None
        assert track.external_url == "https://de.dhv.de/dbnx/nx.php?id=42"


def test_indexer_preserves_rotation_on_reingest(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "foto.jpg",
        datetime_original="2025:05:15 08:20:00",
        offset_original="+02:00",
    )
    indexer = FileIndexer()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        indexer.index(session, project, source, generate_thumbnails=False)
        photo = session.scalar(select(SourceFile).where(SourceFile.file_kind == FileKind.PHOTO.value))
        assert photo is not None
        photo.rotation_degrees = 90
        session.commit()

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        indexer.index(session, project, source, generate_thumbnails=False)
        session.commit()

    with open_project.session_factory() as session:
        photo = session.scalar(select(SourceFile).where(SourceFile.file_kind == FileKind.PHOTO.value))
        assert photo is not None
        assert photo.rotation_degrees == 90


def test_set_track_url_rejects_non_http(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_igc(source / "flug.igc", bozen_points())
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, generate_thumbnails=False)
        gps = session.scalar(select(SourceFile).where(SourceFile.file_kind == FileKind.GPS.value))
        assert gps is not None
        with pytest.raises(ValueError, match="http"):
            set_track_external_url(session, gps.id, "javascript:alert(1)")


def test_indexer_matches_photo_without_gps_to_nearby_photo(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "mit_gps.jpg",
        datetime_original="2025:05:15 15:32:00",
        offset_original="+02:00",
        latitude=(46.0, 30.0, 0.0),
        longitude=(11.0, 21.0, 0.0),
    )
    write_jpeg_with_exif(
        source / "ohne_gps.jpg",
        datetime_original="2025:05:15 15:32:10",
        offset_original="+02:00",
        make="Canon",
        model="EOS R6",
    )

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = FileIndexer().index(session, project, source, generate_thumbnails=False)
        session.commit()

    assert result.positions_matched == 1
    with open_project.session_factory() as session:
        counts = count_by_kind(session, open_project.project_id)
        assert counts["matched"] == 1
        assert counts["unlocated"] == 0
        photo = session.scalar(select(SourceFile).where(SourceFile.filename == "ohne_gps.jpg"))
        assert photo is not None
        assert photo.position_source == "photo_nearest"
        assert photo.gps_latitude is not None
        assert abs(photo.gps_latitude - 46.5) < 1e-6
        assert abs((photo.gps_longitude or 0) - 11.35) < 1e-6


def test_indexer_prefers_photo_gps_over_gpx(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "mit_gps.jpg",
        datetime_original="2025:05:15 15:32:00",
        offset_original="+02:00",
        latitude=(46.0, 30.0, 0.0),
        longitude=(11.0, 21.0, 0.0),
    )
    write_jpeg_with_exif(
        source / "ohne_gps.jpg",
        datetime_original="2025:05:15 15:32:10",
        offset_original="+02:00",
        make="Canon",
        model="EOS R6",
    )
    write_gpx(
        source / "spur.gpx",
        [
            (46.0, 11.0, 260.0, "2025-05-15T13:31:50Z"),
            (46.2, 11.2, 280.0, "2025-05-15T13:32:10Z"),
        ],
    )

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, generate_thumbnails=False)
        session.commit()

    with open_project.session_factory() as session:
        photo = session.scalar(select(SourceFile).where(SourceFile.filename == "ohne_gps.jpg"))
        assert photo is not None
        assert photo.position_source == "photo_nearest"
        assert photo.gps_latitude is not None
        assert abs(photo.gps_latitude - 46.5) < 1e-6


def test_indexer_prefers_gpx_over_igc(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "ohne_gps.jpg",
        datetime_original="2025:05:15 14:32:00",
        offset_original="+02:00",
        make="Canon",
        model="EOS R6",
    )
    write_gpx(
        source / "spur.gpx",
        [
            (46.0, 11.0, 260.0, "2025-05-15T12:31:50Z"),
            (46.2, 11.2, 280.0, "2025-05-15T12:32:10Z"),
        ],
    )
    write_igc(source / "flug.igc", bozen_points())

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, generate_thumbnails=False)
        session.commit()

    with open_project.session_factory() as session:
        photo = session.scalar(select(SourceFile).where(SourceFile.file_kind == FileKind.PHOTO.value))
        assert photo is not None
        assert photo.position_source == "gpx_interpolated"
        assert photo.gps_latitude is not None
        assert abs(photo.gps_latitude - 46.1) < 1e-6
