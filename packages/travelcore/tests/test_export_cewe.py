from datetime import UTC, date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from travelcore.exceptions import ExportError
from travelcore.export.book import KIND_PHOTOS, book_pages
from travelcore.export.cewe import export_mcf_filename, export_travelbook_mcf, normalize_mcf_save_path
from travelcore.export.document import TravelbookDocument, sync_document
from travelcore.export.mcfproduct import MIN_CONTENT_PAGES, PRODUCT_NAME, padded_content_count
from travelcore.export.mcfwrite import content_pages, mcf_folder_name
from travelcore.timeline.types import TimelineEntry, TimelinePhoto, TimelineSection, TimelineSnapshot


def _photo(source_id: int, path: Path, **kwargs: object) -> TimelinePhoto:
    values: dict[str, object] = {
        "source_file_id": source_id,
        "filename": path.name,
        "path": str(path),
        "thumbnail_path": path,
        "captured_at": None,
        "used_in_journal": True,
        "is_cover": False,
        "is_favorite": False,
        "gps_latitude": None,
        "gps_longitude": None,
        "file_kind": "photo",
    }
    values.update(kwargs)
    return TimelinePhoto(**values)  # type: ignore[arg-type]


def _section(section_id: int, items: tuple[TimelinePhoto, ...], **kwargs: object) -> TimelineSection:
    values: dict[str, object] = {
        "id": section_id,
        "kind": "day",
        "mode": None,
        "title": "Bozen",
        "notes": "Erstes Tal.",
        "started_at": datetime(2026, 8, 1, tzinfo=UTC),
        "ended_at": datetime(2026, 8, 1, tzinfo=UTC),
        "location_name": None,
        "location_from": None,
        "location_to": None,
        "origin": "manual",
        "items": items,
        "cover_source_file_id": items[0].source_file_id if items else None,
    }
    values.update(kwargs)
    return TimelineSection(**values)  # type: ignore[arg-type]


def _snapshot(*sections: TimelineSection, title: str = "Alpen") -> TimelineSnapshot:
    entries = tuple(TimelineEntry(started_at=section.started_at, section=section) for section in sections)
    return TimelineSnapshot(
        trip_id=1,
        title=title,
        origin="manual",
        countries=("IT",),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 10),
        sections=sections,
        entries=entries,
    )


def _jpeg(path: Path, color: tuple[int, int, int] = (180, 20, 20)) -> Path:
    Image.new("RGB", (80, 60), color).save(path, format="JPEG", quality=95)
    return path


def test_padded_content_count_is_26_or_4k_plus_2() -> None:
    assert padded_content_count(5) == 26
    assert padded_content_count(26) == 26
    assert padded_content_count(27) == 30
    assert padded_content_count(28) == 30


def test_content_pages_drop_cover_blank_and_pad(tmp_path: Path) -> None:
    photo = _photo(1, _jpeg(tmp_path / "a.jpg"))
    snapshot = _snapshot(_section(7, (photo,)))
    pages = book_pages(sync_document(TravelbookDocument(), snapshot), snapshot)
    cover, interiors = content_pages(pages)
    assert cover.kind == "cover"
    assert len(interiors) == MIN_CONTENT_PAGES
    assert interiors[0].kind == "title"


def test_mcf_writes_fotobook_and_image_folder(tmp_path: Path) -> None:
    red = _jpeg(tmp_path / "keep.jpg")
    before = red.read_bytes()
    mtime = red.stat().st_mtime_ns
    snapshot = _snapshot(_section(4, (_photo(9, red),)))
    document = sync_document(TravelbookDocument(page_size="a4-portrait"), snapshot)
    destination = tmp_path / "exports" / "reise.mcf"
    seen: list[tuple[int, int]] = []
    result = export_travelbook_mcf(
        document,
        snapshot,
        destination,
        sources={9: red},
        progress=lambda current, total: seen.append((current, total)),
    )
    assert result.output_path == destination
    raw = destination.read_text(encoding="utf-8")
    assert raw.startswith("<?xml")
    assert "</fotobook>" in raw
    root = ET.fromstring(raw)
    assert root.tag == "fotobook"
    assert root.get("productname") == PRODUCT_NAME
    config = root.find("articleConfig")
    assert config is not None
    assert config.get("normalpages") == str(MIN_CONTENT_PAGES)
    assert any(area.get("areatype") == "imagearea" for area in root.iter("area"))
    assert any(area.get("areatype") == "textarea" for area in root.iter("area"))
    assert "Alpen" in raw or "ALPEN" in raw
    folder = destination.parent / mcf_folder_name(destination)
    assert folder.is_dir()
    images = list(folder.glob("*.jpg"))
    assert images
    assert any(path.name.startswith("src9_") or path.name.startswith("src9-") for path in images)
    assert any(path.name.startswith("gfx-") for path in images)
    assert red.read_bytes() == before
    assert red.stat().st_mtime_ns == mtime
    assert seen[0][0] == 1
    assert seen[-1] == (MIN_CONTENT_PAGES, MIN_CONTENT_PAGES)


def test_mcf_photo_page_keeps_native_image_and_cutout(tmp_path: Path) -> None:
    red = _jpeg(tmp_path / "red.jpg")
    snapshot = _snapshot(_section(1, (_photo(1, red),)))
    document = sync_document(TravelbookDocument(), snapshot)
    result = export_travelbook_mcf(document, snapshot, tmp_path / "book.mcf", sources={1: red})
    root = ET.fromstring(result.output_path.read_text(encoding="utf-8"))
    photos = [page for page in book_pages(document, snapshot) if page.kind == KIND_PHOTOS]
    assert photos
    images = list(root.iter("image"))
    assert images
    assert any((item.get("filename") or "").startswith("safecontainer:/") for item in images)
    assert any(item.find("cutout") is not None for item in images)


def test_mcf_rejects_yearbook_and_non_a4(tmp_path: Path) -> None:
    red = _jpeg(tmp_path / "a.jpg")
    snapshot = _snapshot(_section(1, (_photo(1, red),)))
    yearbook = TravelbookDocument(product="yearbook", page_size="a4-portrait")
    try:
        export_travelbook_mcf(yearbook, snapshot, tmp_path / "y.mcf")
    except ExportError as exc:
        assert "yearbook" in str(exc) or "nicht vorgesehen" in str(exc)
    else:
        raise AssertionError("expected ExportError")
    landscape = sync_document(TravelbookDocument(page_size="a4-landscape"), snapshot)
    try:
        export_travelbook_mcf(landscape, snapshot, tmp_path / "l.mcf", sources={1: red})
    except ExportError as exc:
        assert "Hochformat" in str(exc)
    else:
        raise AssertionError("expected ExportError")


def test_mcf_filename_helpers() -> None:
    assert export_mcf_filename("Alpen 2026") == "Alpen-2026.mcf"
    assert normalize_mcf_save_path("reise").suffix == ".mcf"
    assert mcf_folder_name(Path("Reise.mcf")) == "Reise_mcf-Dateien"
