from datetime import date

from travelcore.timeline.texts import (
    combine_imported_texts,
    date_from_text_filename,
    parse_imported_text,
    title_from_text_filename,
)


def test_parse_markdown_heading() -> None:
    title, body = parse_imported_text("# Bozen\n\nAnkunft am Abend.\n", "note.md")
    assert title == "Bozen"
    assert body == "Ankunft am Abend."


def test_parse_first_line_as_title() -> None:
    title, body = parse_imported_text("Bozen\nAnkunft am Abend.", "note.txt")
    assert title == "Bozen"
    assert body == "Ankunft am Abend."


def test_parse_falls_back_to_filename_when_first_line_is_long() -> None:
    long_line = "A" * 200
    title, body = parse_imported_text(long_line, "2025-05-15 Notiz.txt")
    assert title == "Notiz"
    assert body == long_line


def test_date_and_title_from_filename() -> None:
    assert date_from_text_filename("2025-05-15.md") == date(2025, 5, 15)
    assert date_from_text_filename("2025-05-15 Bozen.txt") == date(2025, 5, 15)
    assert title_from_text_filename("2025-05-15.md") is None
    assert title_from_text_filename("2025-05-15 Bozen.txt") == "Bozen"


def test_combine_imported_texts_uses_first_title() -> None:
    title, notes = combine_imported_texts([("Bozen", "Ankunft"), ("Meran", "Später"), (None, "")])
    assert title == "Bozen"
    assert notes == "Ankunft\n\nSpäter"
