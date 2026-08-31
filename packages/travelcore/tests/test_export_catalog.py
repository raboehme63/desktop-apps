from travelcore.exceptions import ExportError
from travelcore.export.catalog import (
    chronicle_page_layouts,
    default_page_size_id,
    first_path,
    list_page_sizes,
    list_photo_layouts,
    list_product_ids,
    load_catalog,
    load_page_layout,
    load_product,
    page_size,
    product_formats,
    supports,
)


def test_catalog_lists_three_products() -> None:
    ids = list_product_ids()
    assert ids == ("travelbook", "yearbook", "travelbook-interactive")
    catalog = load_catalog()
    format_ids = [item["id"] for item in catalog["formats"]]
    assert format_ids == ["html", "pdf", "epub", "latex", "cewe", "video"]


def test_first_path_is_travelbook_html() -> None:
    assert first_path() == ("travelbook", "html")
    assert supports("travelbook", "html")


def test_page_sizes_default_to_a4_portrait() -> None:
    assert default_page_size_id() == "a4-portrait"
    ids = [item["id"] for item in list_page_sizes()]
    assert ids == ["a4-portrait", "a4-landscape", "square"]
    a4 = page_size("a4-portrait")
    assert a4["width_mm"] == 210
    assert a4["height_mm"] == 297
    landscape = page_size("a4-landscape")
    assert landscape["width_mm"] == 297
    assert landscape["height_mm"] == 210


def test_travelbook_is_static_book_with_page_turn() -> None:
    formats = product_formats("travelbook")
    assert "html" in formats
    assert "pdf" in formats
    assert "video" not in formats
    product = load_product("travelbook")
    assert product["formats"] == list(formats)
    assert product["layout"]["kind"] == "book"
    assert product["layout"]["page_size"] == "a4-portrait"
    assert product["viewer"]["chrome"] == "book_nav"
    assert "prev_next" in product["viewer"]["features"]
    assert "pan" not in product["viewer"]["features"]
    page_ids = [page["id"] for page in product["pages"]]
    assert page_ids[:3] == ["cover", "title_page", "trip_summary"]
    assert page_ids[3] == "chronicle"
    cover = product["pages"][0]
    assert cover["kind"] == "cover"
    assert cover["slots"]["title"]["bind"] == "trip.title"
    assert cover["numbered"] is False
    summary = product["pages"][2]
    assert summary["spread"] is True
    assert summary["verso"]["slots"]["countries"]["bind"] == "trip.countries"
    assert summary["verso"]["style"]["metrics"] == [
        "duration_days",
        "section_count",
        "photo_count",
        "youtube_count",
        "flight_count",
    ]
    assert summary["recto"]["kind"] == "trip_summary_map"
    assert summary["recto"]["style"]["mode"] == "static_image"
    chronicle = product["pages"][3]
    assert chronicle["kind"] == "chronicle"
    assert chronicle["status"] == "active"
    assert chronicle["verso"]["layout"] == "section_intro"
    assert chronicle["recto"]["layout"] == "photos_1"
    editor = product["editor"]
    assert editor["enabled"] is True
    assert editor["persist"] == "travelbook.json"
    assert editor["chronicle"]["add_spread"] is True
    assert editor["chronicle"]["initial_spread"]["verso"]["locked"] is True
    assert editor["chronicle"]["initial_spread"]["recto"]["layout"] == "photos_1"
    tray = editor["chronicle"]["media_tray"]
    assert tray["interaction"] == "drag_drop"
    assert tray["source"] == "section_members"
    assert tray["kinds"] == ["photo", "video", "track"]
    assert tray["thumbnails"] is True


def test_travelbook_page_layouts_are_one_to_eight_photos_and_journal() -> None:
    layouts = chronicle_page_layouts("travelbook")
    expected = tuple(f"photos_{index}" for index in range(1, 9)) + ("journal",)
    assert layouts == expected
    intro = load_page_layout("section_intro")
    assert intro["kind"] == "section_intro"
    slot_ids = [slot["id"] for slot in intro["slots"]]
    assert slot_ids == [
        "country_shape",
        "country_flag",
        "country_name",
        "cover",
        "title",
        "dates",
        "notes",
        "date",
    ]
    assert intro["photo_count"] == 0
    shape = next(slot for slot in intro["slots"] if slot["id"] == "country_shape")
    assert shape["pin"] == "entry.coordinates"
    cover = next(slot for slot in intro["slots"] if slot["id"] == "cover")
    assert cover["type"] == "media"
    assert cover["fit"] == "contain"
    notes = next(slot for slot in intro["slots"] if slot["id"] == "notes")
    assert notes["bind"] == "entry.notes"
    for layout_id in layouts:
        data = load_page_layout(layout_id)
        assert data["id"] == layout_id
        assert data["applies_to"] == "page"
    photo_slot = load_page_layout("photos_1")["slots"][0]
    assert photo_slot["type"] == "media"
    assert photo_slot["accept"] == ["photo", "video", "track"]
    assert load_page_layout("photos_1")["photo_count"] == 1
    assert load_page_layout("photos_8")["photo_count"] == 8
    assert load_page_layout("journal")["kind"] == "journal"
    assert load_page_layout("journal")["photo_count"] == 0


def test_list_photo_layouts_is_one_to_eight() -> None:
    layouts = list_photo_layouts("a4-portrait")
    assert [item["id"] for item in layouts] == [f"photos_{index}" for index in range(1, 9)]
    for index, item in enumerate(layouts, start=1):
        slots = [slot for slot in item["slots"] if slot.get("type") == "media"]
        assert item["photo_count"] == index
        assert len(slots) == index
        assert item["builtin"] is True


def test_interactive_is_readonly_map_website() -> None:
    product = load_product("travelbook-interactive")
    assert "extends" not in product
    assert product["id"] == "travelbook-interactive"
    assert product["layout"]["kind"] == "map_site"
    assert product_formats("travelbook-interactive") == ("html",)
    assert not supports("travelbook-interactive", "pdf")
    assert not supports("travelbook-interactive", "video")
    assert not supports("travelbook-interactive", "cewe")
    assert product["viewer"]["chrome"] == "map"
    assert product["viewer"]["read_only"] is True
    assert "pan" in product["viewer"]["features"]
    assert "zoom" in product["viewer"]["features"]
    assert "edit" in product["viewer"]["forbidden"]
    pages = product["pages"]
    assert [page["kind"] for page in pages] == ["map_site"]
    assert pages[0]["slots"]["scene"]["bind"] == "map.scene"


def test_yearbook_is_planned_and_print_capable() -> None:
    product = load_product("yearbook")
    assert product["status"] == "planned"
    assert supports("yearbook", "pdf")
    assert not supports("yearbook", "video")
    kinds = [page["kind"] for page in product["pages"]]
    assert kinds == ["cover", "title_page", "year_summary", "toc", "trip_chapter"]
    assert product["viewer"]["chrome"] == "book_nav"


def test_matrix_matches_each_product_file() -> None:
    catalog = load_catalog()
    for product_id, listed in catalog["matrix"].items():
        assert tuple(listed) == tuple(load_product(product_id)["formats"])
        assert tuple(listed) == product_formats(product_id)


def test_unknown_product_raises() -> None:
    try:
        load_product("film")
    except ExportError as exc:
        assert "film" in str(exc)
    else:
        raise AssertionError("expected ExportError")
