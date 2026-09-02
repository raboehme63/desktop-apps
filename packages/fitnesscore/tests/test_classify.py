from pathlib import Path

from fitnesscore.parse.classify import classify_path


def test_classify_known_prefixes() -> None:
    assert classify_path(Path("training-session_2020.json")) == "training_session"
    assert classify_path(Path("training-target-2020.json")) == "training_target"
    assert classify_path(Path("activity-2014-04-25-abc.json")) == "activity_day"
    assert classify_path(Path("247ohr_2022_07-x.json")) == "ohr_247"
    assert classify_path(Path("planned-route-1.json")) == "planned_route"
    assert classify_path(Path("Ralf.FIT")) == "fit_activity"
    assert classify_path(Path("flug.IGC")) == "igc_flight"
    assert classify_path(Path("notes.txt")) is None
    assert classify_path(Path("misc.json")) == "unknown_json"
