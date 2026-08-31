from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

from PIL import Image, ImageDraw

from travelcore.exceptions import ExportError
from travelcore.export.book import (
    KIND_BLANK,
    KIND_COVER,
    KIND_INTRO,
    KIND_JOURNAL,
    KIND_PHOTOS,
    KIND_SUMMARY_COUNTRIES,
    KIND_SUMMARY_MAP,
    KIND_TITLE,
    BookPage,
    book_pages,
)
from travelcore.export.document import (
    PhotoElement,
    TravelbookDocument,
    add_spread,
    replace_chapter,
    replace_spread,
    sync_document,
)
from travelcore.export.geometry import Frame
from travelcore.export.paint import (
    NAVY_BG,
    PAGE_BG,
    PAGE_FG,
    _draw_name_and_flag,
    _draw_silhouette,
    _font,
    folio_outer_x,
    render_book_page,
)
from travelcore.export.pdf import (
    PdfExporter,
    export_filename,
    export_travelbook_pdf,
    normalize_pdf_save_path,
    unique_export_path,
)
from travelcore.export.quality import DEFAULT_QUALITY_ID, pdf_quality
from travelcore.export.raster import page_pixels
from travelcore.export.svgicon import rasterize_svg
from travelcore.geo.catalog import get_country
from travelcore.timeline.types import TimelineEntry, TimelinePhoto, TimelineSection, TimelineSnapshot
from travelcore.trip.models import Trip


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


def test_book_pages_front_matter_then_intro_and_photos(tmp_path: Path) -> None:
    photo = _photo(1, _jpeg(tmp_path / "a.jpg"))
    snapshot = _snapshot(_section(7, (photo,)))
    document = sync_document(TravelbookDocument(), snapshot)
    pages = book_pages(document, snapshot)
    kinds = [page.kind for page in pages]
    assert kinds[:5] == [
        KIND_COVER,
        KIND_BLANK,
        KIND_TITLE,
        KIND_SUMMARY_COUNTRIES,
        KIND_SUMMARY_MAP,
    ]
    assert kinds[5] == KIND_INTRO
    assert kinds[6] == KIND_PHOTOS
    assert pages[0].number is None
    assert pages[2].number is None
    assert pages[3].number == 1
    assert pages[5].number == 3
    assert pages[0].title == "ALPEN"
    assert pages[5].dates == "01.08.2026"
    assert pages[3].countries == ("IT",)


def test_book_pages_merges_gutter_visitors(tmp_path: Path) -> None:
    photo = _photo(1, _jpeg(tmp_path / "a.jpg"))
    snapshot = _snapshot(_section(7, (photo,)))
    document = sync_document(TravelbookDocument(spread_overlap=True), snapshot)
    chapter = add_spread(document.chapters[0], photo_layout="photos_1")
    extra = chapter.spreads[-1]
    spanning = PhotoElement(id="span", source_file_id=1, frame=Frame(80, 0, 40, 100), z=1)
    extra = replace(extra, verso=replace(extra.verso, elements=(spanning,)))
    document = replace_chapter(document, replace_spread(chapter, extra))
    pages = book_pages(document, snapshot)
    photos = [page for page in pages if page.kind == KIND_PHOTOS]
    assert photos[1].elements[0].frame.x == 80
    visitors = [item for item in photos[2].elements if item.id == "span"]
    assert visitors[0].frame.x == -20


def test_hidden_section_is_omitted_from_pdf_pages(tmp_path: Path) -> None:
    visible = _section(1, (_photo(1, _jpeg(tmp_path / "v.jpg")),), title="Sichtbar")
    hidden = _section(2, (_photo(2, _jpeg(tmp_path / "h.jpg")),), title="Verborgen", hidden=True)
    snapshot = _snapshot(visible, hidden)
    pages = book_pages(sync_document(TravelbookDocument(), snapshot), snapshot)
    intros = [page for page in pages if page.kind == KIND_INTRO]
    assert len(intros) == 1
    assert intros[0].title == "Sichtbar"


def test_journal_spread_becomes_journal_pages(tmp_path: Path) -> None:
    snapshot = _snapshot(_section(3, (_photo(1, _jpeg(tmp_path / "a.jpg")),)))
    document = sync_document(TravelbookDocument(), snapshot)
    document = replace_chapter(
        document,
        add_spread(document.chapters[0], verso_layout="journal", recto_layout="journal"),
    )
    pages = book_pages(document, snapshot)
    assert [page.kind for page in pages[-2:]] == [KIND_JOURNAL, KIND_JOURNAL]


def test_folio_sits_on_the_outer_edge() -> None:
    assert folio_outer_x(1, 200, 12, 14) == 14
    assert folio_outer_x(3, 200, 12, 14) == 14
    assert folio_outer_x(2, 200, 12, 14) == 174
    assert folio_outer_x(4, 200, 12, 14) == 174


def test_photo_page_paints_folio_on_the_outer_edge() -> None:
    verso = render_book_page(BookPage(kind=KIND_PHOTOS, number=3), {}, 220, 300, dpi=72)
    recto = render_book_page(BookPage(kind=KIND_PHOTOS, number=4), {}, 220, 300, dpi=72)
    blank = render_book_page(BookPage(kind=KIND_PHOTOS), {}, 220, 300, dpi=72)
    assert verso.tobytes() != blank.tobytes()
    assert recto.tobytes() != blank.tobytes()
    band = slice(verso.height - 22, verso.height)
    assert _ink_weight(verso, slice(0, 70), band) > _ink_weight(verso, slice(150, 220), band)
    assert _ink_weight(recto, slice(150, 220), band) > _ink_weight(recto, slice(0, 70), band)


def _ink_weight(image: Image.Image, xs: slice, ys: slice) -> int:
    return sum(
        abs(pixel[0] - PAGE_BG[0]) + abs(pixel[1] - PAGE_BG[1]) + abs(pixel[2] - PAGE_BG[2])
        for x in range(xs.start, xs.stop)
        for y in range(ys.start, ys.stop)
        for pixel in [image.getpixel((x, y))]
    )


def test_germany_flag_svg_has_black_red_gold() -> None:
    country = get_country("DE")
    assert country is not None
    image = rasterize_svg(country.flag_svg, 48, 36)
    top = image.getpixel((24, 4))
    mid = image.getpixel((24, 18))
    bot = image.getpixel((32, 32))
    assert top[0] < 40 and top[1] < 40 and top[2] < 40 and top[3] > 200
    assert mid[0] > 180 and mid[1] < 80
    assert bot[0] > 200 and bot[1] > 150 and bot[2] < 80


def test_germany_silhouette_paints_taller_than_wide() -> None:
    canvas = Image.new("RGB", (200, 200), (255, 255, 255))
    _draw_silhouette(ImageDraw.Draw(canvas), "DE", (0, 0, 200, 200), (0, 0, 0))
    ink = [(x, y) for y in range(200) for x in range(200) if canvas.getpixel((x, y)) != (255, 255, 255)]
    xs = [point[0] for point in ink]
    ys = [point[1] for point in ink]
    assert ink
    assert max(ys) - min(ys) > max(xs) - min(xs)


def test_summary_page_paints_flag_stripes() -> None:
    page = BookPage(kind=KIND_SUMMARY_COUNTRIES, countries=("DE",), metrics=())
    image = render_book_page(page, {}, 400, 560, dpi=72)
    gold = 0
    red = 0
    for y in range(image.height):
        for x in range(int(image.width * 0.4)):
            pixel = image.getpixel((x, y))
            if pixel[0] > 200 and 150 < pixel[1] < 230 and pixel[2] < 80:
                gold += 1
            if pixel[0] > 180 and pixel[1] < 50 and pixel[2] < 50:
                red += 1
    assert gold > 8
    assert red > 8


def _is_flag_gold(pixel: tuple[int, int, int]) -> bool:
    return pixel[0] > 200 and 150 < pixel[1] < 230 and pixel[2] < 80


def _is_de_flag(pixel: tuple[int, int, int]) -> bool:
    black = pixel[0] < 40 and pixel[1] < 40 and pixel[2] < 40
    red = pixel[0] > 180 and pixel[1] < 50 and pixel[2] < 50
    return black or red or _is_flag_gold(pixel)


def _is_navy_ink(pixel: tuple[int, int, int]) -> bool:
    return (
        abs(pixel[0] - PAGE_FG[0]) < 12
        and abs(pixel[1] - PAGE_FG[1]) < 12
        and abs(pixel[2] - PAGE_FG[2]) < 12
    )


def test_intro_paints_flag_left_of_name_and_vertically_centered() -> None:
    country = get_country("DE")
    assert country is not None
    canvas = Image.new("RGB", (280, 40), PAGE_BG)
    draw = ImageDraw.Draw(canvas)
    font = _font(16, bold=True)
    _draw_name_and_flag(canvas, draw, country, (8, 8, 270), font, PAGE_FG, 72, flag_first=True)
    flag_xs: list[int] = []
    flag_ys: list[int] = []
    navy_xs: list[int] = []
    navy_ys: list[int] = []
    for y in range(canvas.height):
        for x in range(canvas.width):
            pixel = canvas.getpixel((x, y))
            if _is_de_flag(pixel):
                flag_xs.append(x)
                flag_ys.append(y)
            elif _is_navy_ink(pixel):
                navy_xs.append(x)
                navy_ys.append(y)
    assert flag_xs and navy_xs
    assert max(flag_xs) < min(navy_xs)
    flag_mid = (min(flag_ys) + max(flag_ys)) / 2
    text_mid = (min(navy_ys) + max(navy_ys)) / 2
    assert abs(flag_mid - text_mid) <= 3


def test_intro_page_paints_flag_left_of_country_name() -> None:
    page = BookPage(kind=KIND_INTRO, country="DE", title="Bozen")
    image = render_book_page(page, {}, 400, 560, dpi=72)
    margin = round(400 * 0.07)
    header_h = round(560 * 0.28)
    y0 = margin + header_h + 8
    y1 = margin + header_h + 24
    gold_x: list[int] = []
    navy_x: list[int] = []
    for y in range(y0, y1):
        for x in range(margin, round(400 * 0.42)):
            pixel = image.getpixel((x, y))
            if _is_flag_gold(pixel):
                gold_x.append(x)
            elif _is_navy_ink(pixel):
                navy_x.append(x)
    assert gold_x and navy_x
    assert max(gold_x) < min(navy_x)


def test_cover_is_navy_and_title_is_cream(tmp_path: Path) -> None:
    snapshot = _snapshot(_section(1, (_photo(1, _jpeg(tmp_path / "a.jpg")),)))
    pages = book_pages(sync_document(TravelbookDocument(), snapshot), snapshot)
    cover = render_book_page(pages[0], {}, 40, 56, dpi=36)
    title = render_book_page(pages[2], {}, 40, 56, dpi=36)
    assert cover.getpixel((2, 2)) == NAVY_BG
    assert title.getpixel((2, 2)) == PAGE_BG


def test_pdf_writes_one_image_page_per_sheet(tmp_path: Path) -> None:
    red = _jpeg(tmp_path / "red.jpg")
    snapshot = _snapshot(_section(4, (_photo(9, red),)))
    document = sync_document(TravelbookDocument(page_size="a4-portrait"), snapshot)
    destination = tmp_path / "exports" / "reise.pdf"
    seen: list[tuple[int, int]] = []
    result = export_travelbook_pdf(
        document,
        snapshot,
        destination,
        sources={9: red},
        dpi=36,
        progress=lambda current, total: seen.append((current, total)),
    )
    raw = result.output_path.read_bytes()
    assert raw.startswith(b"%PDF-1.4")
    assert raw.rstrip().endswith(b"%%EOF")
    assert b"/PageLayout /TwoPageRight" in raw
    assert result.output_path == destination
    page_count = raw.count(b"/Type /Page ")
    expected = len(book_pages(document, snapshot))
    assert page_count == expected
    assert seen[0] == (1, expected)
    assert seen[-1] == (expected, expected)
    width, height = page_pixels(210, 297, dpi=36)
    assert f"/Width {width}".encode("ascii") in raw
    assert f"/Height {height}".encode("ascii") in raw


def test_pdf_does_not_write_originals(tmp_path: Path) -> None:
    original = _jpeg(tmp_path / "keep.jpg")
    before = original.read_bytes()
    mtime = original.stat().st_mtime_ns
    snapshot = _snapshot(_section(1, (_photo(1, original),)))
    export_travelbook_pdf(
        sync_document(TravelbookDocument(), snapshot),
        snapshot,
        tmp_path / "out.pdf",
        sources={1: original},
        dpi=36,
    )
    assert original.stat().st_mtime_ns == mtime
    assert original.read_bytes() == before


def test_yearbook_pdf_is_not_implemented() -> None:
    snapshot = _snapshot()
    document = TravelbookDocument(product="yearbook")
    try:
        export_travelbook_pdf(document, snapshot, Path("x.pdf"), dpi=36)
    except ExportError as exc:
        assert "yearbook" in str(exc)
    else:
        raise AssertionError("expected ExportError")


def test_pdf_exporter_contract_requires_document() -> None:
    exporter = PdfExporter()
    try:
        exporter.export(Trip(title="X"), Path("x.pdf"))
    except ExportError as exc:
        assert "Travelbook" in str(exc)
    else:
        raise AssertionError("expected ExportError")


def test_export_filename_slug_and_unique_path(tmp_path: Path) -> None:
    assert export_filename("Alpen 2026!") == "Alpen-2026.pdf"
    first = unique_export_path(tmp_path, "reise.pdf")
    first.write_bytes(b"a")
    second = unique_export_path(tmp_path, "reise.pdf")
    assert second.name == "reise-2.pdf"
    assert normalize_pdf_save_path(tmp_path / "buch") == tmp_path / "buch.pdf"
    assert normalize_pdf_save_path(tmp_path / "buch.PDF") == tmp_path / "buch.PDF"


def test_pdf_qualities_magazine_is_300dpi_full_chroma() -> None:
    magazine = pdf_quality("magazine")
    assert magazine.dpi == 300
    assert magazine.jpeg_quality == 95
    assert magazine.jpeg_subsampling == 0
    assert pdf_quality("print").dpi == 250
    assert pdf_quality("screen").dpi == 150
    assert pdf_quality(None).id == DEFAULT_QUALITY_ID
    try:
        pdf_quality("ultra")
    except ExportError as exc:
        assert "ultra" in str(exc)
    else:
        raise AssertionError("expected ExportError")


def test_magazine_quality_writes_300dpi_pages(tmp_path: Path) -> None:
    red = _jpeg(tmp_path / "red.jpg")
    snapshot = _snapshot(_section(1, (_photo(1, red),)))
    result = export_travelbook_pdf(
        sync_document(TravelbookDocument(), snapshot),
        snapshot,
        tmp_path / "mag.pdf",
        sources={1: red},
        quality="magazine",
    )
    raw = result.output_path.read_bytes()
    width, height = page_pixels(210, 297, dpi=300)
    assert f"/Width {width}".encode("ascii") in raw
    assert f"/Height {height}".encode("ascii") in raw
    print_w, _print_h = page_pixels(210, 297, dpi=250)
    assert f"/Width {print_w}".encode("ascii") not in raw
