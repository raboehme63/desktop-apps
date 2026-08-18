from pathlib import Path

from sqlalchemy import select

from travelcore.database.models import Project, SourceFile
from travelcore.database.project_store import ProjectStore
from travelcore.media.indexer import FileIndexer

MIN_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


def test_project_survives_close_and_reopen(tmp_path: Path) -> None:
    project_dir = tmp_path / "reise_italien"
    source = tmp_path / "fotos"
    nested = source / "tag1"
    nested.mkdir(parents=True)
    (nested / "piazza.jpg").write_bytes(MIN_JPEG)
    (source / "notes.txt").write_text("Ankunft", encoding="utf-8")

    store = ProjectStore()
    opened = store.create(project_dir, "Italien")
    with opened.session_factory() as session:
        project = session.get(Project, opened.project_id)
        assert project is not None
        FileIndexer().index(session, project, source)
        session.commit()

    reopened = store.open(project_dir)
    with reopened.session_factory() as session:
        files = list(session.scalars(select(SourceFile)))
        names = {row.filename for row in files}
        project = session.get(Project, reopened.project_id)
        assert project is not None
        assert project.name == "Italien"
        assert project.source_root == str(source.resolve())
        assert names == {"piazza.jpg", "notes.txt"}
