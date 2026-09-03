from datetime import UTC, datetime
from pathlib import Path

from gpx_fixtures import write_gpx
from jpeg_fixtures import write_jpeg_with_exif

from travelcore.database.models import Project, TripSection
from travelcore.database.project_store import OpenProject
from travelcore.maps.groups import stay_links_from_entries
from travelcore.maps.links import arc_points, build_stay_segments, insert_gap_segments
from travelcore.maps.scene import STAY_LINK_ROLE_GAP, STAY_LINK_ROLE_USER, StayLinkSegment
from travelcore.media.indexer import FileIndexer
from travelcore.timeline import KIND_MOVEMENT, create_section, park_media, sync_timeline
from travelcore.timeline.transfer_links import (
    LINK_GEOMETRY_ARC,
    LINK_GEOMETRY_LINE,
    LINK_GEOMETRY_TRACK,
    TransferLinkSpec,
    links_from_modes,
    load_transfer_links,
    save_transfer_links,
)
from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelineLink, TimelinePhoto, TimelineSection


def test_links_from_modes_preserves_canonical_order() -> None:
    links = links_from_modes("train,bus")
    assert [item.symbol for item in links] == ["bus", "train"]
    assert all(item.geometry == LINK_GEOMETRY_LINE for item in links)


def test_save_and_reorder_transfer_links(open_project: OpenProject, tmp_path: Path) -> None:
    section_id = _movement_section(open_project, tmp_path)
    with open_project.session_factory() as session:
        save_transfer_links(
            session,
            section_id,
            [
                TransferLinkSpec(geometry=LINK_GEOMETRY_LINE, symbol="car"),
                TransferLinkSpec(geometry=LINK_GEOMETRY_ARC, symbol="plane"),
            ],
        )
        session.commit()
        loaded = load_transfer_links(session, section_id)
        assert [item.symbol for item in loaded] == ["car", "plane"]
        save_transfer_links(session, section_id, list(reversed(loaded)))
        session.commit()
        assert [item.symbol for item in load_transfer_links(session, section_id)] == ["plane", "car"]


def test_save_transfer_links_updates_mode_cache(open_project: OpenProject, tmp_path: Path) -> None:
    section_id = _movement_section(open_project, tmp_path)
    with open_project.session_factory() as session:
        save_transfer_links(
            session,
            section_id,
            [TransferLinkSpec(geometry=LINK_GEOMETRY_LINE, symbol="plane")],
        )
        session.commit()
        section = session.get(TripSection, section_id)
        assert section is not None
        assert section.mode == "plane"


def test_park_media_clears_track_choice(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "foto.jpg",
        datetime_original="2025:05:15 09:00:00",
        offset_original="+02:00",
    )
    write_gpx(
        source / "fahrt.gpx",
        points=[
            (46.0, 11.0, None, "2025-05-15T09:10:00Z"),
            (46.2, 11.1, None, "2025-05-15T09:40:00Z"),
        ],
    )
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = sync_timeline(session, project, thumbs_dir=thumbs)
        by_name = {item.filename: item.source_file_id for day in snapshot.days for item in day.photos}
        track_id = by_name["fahrt.gpx"]
        section = create_section(
            session,
            snapshot.trip_id,
            [by_name["foto.jpg"], track_id],
            kind=KIND_MOVEMENT,
        )
        save_transfer_links(
            session,
            section.id,
            [TransferLinkSpec(geometry=LINK_GEOMETRY_TRACK, symbol="car", track_source_file_id=track_id)],
        )
        session.commit()
        section_id = section.id
        park_media(session, [track_id])
        session.commit()
        loaded = load_transfer_links(session, section_id)
        assert loaded[0].geometry == LINK_GEOMETRY_TRACK
        assert loaded[0].track_source_file_id is None


def test_purge_deletes_transfer_track_line_without_replacement(
    open_project: OpenProject, tmp_path: Path
) -> None:
    from travelcore.database.models import SourceFile
    from travelcore.media.purge import purge_source_files

    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "foto.jpg",
        datetime_original="2025:05:15 09:00:00",
        offset_original="+02:00",
    )
    write_gpx(
        source / "fahrt.gpx",
        points=[
            (46.0, 11.0, None, "2025-05-15T09:10:00Z"),
            (46.2, 11.1, None, "2025-05-15T09:40:00Z"),
        ],
    )
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = sync_timeline(session, project, thumbs_dir=thumbs)
        by_name = {item.filename: item.source_file_id for day in snapshot.days for item in day.photos}
        track_id = by_name["fahrt.gpx"]
        section = create_section(
            session,
            snapshot.trip_id,
            [by_name["foto.jpg"], track_id],
            kind=KIND_MOVEMENT,
        )
        save_transfer_links(
            session,
            section.id,
            [
                TransferLinkSpec(geometry=LINK_GEOMETRY_LINE, symbol="bus"),
                TransferLinkSpec(geometry=LINK_GEOMETRY_TRACK, symbol="car", track_source_file_id=track_id),
            ],
        )
        session.commit()
        section_id = section.id
        row = session.get(SourceFile, track_id)
        assert row is not None
        purge_source_files(session, [row], thumbs_dir=thumbs)
        session.commit()
        loaded = load_transfer_links(session, section_id)
        assert [item.geometry for item in loaded] == [LINK_GEOMETRY_LINE]
        assert loaded[0].symbol == "bus"
        assert session.get(SourceFile, track_id) is None


def test_gap_filler_between_cover_and_track() -> None:
    users = (
        StayLinkSegment(
            role=STAY_LINK_ROLE_USER,
            style="track",
            points=((46.5, 11.4), (46.6, 11.5)),
        ),
    )
    chain = insert_gap_segments((46.0, 11.0), (47.2, 11.4), users)
    roles = [item.role for item in chain]
    assert roles[0] == STAY_LINK_ROLE_GAP
    assert roles[1] == STAY_LINK_ROLE_USER
    assert roles[-1] == STAY_LINK_ROLE_GAP
    assert chain[0].dash == "dotted"


def test_arc_points_are_not_a_straight_chord() -> None:
    points = arc_points((46.0, 11.0), (47.0, 12.0))
    assert len(points) >= 3
    mid = points[len(points) // 2]
    assert mid != (46.5, 11.5)


def test_stay_links_use_first_transfer_segments() -> None:
    transfer = _movement_with_links(
        (
            TimelineLink(id=1, sort_index=0, geometry=LINK_GEOMETRY_LINE, symbol="car"),
            TimelineLink(id=2, sort_index=1, geometry=LINK_GEOMETRY_ARC, symbol="plane"),
        )
    )
    links = stay_links_from_entries(
        [_day_entry(1, 46.0, 11.0), transfer, _day_entry(2, 47.0, 12.0)]
    )
    assert len(links) == 1
    assert links[0].via_transfer is True
    assert links[0].transfer_key == "section:9"
    assert links[0].hubs[0].key == "section:9"
    assert links[0].hubs[0].latitude == 46.5
    users = [item for item in links[0].segments if item.role == STAY_LINK_ROLE_USER]
    assert len(users) == 1
    assert users[0].symbol == "car"
    assert users[0].style == "straight"


def test_build_stay_segments_skips_second_line_without_joint() -> None:
    segments = build_stay_segments(
        (46.0, 11.0),
        (47.0, 12.0),
        [
            TimelineLink(id=1, sort_index=0, geometry=LINK_GEOMETRY_LINE, symbol="car"),
            TimelineLink(id=2, sort_index=1, geometry=LINK_GEOMETRY_ARC, symbol="plane"),
        ],
    )
    users = [item for item in segments if item.role == STAY_LINK_ROLE_USER]
    assert len(users) == 1
    assert users[0].symbol == "car"


def _movement_section(open_project: OpenProject, tmp_path: Path) -> int:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "foto.jpg",
        datetime_original="2025:05:15 09:00:00",
        offset_original="+02:00",
    )
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = sync_timeline(session, project, thumbs_dir=thumbs)
        photo_id = snapshot.days[0].photos[0].source_file_id
        section = create_section(session, snapshot.trip_id, [photo_id], kind=KIND_MOVEMENT)
        session.commit()
        return section.id


def _day_entry(day_id: int, latitude: float, longitude: float) -> TimelineEntry:
    photo = TimelinePhoto(
        source_file_id=900 + day_id,
        filename=f"day{day_id}.jpg",
        path=f"day{day_id}.jpg",
        thumbnail_path=Path("x.jpg"),
        captured_at=datetime(2025, 5, 15, tzinfo=UTC),
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=latitude,
        gps_longitude=longitude,
        display_latitude=latitude,
        display_longitude=longitude,
    )
    return TimelineEntry(
        started_at=datetime(2025, 5, 15, tzinfo=UTC),
        leftover_day=TimelineDay(
            id=day_id,
            day_index=0,
            date=datetime(2025, 5, 15, tzinfo=UTC).date(),
            title="Tag",
            notes=None,
            origin="test",
            photos=(photo,),
        ),
    )


def _movement_with_links(links: tuple[TimelineLink, ...]) -> TimelineEntry:
    photo = TimelinePhoto(
        source_file_id=9,
        filename="t.jpg",
        path="t.jpg",
        thumbnail_path=Path("t.jpg"),
        captured_at=datetime(2025, 5, 15, 12, tzinfo=UTC),
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=46.5,
        gps_longitude=11.5,
        display_latitude=46.5,
        display_longitude=11.5,
    )
    section = TimelineSection(
        id=9,
        kind=KIND_MOVEMENT,
        mode="train",
        title="Transfer",
        notes=None,
        started_at=datetime(2025, 5, 15, 12, tzinfo=UTC),
        ended_at=datetime(2025, 5, 15, 14, tzinfo=UTC),
        location_name=None,
        location_from="A",
        location_to="B",
        origin="test",
        items=(photo,),
        links=links,
    )
    return TimelineEntry(started_at=section.started_at, section=section)
