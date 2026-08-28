from pathlib import Path

from travelcore.database.models import Project
from travelcore.database.project_store import OpenProject
from travelcore.gps.parsers import GpxParser, IgcParser, parser_for_path
from travelcore.media.indexer import FileIndexer, ScanStage, default_index_stages
from travelcore.pipeline import PipelineStage, run_pipeline


def test_default_index_stages_are_named_and_ordered() -> None:
    names = [stage.name for stage in default_index_stages()]
    assert names == ["scan", "extract", "persist", "gps", "preview"]
    assert all(isinstance(stage, PipelineStage) for stage in default_index_stages())


def test_file_indexer_accepts_custom_stages(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    (source / "note.txt").write_text("hello", encoding="utf-8")
    seen: list[str] = []

    class RecordingStage:
        name = "record"

        def run(self, ctx: object) -> None:
            seen.append("record")

    indexer = FileIndexer(compute_hash=False, stages=(ScanStage(), RecordingStage()))
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        result = indexer.index(session, project, source, generate_thumbnails=False)
        session.commit()
    assert seen == ["record"]
    assert result.scanned == 1


def test_run_pipeline_invokes_stages_in_order() -> None:
    log: list[str] = []

    class First:
        name = "first"

        def run(self, ctx: list[str]) -> None:
            ctx.append(self.name)

    class Second:
        name = "second"

        def run(self, ctx: list[str]) -> None:
            ctx.append(self.name)

    result = run_pipeline(log, (First(), Second()))
    assert result == ["first", "second"]


def test_track_parser_registry() -> None:
    assert isinstance(parser_for_path(Path("a.gpx")), GpxParser)
    assert isinstance(parser_for_path(Path("a.igc")), IgcParser)
    assert parser_for_path(Path("a.kml")) is None
    assert parser_for_path(Path("a.geojson")) is None
