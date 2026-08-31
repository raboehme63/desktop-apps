from travelcore.exceptions import ExportError
from travelcore.export.catalog import list_photo_layouts, load_page_layout
from travelcore.export.geometry import Frame
from travelcore.export.photo_layouts import (
    delete_user_layout,
    layout_from_frames,
    list_user_layouts,
    load_user_layout,
    rename_user_layout,
    save_user_layout,
    set_user_layouts_dir,
)


def test_user_layout_is_scoped_to_page_size(tmp_path) -> None:  # noqa: ANN001
    set_user_layouts_dir(tmp_path)
    try:
        layout = layout_from_frames(
            (Frame(2, 2, 46, 96), Frame(52, 2, 46, 96)),
            name="Randspalten",
            page_size="a4-landscape",
        )
        saved = save_user_layout(layout)
        assert saved["id"].startswith("user_")
        assert saved["photo_count"] == 2
        assert load_page_layout(saved["id"])["page_size"] == "a4-landscape"
        portrait = list_photo_layouts("a4-portrait")
        landscape = list_photo_layouts("a4-landscape")
        assert saved["id"] not in [item["id"] for item in portrait]
        assert saved["id"] in [item["id"] for item in landscape]
        assert [item["id"] for item in portrait[:8]] == [f"photos_{index}" for index in range(1, 9)]
        assert list_user_layouts("a4-portrait") == ()
    finally:
        set_user_layouts_dir(None)


def test_rename_and_delete_user_layout(tmp_path) -> None:  # noqa: ANN001
    set_user_layouts_dir(tmp_path)
    try:
        saved = save_user_layout(
            layout_from_frames((Frame(0, 0, 100, 100),), name="Alt", page_size="square")
        )
        renamed = rename_user_layout(saved["id"], "Neu")
        assert renamed["label"]["de"] == "Neu"
        assert load_user_layout(saved["id"])["label"]["de"] == "Neu"
        delete_user_layout(saved["id"])
        assert load_user_layout(saved["id"]) is None
        try:
            delete_user_layout("photos_1")
        except ExportError as exc:
            assert "Standard" in str(exc)
        else:
            raise AssertionError("expected ExportError")
    finally:
        set_user_layouts_dir(None)


def test_layout_from_frames_rejects_empty() -> None:
    try:
        layout_from_frames((), name="Leer", page_size="a4-portrait")
    except ExportError as exc:
        assert "Rahmen" in str(exc)
    else:
        raise AssertionError("expected ExportError")
