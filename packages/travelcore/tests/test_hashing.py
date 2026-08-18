from pathlib import Path

from travelcore.media.hashing import sha256_file

HELLO_HASH = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_sha256_of_known_content(tmp_path: Path) -> None:
    path = tmp_path / "hello.txt"
    path.write_bytes(b"hello")
    assert sha256_file(path) == HELLO_HASH


def test_identical_files_share_hash(tmp_path: Path) -> None:
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    payload = b"\xff\xd8" + b"same-bytes" * 50 + b"\xff\xd9"
    a.write_bytes(payload)
    b.write_bytes(payload)
    assert sha256_file(a) == sha256_file(b)


def test_different_files_differ(tmp_path: Path) -> None:
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"one")
    b.write_bytes(b"two")
    assert sha256_file(a) != sha256_file(b)
