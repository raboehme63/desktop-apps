from pathlib import Path

from travelcore.geo.catalog import (
    country_label,
    get_country,
    list_countries,
    resolve_token,
    search_countries,
)
from travelcore.timeline.countries import country_labels, parse_countries, serialize_countries


def test_catalog_includes_core_travel_countries() -> None:
    countries = list_countries()
    by_iso = {item.iso2: item for item in countries}
    assert len(countries) >= 200
    for iso, name_de in (
        ("DE", "Deutschland"),
        ("IT", "Italien"),
        ("FR", "Frankreich"),
        ("NO", "Norwegen"),
        ("TW", "Taiwan"),
        ("ZA", "Südafrika"),
    ):
        item = by_iso[iso]
        assert item.name_de == name_de
        assert item.flag_svg.is_file()
        assert item.shape_svg.is_file()
        assert item.flag_svg.read_text(encoding="utf-8").lstrip().startswith("<svg")
        assert 'fill="#000000"' in item.shape_svg.read_text(encoding="utf-8")


def test_resolve_token_accepts_code_german_english_and_alias() -> None:
    assert resolve_token("it") == "IT"
    assert resolve_token("Italien") == "IT"
    assert resolve_token("Italy") == "IT"
    assert resolve_token("USA") == "US"
    assert get_country("de") is not None
    assert country_label("AT") == "Österreich"
    assert search_countries("slowen")[0].iso2 == "SI"
    assert search_countries("südafrika")[0].iso2 == "ZA"


def test_country_at_uses_silhouette_outline() -> None:
    from travelcore.geo.catalog import country_at, get_country, shape_lonlat_box

    germany = get_country("DE")
    austria = get_country("AT")
    assert germany is not None and austria is not None
    box = shape_lonlat_box(germany)
    assert box is not None
    min_lon, min_lat, max_lon, max_lat = box
    assert min_lon < 10 < max_lon
    assert min_lat < 51 < max_lat
    at_box = shape_lonlat_box(austria)
    assert at_box is not None
    hochries = (47.767, 12.167)
    assert at_box[1] < hochries[0] < at_box[3]
    assert at_box[0] < hochries[1] < at_box[2]
    assert country_at(*hochries, preferred=("ZA", "DE")).iso2 == "DE"
    assert country_at(*hochries, preferred=("AT", "DE")).iso2 == "DE"
    assert country_at(*hochries, preferred=("AT",)).iso2 == "DE"
    munich = country_at(48.137, 11.576, preferred=("AT",))
    assert munich is not None and munich.iso2 == "DE"
    vienna = country_at(48.208, 16.373, preferred=("DE", "AT"))
    assert vienna is not None and vienna.iso2 == "AT"
    vaduz = country_at(47.141, 9.521, preferred=("CH", "AT"))
    assert vaduz is not None and vaduz.iso2 == "LI"
    cape_town = country_at(-33.92, 18.42, preferred=("ZA",))
    assert cape_town is not None and cape_town.iso2 == "ZA"
    milan = country_at(45.46, 9.19)
    assert milan is not None and milan.iso2 == "IT"


def test_parse_countries_stores_iso_codes() -> None:
    assert parse_countries("Italien\nÖsterreich\nItalien") == ("IT", "AT")
    assert parse_countries("Italien, Slowenien") == ("IT", "SI")
    assert serialize_countries(["  Italien ", "", "Österreich"]) == "IT\nAT"
    assert serialize_countries(["IT", "at"]) == "IT\nAT"
    assert serialize_countries([]) is None
    assert country_labels(("IT", "AT")) == ("Italien", "Österreich")
    assert parse_countries("Nimmerland") == ("Nimmerland",)


def test_catalog_files_live_next_to_module() -> None:
    data = Path(__file__).resolve().parents[1] / "src" / "travelcore" / "geo" / "data"
    assert (data / "catalog.json").is_file()
    assert (data / "NOTICE.txt").is_file()
    assert (data / "flags" / "de.svg").is_file()
    assert (data / "shapes" / "de.svg").is_file()
