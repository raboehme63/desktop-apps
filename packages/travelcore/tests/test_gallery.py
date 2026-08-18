from pathlib import Path

from jpeg_fixtures import write_jpeg_with_exif, write_plain_jpeg

from travelcore.database.models import Project
from travelcore.database.project_store import OpenProject
from travelcore.media.gallery import list_gallery_items
from travelcore.media.indexer import FileIndexer


def test_gallery_lists_photos_in_capture_order(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "spaeter.jpg",
        datetime_original="2025:05:15 18:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "frueher.jpg",
        datetime_original="2025:05:15 08:20:00",
        offset_original="+02:00",
    )
    write_plain_jpeg(source / "ohne_exif.jpg")

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()

    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        items = list_gallery_items(session, open_project.project_id, thumbs, size=256)

    names = [item.filename for item in items]
    assert names[0] == "frueher.jpg"
    assert names[1] == "spaeter.jpg"
    assert len(items) == 3
    assert all(item.thumbnail_path.parent == thumbs for item in items)
    assert any(item.thumbnail_path.is_file() for item in items)
