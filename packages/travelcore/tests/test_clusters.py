from pathlib import Path
from shutil import copy2

from jpeg_fixtures import write_jpeg_with_exif, write_plain_jpeg
from sqlalchemy import select

from travelcore.database.models import Project, SimilarityGroup, SimilarityGroupMember, SourceFile
from travelcore.database.project_store import OpenProject
from travelcore.media.gallery import list_gallery_items
from travelcore.media.indexer import FileIndexer
from travelcore.similarity.clusters import (
    accept_exact_stacks,
    compute_media_stats,
    create_manual_group,
    dissolve_group,
    load_cluster,
    load_cluster_overlay,
    propose_scene_groups,
    set_group_keys,
    set_stack_key,
)
from travelcore.similarity.types import ClusterStatus, ClusterType
from travelcore.timeline.build import set_photo_sort_status


def _index(open_project: OpenProject, source: Path) -> None:
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source)
        session.commit()


def test_exact_stacks_keep_one_key_visible(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    original = write_plain_jpeg(source / "original.jpg")
    copy2(original, source / "copy.jpg")
    _index(open_project, source)

    with open_project.session_factory() as session:
        created = accept_exact_stacks(session, open_project.project_id)
        session.commit()
    assert created == 1

    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        visible = list_gallery_items(session, open_project.project_id, thumbs)
        hidden = list_gallery_items(
            session, open_project.project_id, thumbs, hide_cluster_hidden=False
        )
        overlay = load_cluster_overlay(session, open_project.project_id)
    assert len(visible) == 1
    assert visible[0].stack_size == 2
    assert visible[0].is_stack_key is True
    assert len(hidden) == 2
    assert len(overlay.hidden) == 1

    other = next(item.source_file_id for item in hidden if item.source_file_id != visible[0].source_file_id)
    with open_project.session_factory() as session:
        set_stack_key(session, visible[0].stack_id or 0, other)
        session.commit()
    with open_project.session_factory() as session:
        visible = list_gallery_items(session, open_project.project_id, thumbs)
    assert [item.source_file_id for item in visible] == [other]


def test_scene_group_keys_hide_other_members(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "one.jpg", datetime_original="2026:08:30 12:00:00", offset_original="+02:00"
    )
    write_jpeg_with_exif(
        source / "two.jpg", datetime_original="2026:08:30 12:00:10", offset_original="+02:00"
    )
    write_jpeg_with_exif(
        source / "later.jpg", datetime_original="2026:08:30 15:00:00", offset_original="+02:00"
    )
    _index(open_project, source)

    with open_project.session_factory() as session:
        created = propose_scene_groups(session, open_project.project_id)
        session.commit()
    assert created == 1

    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        items = list_gallery_items(session, open_project.project_id, thumbs)
        group = session.scalar(
            select(SimilarityGroup).where(SimilarityGroup.cluster_type == ClusterType.GROUP.value)
        )
    assert group is not None
    assert group.status == ClusterStatus.SUGGESTED.value
    suggested = [item for item in items if item.group_id == group.id]
    assert len(suggested) == 2
    with open_project.session_factory() as session:
        stats = compute_media_stats(session, open_project.project_id)
    assert stats.imported == 3
    assert stats.gallery == 3
    assert stats.groups == 1

    key = suggested[0].source_file_id
    with open_project.session_factory() as session:
        set_group_keys(session, group.id, [key])
        session.commit()
    with open_project.session_factory() as session:
        visible = list_gallery_items(session, open_project.project_id, thumbs)
    group_visible = [item for item in visible if item.group_id == group.id]
    assert [item.source_file_id for item in group_visible] == [key]
    assert group_visible[0].is_group_key is True
    assert group_visible[0].group_status == ClusterStatus.ACCEPTED.value

    with open_project.session_factory() as session:
        set_group_keys(session, group.id, [])
        session.commit()
    with open_project.session_factory() as session:
        visible = list_gallery_items(session, open_project.project_id, thumbs)
    suggested = [item for item in visible if item.group_id == group.id]
    assert len(suggested) == 2
    assert all(item.group_status == ClusterStatus.SUGGESTED.value for item in suggested)
    assert all(item.is_group_key is False for item in suggested)


def test_suggested_group_ignores_stale_keys(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "one.jpg", datetime_original="2026:08:30 12:00:00", offset_original="+02:00"
    )
    write_jpeg_with_exif(
        source / "two.jpg", datetime_original="2026:08:30 12:00:10", offset_original="+02:00"
    )
    _index(open_project, source)
    with open_project.session_factory() as session:
        propose_scene_groups(session, open_project.project_id)
        member = session.scalar(select(SimilarityGroupMember))
        assert member is not None
        member.is_key = True
        session.commit()
    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        items = list_gallery_items(session, open_project.project_id, thumbs)
        record = load_cluster(session, items[0].group_id or 0)
    assert all(item.group_status == ClusterStatus.SUGGESTED.value for item in items)
    assert all(item.is_group_key is False for item in items)
    assert record.key_ids == ()


def test_manual_group_has_no_keys(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_plain_jpeg(source / "a.jpg")
    write_plain_jpeg(source / "b.jpg")
    write_plain_jpeg(source / "c.jpg")
    _index(open_project, source)

    with open_project.session_factory() as session:
        rows = list(session.scalars(select(SourceFile).order_by(SourceFile.filename.asc())))
        ids = [row.id for row in rows if row.filename in {"a.jpg", "c.jpg"}]
        cluster_id = create_manual_group(session, open_project.project_id, ids)
        session.commit()
    record = None
    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        record = load_cluster(session, cluster_id)
        visible = list_gallery_items(session, open_project.project_id, thumbs)
    assert record.origin == "manual"
    assert record.status == ClusterStatus.SUGGESTED.value
    assert set(record.member_ids) == set(ids)
    assert record.key_ids == ()
    grouped = [item for item in visible if item.group_id == cluster_id]
    assert {item.filename for item in grouped} == {"a.jpg", "c.jpg"}
    assert all(item.is_group_key is False for item in grouped)
    assert all(item.group_status == ClusterStatus.SUGGESTED.value for item in grouped)

    with open_project.session_factory() as session:
        dissolve_group(session, cluster_id)
        session.commit()
    with open_project.session_factory() as session:
        visible = list_gallery_items(session, open_project.project_id, thumbs)
        leftover = session.scalar(
            select(SimilarityGroup).where(SimilarityGroup.id == cluster_id)
        )
    assert leftover is None
    assert all(item.group_id is None for item in visible)


def test_manual_group_moves_photos_out_of_previous_group(
    open_project: OpenProject, tmp_path: Path
) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "one.jpg", datetime_original="2026:08:30 12:00:00", offset_original="+02:00"
    )
    write_jpeg_with_exif(
        source / "two.jpg", datetime_original="2026:08:30 12:00:10", offset_original="+02:00"
    )
    write_plain_jpeg(source / "extra.jpg")
    _index(open_project, source)

    with open_project.session_factory() as session:
        created = propose_scene_groups(session, open_project.project_id)
        extra = session.scalar(select(SourceFile).where(SourceFile.filename == "extra.jpg"))
        one = session.scalar(select(SourceFile).where(SourceFile.filename == "one.jpg"))
        assert extra is not None and one is not None
        new_id = create_manual_group(session, open_project.project_id, [one.id, extra.id])
        session.commit()
    assert created == 1
    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        items = list_gallery_items(session, open_project.project_id, thumbs)
        leftover = session.scalar(
            select(SimilarityGroup).where(
                SimilarityGroup.cluster_type == ClusterType.GROUP.value,
                SimilarityGroup.id != new_id,
            )
        )
    grouped = [item for item in items if item.group_id == new_id]
    assert {item.filename for item in grouped} == {"one.jpg", "extra.jpg"}
    assert leftover is None
    two = next(item for item in items if item.filename == "two.jpg")
    assert two.group_id is None


def test_stack_key_prefers_richer_original(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "IMG-20260830-WA0001.jpg",
        datetime_original="2026:08:30 12:00:00",
        offset_original="+02:00",
        make=None,
        model=None,
        size=(16, 12),
    )
    write_jpeg_with_exif(
        source / "IMG_1001.jpg",
        datetime_original="2026:08:30 12:00:00",
        offset_original="+02:00",
        size=(64, 48),
    )
    _index(open_project, source)
    with open_project.session_factory() as session:
        rows = list(session.scalars(select(SourceFile)))
        digest = next(row.sha256 for row in rows if row.sha256)
        for row in rows:
            row.sha256 = digest
        accept_exact_stacks(session, open_project.project_id)
        session.commit()
    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        visible = list_gallery_items(session, open_project.project_id, thumbs)
    assert len(visible) == 1
    assert visible[0].filename == "IMG_1001.jpg"


def test_media_stats_counts_stacks_rejected_and_pool(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    original = write_plain_jpeg(source / "original.jpg", size=(16, 12))
    copy2(original, source / "copy.jpg")
    write_plain_jpeg(source / "keep.jpg", size=(20, 14))
    write_plain_jpeg(source / "weg.jpg", size=(24, 16))
    write_plain_jpeg(source / "pool.jpg", size=(28, 18))
    _index(open_project, source)

    with open_project.session_factory() as session:
        accept_exact_stacks(session, open_project.project_id)
        weg = session.scalar(select(SourceFile).where(SourceFile.filename == "weg.jpg"))
        parked = session.scalar(select(SourceFile).where(SourceFile.filename == "pool.jpg"))
        assert weg is not None and parked is not None
        set_photo_sort_status(session, weg.id, "rejected")
        parked.parked = True
        session.commit()
        stats = compute_media_stats(session, open_project.project_id)
    assert stats.imported == 5
    assert stats.gallery == 2
    assert stats.rejected == 1
    assert stats.pool == 1
    assert stats.stacks == 1
    assert stats.stack_hidden == 1
    assert stats.groups == 0
    assert stats.hidden == 1
    assert "Importiert 5" in stats.format_line()
    assert "Dubletten 1 / 1" in stats.format_line()
