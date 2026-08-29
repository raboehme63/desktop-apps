from travelcore.timeline.sections import MOVEMENT_MODES
from travelcore.timeline.symbols import (
    TRANSPORT_SYMBOLS,
    stay_symbol_svg_js,
    symbol_badge_svg,
    symbol_inner_svg,
    symbol_label,
)


def test_transport_symbols_cover_movement_modes() -> None:
    keys = [item.key for item in TRANSPORT_SYMBOLS]
    assert set(keys) == set(MOVEMENT_MODES)
    assert len(keys) == len(set(keys))


def test_symbol_badge_is_white_on_black() -> None:
    svg = symbol_badge_svg("car", size=36)
    assert 'fill="#000000"' in svg
    assert 'fill="#ffffff"' in symbol_inner_svg("car", "#ffffff")
    assert svg.count("<svg") == 1
    assert "translate(" in svg and "scale(" in svg
    assert "rotate(90 128 128)" in symbol_inner_svg("plane", "#ffffff")
    assert "rotate(" not in symbol_inner_svg("car", "#ffffff")
    assert "rotate(" not in symbol_inner_svg("walk", "#ffffff")
    assert "rotate(" not in symbol_inner_svg("bus", "#ffffff")
    assert "stroke=" in symbol_inner_svg("bus", "#ffffff")
    assert "stroke=" in symbol_inner_svg("train", "#ffffff")
    assert "stroke=" in symbol_inner_svg("walk", "#ffffff")
    assert "rotate(" not in symbol_inner_svg("bike", "#ffffff")
    assert "rotate(" not in symbol_inner_svg("boat", "#ffffff")
    assert "rotate(" not in symbol_inner_svg("campervan", "#ffffff")
    assert "rotate(" not in symbol_inner_svg("camper", "#ffffff")
    assert "rotate(" not in symbol_inner_svg("climb", "#ffffff")
    assert symbol_label("plane") == "Flugzeug"
    assert symbol_label("campervan") == "Camper Van"
    assert symbol_label("climb") == "Klettern"


def test_stay_symbol_svg_js_lists_every_key() -> None:
    script = stay_symbol_svg_js()
    assert "function staySymbolSvg(symbol, color)" in script
    for item in TRANSPORT_SYMBOLS:
        assert f"symbol === '{item.key}'" in script
        assert item.summary
