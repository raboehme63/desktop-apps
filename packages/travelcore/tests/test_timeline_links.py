from travelcore.exceptions import ProjectError
from travelcore.timeline.links import (
    is_igc_filename,
    normalize_leonardo_url,
    normalize_youtube_url,
    parse_leonardo_urls,
    parse_youtube_urls,
    serialize_leonardo_urls,
    serialize_youtube_urls,
    youtube_thumbnail_url,
    youtube_video_id,
)


def test_parse_and_serialize_youtube_urls() -> None:
    stored = serialize_youtube_urls(
        ["https://youtu.be/abc", "https://www.youtube.com/watch?v=xyz", "https://youtu.be/abc"]
    )
    assert stored is not None
    parsed = parse_youtube_urls(stored)
    assert parsed == ("https://youtu.be/abc", "https://www.youtube.com/watch?v=xyz")
    assert parse_youtube_urls(None) == ()
    assert serialize_youtube_urls(["", "  "]) is None


def test_normalize_youtube_url_rejects_other_hosts() -> None:
    assert normalize_youtube_url("youtu.be/abc") == "https://youtu.be/abc"
    try:
        normalize_youtube_url("https://example.com/watch")
    except ProjectError as exc:
        assert "YouTube" in str(exc)
    else:
        raise AssertionError("expected ProjectError")


def test_parse_and_serialize_leonardo_urls() -> None:
    stored = serialize_leonardo_urls(
        [
            "https://de.dhv.de/dbnx/nx.php?id=1",
            "de.dhv.de/dbnx/nx.php?id=2",
            "https://de.dhv.de/dbnx/nx.php?id=1",
        ]
    )
    assert stored is not None
    parsed = parse_leonardo_urls(stored)
    assert parsed == (
        "https://de.dhv.de/dbnx/nx.php?id=1",
        "https://de.dhv.de/dbnx/nx.php?id=2",
    )
    assert parse_leonardo_urls(None) == ()
    assert serialize_leonardo_urls(["", "  "]) is None


def test_normalize_leonardo_url_requires_http() -> None:
    assert normalize_leonardo_url("de.dhv.de/dbnx/") == "https://de.dhv.de/dbnx/"
    try:
        normalize_leonardo_url("javascript:alert(1)")
    except ProjectError as exc:
        assert "http" in str(exc)
    else:
        raise AssertionError("expected ProjectError")


def test_is_igc_filename() -> None:
    assert is_igc_filename("flug.igc")
    assert is_igc_filename("FLUG.IGC")
    assert not is_igc_filename("spur.gpx")
    assert not is_igc_filename("foto.jpg")


def test_youtube_video_id_and_thumbnail_url() -> None:
    assert youtube_video_id("https://youtu.be/abcdefghijk") == "abcdefghijk"
    assert youtube_video_id("https://www.youtube.com/watch?v=abcdefghijk&t=12") == "abcdefghijk"
    assert youtube_video_id("https://www.youtube.com/embed/abcdefghijk") == "abcdefghijk"
    assert youtube_video_id("https://www.youtube.com/shorts/abcdefghijk") == "abcdefghijk"
    assert youtube_video_id("https://www.youtube-nocookie.com/embed/abcdefghijk") == "abcdefghijk"
    assert youtube_thumbnail_url("https://youtu.be/abcdefghijk") == (
        "https://img.youtube.com/vi/abcdefghijk/hqdefault.jpg"
    )
    assert youtube_video_id("https://example.com/watch") is None
