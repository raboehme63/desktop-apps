from pathlib import Path

from travelcore.export.document import (
    DOCUMENT_FILENAME,
    SCHEMA_VERSION,
    Chapter,
    PageInstance,
    PhotoElement,
    Spread,
    TravelbookDocument,
    add_photo_element,
    add_spread,
    book_media_items,
    document_from_dict,
    document_to_dict,
    elements_from_layout,
    load_or_create,
    photo_layout_id,
    remove_element,
    remove_spread,
    replace_source,
    save_document,
    send_to_back,
    sync_document,
)
from travelcore.export.geometry import Crop, Frame
from travelcore.timeline.types import TimelineEntry, TimelinePhoto, TimelineSection, TimelineSnapshot


def _photo(source_id: int, **kwargs: object) -> TimelinePhoto:
    values: dict[str, object] = {
        "source_file_id": source_id,
        "filename": f"{source_id}.jpg",
        "path": f"/{source_id}.jpg",
        "thumbnail_path": Path(f"{source_id}.jpg"),
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


def _section(section_id: int, items: tuple[TimelinePhoto, ...]) -> TimelineSection:
    return TimelineSection(
        id=section_id,
        kind="day",
        mode=None,
        title="Tag",
        notes="",
        started_at=None,
        ended_at=None,
        location_name=None,
        location_from=None,
        location_to=None,
        origin="manual",
        items=items,
    )


def test_elements_from_photos_4_skip_empty_slots() -> None:
    elements = elements_from_layout("photos_4", [10, None, 12, 13])
    assert [item.source_file_id for item in elements] == [10, 12, 13]
    assert elements[0].frame.x == 0
    assert elements[0].frame.w == 49
    assert elements[1].frame.x == 0
    assert elements[1].frame.y == 51
    assert elements[0].z == 1
    assert elements[2].z == 3


def test_schema_1_media_array_migrates_to_elements() -> None:
    document = document_from_dict(
        {
            "schema_version": 1,
            "product": "travelbook",
            "chapters": [
                {
                    "section_id": 4,
                    "spreads": [
                        {
                            "id": "section-4-initial",
                            "initial": True,
                            "verso": {"layout": "section_intro", "locked": True},
                            "recto": {"layout": "photos_1", "media": [102]},
                        }
                    ],
                }
            ],
        }
    )
    assert document.schema_version == SCHEMA_VERSION
    recto = document.chapters[0].spreads[0].recto
    assert len(recto.elements) == 1
    assert recto.elements[0].source_file_id == 102
    assert recto.elements[0].frame.w == 100


def test_roundtrip_preserves_crop_and_z() -> None:
    element = PhotoElement(
        id="e1",
        source_file_id=7,
        frame=Frame(10, 20, 30, 40),
        crop=Crop(scale=1.5, pan_x=-0.2, pan_y=0.4, angle=7.0),
        z=4,
    )
    page = PageInstance(layout="photos_1", elements=(element,))
    document = TravelbookDocument(
        chapters=(
            Chapter(
                section_id=1,
                spreads=(Spread(id="s", verso=PageInstance("journal"), recto=page),),
            ),
        )
    )
    restored = document_from_dict(document_to_dict(document))
    got = restored.chapters[0].spreads[0].recto.elements[0]
    assert got.source_file_id == 7
    assert got.frame.x == 10
    assert got.z == 4
    assert got.crop.scale == 1.5
    assert got.crop.angle == 7.0


def test_sync_creates_initial_spread_and_drops_hidden_sections() -> None:
    photos = (_photo(1), _photo(2), _photo(3))
    section = _section(8, photos)
    snapshot = TimelineSnapshot(
        trip_id=1,
        title="Reise",
        origin="manual",
        entries=(TimelineEntry(started_at=None, section=section),),
    )
    document = sync_document(TravelbookDocument(), snapshot)
    assert len(document.chapters) == 1
    spread = document.chapters[0].spreads[0]
    assert spread.initial
    assert spread.verso.layout == "section_intro"
    assert spread.verso.locked
    assert spread.recto.layout == "photos_3"
    assert [item.source_file_id for item in spread.recto.elements] == [1, 2, 3]

    hidden = TimelineSection(
        id=8,
        kind="day",
        mode=None,
        title="Tag",
        notes="",
        started_at=None,
        ended_at=None,
        location_name=None,
        location_from=None,
        location_to=None,
        origin="manual",
        hidden=True,
        items=photos,
    )
    empty = TimelineSnapshot(
        trip_id=1,
        title="Reise",
        origin="manual",
        entries=(TimelineEntry(started_at=None, section=hidden),),
    )
    assert sync_document(document, empty).chapters == ()


def test_sync_keeps_hand_edited_elements() -> None:
    photos = (_photo(1),)
    section = _section(2, photos)
    snapshot = TimelineSnapshot(
        trip_id=1,
        title="Reise",
        origin="manual",
        entries=(TimelineEntry(started_at=None, section=section),),
    )
    document = sync_document(TravelbookDocument(), snapshot)
    edited = PhotoElement(id="hand", source_file_id=1, frame=Frame(5, 5, 50, 50), z=9)
    spread = document.chapters[0].spreads[0]
    spread = Spread(
        id=spread.id,
        initial=True,
        verso=spread.verso,
        recto=PageInstance(layout="photos_1", elements=(edited,)),
    )
    document = TravelbookDocument(chapters=(Chapter(section_id=2, spreads=(spread,)),))
    synced = sync_document(document, snapshot)
    assert synced.chapters[0].spreads[0].recto.elements[0].id == "hand"
    assert synced.chapters[0].spreads[0].recto.elements[0].z == 9


def test_add_and_remove_spread() -> None:
    chapter = Chapter(
        section_id=1,
        spreads=(
            Spread(
                id="initial",
                initial=True,
                verso=PageInstance("section_intro", locked=True),
                recto=PageInstance("photos_1"),
            ),
        ),
    )
    with_extra = add_spread(chapter)
    assert len(with_extra.spreads) == 2
    assert not with_extra.spreads[1].initial
    assert with_extra.spreads[1].verso.layout == "photos_1"
    kept = remove_spread(with_extra, with_extra.spreads[1].id)
    assert len(kept.spreads) == 1
    still = remove_spread(kept, "initial")
    assert still.spreads[0].initial


def test_add_replace_delete_and_z_order() -> None:
    first = elements_from_layout("photos_1", [1])
    two = add_photo_element(first, 2, frame=Frame(50, 50, 20, 20))
    assert len(two) == 2
    assert two[1].z == 2
    swapped = replace_source(two, two[0].id, 9)
    assert swapped[0].source_file_id == 9
    back = send_to_back(swapped, swapped[1].id)
    assert back[1].z < back[0].z
    gone = remove_element(back, back[0].id)
    assert [item.source_file_id for item in gone] == [2]


def test_hidden_stack_members_are_not_book_media() -> None:
    key = _photo(1, is_stack_key=True, stack_id=4, stack_size=2)
    copy = _photo(2, is_stack_key=False, stack_id=4, stack_size=2)
    rejected = _photo(3, sort_status="rejected")
    section = _section(1, (key, copy, rejected))
    assert [item.source_file_id for item in book_media_items(section)] == [1]


def test_load_or_create_writes_travelbook_json(tmp_path: Path) -> None:
    section = _section(3, (_photo(11),))
    snapshot = TimelineSnapshot(
        trip_id=1,
        title="Reise",
        origin="manual",
        entries=(TimelineEntry(started_at=None, section=section),),
    )
    document = load_or_create(tmp_path, snapshot, page_size="square")
    path = tmp_path / DOCUMENT_FILENAME
    assert path.is_file()
    assert document.page_size == "square"
    element = document.chapters[0].spreads[0].recto.elements[0]
    assert element.source_file_id == 11
    save_document(path, document)
    again = load_or_create(tmp_path, snapshot)
    assert again.chapters[0].section_id == 3


def test_photo_layout_id_caps_at_eight() -> None:
    assert photo_layout_id(0) == "photos_1"
    assert photo_layout_id(1) == "photos_1"
    assert photo_layout_id(8) == "photos_8"
    assert photo_layout_id(20) == "photos_8"
