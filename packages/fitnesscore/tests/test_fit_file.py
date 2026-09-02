from pathlib import Path

import pytest

from fitnesscore.parse.fit import documents_from_fit

_FIT = Path(r"b:\x___myDownloads\Ralf\Ralf_Böhme_2026-09-01_11-03-34.FIT")


@pytest.mark.skipif(not _FIT.is_file(), reason="Lokale Polar-FIT-Datei nicht vorhanden")
def test_real_polar_fit_e_biking() -> None:
    docs = documents_from_fit(_FIT.read_bytes())
    assert len(docs) == 1
    assert docs[0].sport_slug == "e-biking"
    assert docs[0].started_at is not None
    assert docs[0].started_at.year == 2026
    assert docs[0].tracks
    assert docs[0].tracks[0].points[0].latitude > 47
    assert docs[0].tracks[0].points[0].longitude > 11
