from pathlib import Path

from traveljournal.services.workspace import (
    Workspace,
    normalize_timeline_media_tab,
    resolve_projects_root,
)


def test_resolve_projects_root_prefers_settings_then_stored_then_recents(tmp_path: Path) -> None:
    settings_dir = tmp_path / "from-env"
    stored_dir = tmp_path / "from-config"
    recent_parent = tmp_path / "from-recent"
    settings_dir.mkdir()
    stored_dir.mkdir()
    recent_parent.mkdir()
    recent = recent_parent / "Italien 2025"
    recent.mkdir()

    assert (
        resolve_projects_root(
            settings_root=str(settings_dir),
            stored_root=str(stored_dir),
            recents=[recent],
        )
        == settings_dir.resolve()
    )
    assert (
        resolve_projects_root(
            settings_root=None,
            stored_root=str(stored_dir),
            recents=[recent],
        )
        == stored_dir.resolve()
    )
    assert (
        resolve_projects_root(
            settings_root="",
            stored_root=None,
            recents=[recent],
        )
        == recent_parent.resolve()
    )
    assert resolve_projects_root(settings_root=None, stored_root=None, recents=[]) is None
    missing = tmp_path / "missing"
    assert (
        resolve_projects_root(
            settings_root=str(missing),
            stored_root=str(stored_dir),
            recents=[],
        )
        == stored_dir.resolve()
    )


def test_normalize_timeline_media_tab() -> None:
    assert normalize_timeline_media_tab("favorite") == "favorite"
    assert normalize_timeline_media_tab("reserve") == "reserve"
    assert normalize_timeline_media_tab("rejected") == "rejected"
    assert normalize_timeline_media_tab("parked") == "all"
    assert normalize_timeline_media_tab("unknown") == "all"
    assert normalize_timeline_media_tab(None) == "all"


def test_timeline_media_tab_persists(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from traveljournal.services import workspace as workspace_mod

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    workspace = Workspace()
    assert workspace.timeline_media_tab() == "all"
    workspace.set_timeline_media_tab("favorite")
    assert workspace.timeline_media_tab() == "favorite"
    workspace.set_timeline_media_tab("nope")
    assert workspace.timeline_media_tab() == "all"


def test_map_display_flags_persist_in_project(tmp_path: Path) -> None:
    from travelcore.database.project_store import ProjectStore
    from travelcore.project_settings import load_project_settings

    opened = ProjectStore().create(tmp_path / "karte_flags", "Flags")
    workspace = Workspace()
    workspace.current = opened
    assert workspace.map_show_photo_cones() is False
    assert workspace.map_show_reserve() is False
    assert workspace.map_show_sat_labels() is False
    assert workspace.map_show_sat_streets() is False
    workspace.set_map_display_flags(
        photo_cones=True, show_reserve=True, sat_labels=True, sat_streets=True
    )
    assert workspace.map_show_photo_cones() is True
    assert workspace.map_show_reserve() is True
    assert workspace.map_show_sat_labels() is True
    assert workspace.map_show_sat_streets() is True
    loaded = load_project_settings(opened.directory)
    assert loaded.placeholders.map_show_photo_cones is True
    assert loaded.placeholders.map_show_reserve is True
    assert loaded.placeholders.map_show_sat_labels is True
    assert loaded.placeholders.map_show_sat_streets is True


def test_sidebar_collapsed_persists(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from traveljournal.services import workspace as workspace_mod

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    workspace = Workspace()
    assert workspace.sidebar_collapsed() is False
    workspace.set_sidebar_collapsed(True)
    assert workspace.sidebar_collapsed() is True
    workspace.set_sidebar_collapsed(False)
    assert workspace.sidebar_collapsed() is False


def test_timeline_pool_visible_persists(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from traveljournal.services import workspace as workspace_mod

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    workspace = Workspace()
    assert workspace.timeline_pool_visible() is False
    workspace.set_timeline_pool_visible(True)
    assert workspace.timeline_pool_visible() is True
    workspace.set_timeline_pool_visible(False)
    assert workspace.timeline_pool_visible() is False


def test_pool_width_persists(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from traveljournal.services import workspace as workspace_mod

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    workspace = Workspace()
    assert workspace.pool_width() == 280
    workspace.set_pool_width(360)
    assert workspace.pool_width() == 360
    workspace.set_pool_width(80)
    assert workspace.pool_width() == 220


def test_inspector_geometry_persists(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.widgets.media_inspector import INSPECTOR_DEFAULT_SIZE, clamp_inspector_size

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    workspace = Workspace()
    assert workspace.inspector_size() == INSPECTOR_DEFAULT_SIZE
    assert workspace.inspector_maximized() is False
    workspace.set_inspector_geometry(1100, 640)
    assert workspace.inspector_size() == (1100, 640)
    workspace.set_inspector_geometry(80, 20, maximized=True)
    assert workspace.inspector_size() == clamp_inspector_size(80, 20)
    assert workspace.inspector_maximized() is True
    assert clamp_inspector_size("nope", None) == INSPECTOR_DEFAULT_SIZE


def test_pool_media_tab_persists(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from traveljournal.services import workspace as workspace_mod

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    workspace = Workspace()
    assert workspace.pool_media_tab() == "all"
    workspace.set_pool_media_tab("favorite")
    assert workspace.pool_media_tab() == "favorite"
    workspace.set_pool_media_tab("parked")
    assert workspace.pool_media_tab() == "all"


def test_thumb_zoom_persists(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.widgets.thumb_zoom import DEFAULT_THUMB_ZOOM, clamp_thumb_zoom

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    workspace = Workspace()
    assert workspace.timeline_thumb_zoom() == DEFAULT_THUMB_ZOOM
    assert workspace.map_thumb_zoom() == DEFAULT_THUMB_ZOOM
    workspace.set_timeline_thumb_zoom(150)
    workspace.set_map_thumb_zoom(75)
    assert workspace.timeline_thumb_zoom() == 150
    assert workspace.map_thumb_zoom() == 75
    workspace.set_timeline_thumb_zoom(12)
    assert workspace.timeline_thumb_zoom() == clamp_thumb_zoom(12)
    workspace.set_map_thumb_zoom("nope")
    assert workspace.map_thumb_zoom() == DEFAULT_THUMB_ZOOM


def test_show_rejected_in_all_persists(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from traveljournal.services import workspace as workspace_mod

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    workspace = Workspace()
    assert workspace.show_rejected_in_all() is False
    workspace.set_show_rejected_in_all(True)
    assert workspace.show_rejected_in_all() is True
    workspace.set_show_rejected_in_all(False)
    assert workspace.show_rejected_in_all() is False
