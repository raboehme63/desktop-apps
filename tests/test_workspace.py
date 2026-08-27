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
    assert normalize_timeline_media_tab("all") == "all"
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
    workspace.set_map_display_flags(photo_cones=True, show_reserve=True)
    assert workspace.map_show_photo_cones() is True
    assert workspace.map_show_reserve() is True
    loaded = load_project_settings(opened.directory)
    assert loaded.placeholders.map_show_photo_cones is True
    assert loaded.placeholders.map_show_reserve is True


def test_sidebar_collapsed_persists(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from traveljournal.services import workspace as workspace_mod

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    workspace = Workspace()
    assert workspace.sidebar_collapsed() is False
    workspace.set_sidebar_collapsed(True)
    assert workspace.sidebar_collapsed() is True
    workspace.set_sidebar_collapsed(False)
    assert workspace.sidebar_collapsed() is False
