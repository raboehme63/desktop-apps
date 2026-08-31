from travelcore.export.geometry import (
    Crop,
    Frame,
    affine_to_source,
    clamp_angle,
    clamp_frame,
    clamp_scale,
    clamp_stored_frame,
    contain_fit,
    cover_scale,
    frame_pixels,
    image_rect_in_rotated_frame,
    map_rect_to_contained,
    pan_from_delta,
    pan_from_source,
    pixels_to_frame,
    rotated_frame_size,
    source_rect,
)


def test_cover_scale_fills_the_shorter_axis() -> None:
    # 4000×3000 into a 200×200 square → scale by 200/3000 on height is too small;
    # cover uses max(200/4000, 200/3000) = 200/3000.
    assert cover_scale(4000, 3000, 200, 200) == 200 / 3000
    assert cover_scale(3000, 4000, 200, 200) == 200 / 3000


def test_source_rect_at_scale_one_is_centered_cover() -> None:
    # Landscape image in a square frame: crop left and right equally.
    x, y, width, height = source_rect(4000, 3000, 200, 200, Crop())
    assert y == 0.0
    assert height == 3000
    assert width == 3000  # 200 / (200/3000) = 3000
    assert x == 500.0


def test_source_rect_zoom_shrinks_the_window() -> None:
    full = source_rect(4000, 3000, 200, 200, Crop(scale=1.0))
    zoomed = source_rect(4000, 3000, 200, 200, Crop(scale=2.0))
    assert zoomed[2] == full[2] / 2
    assert zoomed[3] == full[3] / 2
    # pan 0 keeps the same centre
    full_cx = full[0] + full[2] / 2
    zoomed_cx = zoomed[0] + zoomed[2] / 2
    assert abs(full_cx - zoomed_cx) < 1e-6


def test_pan_left_shows_the_left_edge() -> None:
    x, _y, width, _height = source_rect(4000, 3000, 200, 200, Crop(scale=1.0, pan_x=-1.0))
    assert x == 0.0
    assert width == 3000
    x_right, *_ = source_rect(4000, 3000, 200, 200, Crop(scale=1.0, pan_x=1.0))
    assert x_right == 1000.0


def test_pan_roundtrip() -> None:
    crop = Crop(scale=1.4, pan_x=0.35, pan_y=-0.2)
    x, y, _w, _h = source_rect(6000, 4000, 300, 200, crop)
    pan_x, pan_y = pan_from_source(6000, 4000, 300, 200, crop.scale, x, y)
    assert abs(pan_x - crop.pan_x) < 1e-6
    assert abs(pan_y - crop.pan_y) < 1e-6


def test_frame_percent_roundtrip() -> None:
    frame = Frame(x=10, y=20, w=40, h=30)
    left, top, width, height = frame_pixels(210, 297, frame)
    restored = pixels_to_frame(210, 297, left, top, width, height)
    assert abs(restored.x - frame.x) < 1e-9
    assert abs(restored.y - frame.y) < 1e-9
    assert abs(restored.w - frame.w) < 1e-9
    assert abs(restored.h - frame.h) < 1e-9


def test_clamp_frame_stays_on_the_page() -> None:
    clipped = clamp_frame(Frame(x=90, y=90, w=40, h=40))
    assert clipped.x + clipped.w <= 100.0
    assert clipped.y + clipped.h <= 100.0
    assert clipped.w >= 6.0


def test_clamp_frame_verso_may_cross_gutter() -> None:
    overflow = clamp_frame(Frame(x=80, y=10, w=40, h=40), gutter_side="right")
    assert overflow.x == 80
    assert overflow.x + overflow.w == 120
    clipped = clamp_frame(Frame(x=80, y=10, w=40, h=40))
    assert clipped.x + clipped.w <= 100.0


def test_clamp_frame_recto_may_cross_gutter() -> None:
    overflow = clamp_frame(Frame(x=-20, y=10, w=40, h=40), gutter_side="left")
    assert overflow.x == -20
    assert overflow.x + overflow.w == 20
    clipped = clamp_frame(Frame(x=-20, y=10, w=40, h=40))
    assert clipped.x >= 0.0


def test_clamp_stored_frame_keeps_gutter_overflow() -> None:
    verso = clamp_stored_frame(Frame(80, 0, 40, 100))
    assert verso.x + verso.w > 100.0
    recto = clamp_stored_frame(Frame(-20, 0, 40, 100))
    assert recto.x < 0.0
    on_page = clamp_stored_frame(Frame(10, 10, 40, 40))
    assert on_page.x >= 0.0
    assert on_page.x + on_page.w <= 100.0


def test_contained_mapping_keeps_cover_window_aspect() -> None:
    # Square thumbs letterbox the photo; mapping must stay uniform or Qt stretches.
    sx, sy, sw, sh = source_rect(4000, 3000, 200, 200, Crop())
    assert abs(sw / sh - 1.0) < 1e-9
    _mx, _my, mw, mh = map_rect_to_contained(4000, 3000, 256, 256, sx, sy, sw, sh)
    assert abs(mw / mh - 1.0) < 1e-6
    ox, oy, cw, ch = contain_fit(4000, 3000, 256, 256)
    assert abs(cw - 256) < 1e-9
    assert ch < 256
    assert abs(oy * 2 + ch - 256) < 1e-6
    assert ox == 0.0


def test_clamp_scale_allows_zoom_out() -> None:
    assert clamp_scale(0.2) == 0.2
    assert clamp_scale(0.01) == 0.2
    assert clamp_scale(99) == 8.0


def test_rotated_square_frame_grows_with_angle() -> None:
    width, height = rotated_frame_size(200, 200, 45)
    assert width > 200
    assert abs(width - height) < 1e-9
    assert abs(rotated_frame_size(200, 100, 0)[0] - 200) < 1e-9


def test_image_rect_centered_at_cover() -> None:
    left, top, width, height = image_rect_in_rotated_frame(4000, 3000, 200, 200, Crop())
    assert abs(height - 200) < 1e-6
    assert width > 200
    assert abs(top + height / 2) < 1e-6
    assert abs(left + width / 2) < 1e-6


def test_affine_matches_source_rect_at_angle_zero() -> None:
    a, b, c, d, e, f = affine_to_source(4000, 3000, 200, 200, Crop())
    assert abs(b) < 1e-9
    assert abs(d) < 1e-9
    sx, sy, sw, sh = source_rect(4000, 3000, 200, 200, Crop())
    assert abs(c - sx) < 1e-4
    assert abs(f - sy) < 1e-4
    assert abs(a * 200 + c - (sx + sw)) < 1e-3
    assert abs(e * 200 + f - (sy + sh)) < 1e-3


def test_pan_delta_moves_the_image_with_the_pointer() -> None:
    start = Crop(scale=1.0, pan_x=0.0, pan_y=0.0)
    moved = pan_from_delta(4000, 3000, 200, 200, start, -40.0, 0.0)
    assert moved.pan_x > start.pan_x


def test_clamp_angle_wraps() -> None:
    assert clamp_angle(181) == -179
    assert clamp_angle(-181) == 179
    assert clamp_angle(360) == 0
