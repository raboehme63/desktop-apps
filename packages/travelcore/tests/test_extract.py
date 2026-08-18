from pathlib import Path

from jpeg_fixtures import write_jpeg_with_exif, write_plain_jpeg

from travelcore.media.extract import ExtractRequest, extract_file_facts, extract_many
from travelcore.parallel import resolve_worker_count


def test_resolve_worker_count_auto_and_bounds() -> None:
    assert resolve_worker_count(0) >= 1
    assert resolve_worker_count(None) >= 1
    assert resolve_worker_count(1) == 1
    assert resolve_worker_count(99) == 64


def test_extract_file_facts_hashes_and_reads_jpeg(tmp_path: Path) -> None:
    path = write_jpeg_with_exif(
        tmp_path / "bozen.jpg",
        datetime_original="2025:05:15 15:10:00",
        offset_original="+02:00",
        latitude=(46.0, 30.0, 0.0),
        longitude=(11.0, 21.0, 0.0),
    )
    facts = extract_file_facts(ExtractRequest(str(path), compute_hash=True, read_metadata=True))
    assert facts.io_error is None
    assert facts.metadata_error is None
    assert facts.sha256
    assert facts.metadata is not None
    assert facts.metadata.camera == "Canon EOS R6"
    assert facts.metadata.position is not None


def test_extract_many_pool_matches_sequential(tmp_path: Path) -> None:
    files = [write_plain_jpeg(tmp_path / f"foto_{index}.jpg") for index in range(4)]
    requests = [ExtractRequest(str(path), compute_hash=True, read_metadata=True) for path in files]
    sequential = extract_many(requests, max_workers=1)
    pooled = extract_many(requests, max_workers=2)
    assert sequential.keys() == pooled.keys()
    for path, facts in sequential.items():
        other = pooled[path]
        assert facts.sha256 == other.sha256
        assert facts.metadata_error == other.metadata_error
        assert (facts.metadata is None) == (other.metadata is None)
