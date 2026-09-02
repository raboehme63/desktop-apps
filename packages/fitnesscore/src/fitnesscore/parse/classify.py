"""Classify Polar export filenames and FIT files."""

from __future__ import annotations

from pathlib import Path

KIND_TRAINING_SESSION = "training_session"
KIND_TRAINING_TARGET = "training_target"
KIND_ACTIVITY_DAY = "activity_day"
KIND_OHR = "ohr_247"
KIND_FITNESS_TEST = "fitness_test"
KIND_PLANNED_ROUTE = "planned_route"
KIND_ORTHOSTATIC = "orthostatic"
KIND_PHYSICAL = "physical_test"
KIND_JUMP = "jump"
KIND_PROGRAM = "program"
KIND_ACCOUNT = "account"
KIND_PPI = "ppi_samples"
KIND_NIGHTLY_RECOVERY = "nightly_recovery"
KIND_SLEEP = "sleep"
KIND_CALENDAR = "calendar"
KIND_SPORT_PROFILE = "sport_profile"
KIND_FAVOURITE = "favourite"
KIND_PRODUCTS = "products"
KIND_FIT_ACTIVITY = "fit_activity"
KIND_IGC_FLIGHT = "igc_flight"
KIND_UNKNOWN_JSON = "unknown_json"

_PREFIXES: tuple[tuple[str, str], ...] = (
    ("training-session", KIND_TRAINING_SESSION),
    ("training-target", KIND_TRAINING_TARGET),
    ("activity-", KIND_ACTIVITY_DAY),
    ("247ohr_", KIND_OHR),
    ("fitness-test", KIND_FITNESS_TEST),
    ("planned-route", KIND_PLANNED_ROUTE),
    ("orthostatic", KIND_ORTHOSTATIC),
    ("physical-", KIND_PHYSICAL),
    ("jump-", KIND_JUMP),
    ("programs-", KIND_PROGRAM),
    ("account-", KIND_ACCOUNT),
    ("ppi_samples", KIND_PPI),
    ("nightly_recovery", KIND_NIGHTLY_RECOVERY),
    ("sleep_", KIND_SLEEP),
    ("calendar-", KIND_CALENDAR),
    ("sport-profiles", KIND_SPORT_PROFILE),
    ("favourite-", KIND_FAVOURITE),
    ("products-", KIND_PRODUCTS),
)

IMPORT_SUFFIXES = {".json", ".fit", ".igc"}


def classify_path(path: Path) -> str | None:
    """Return a kind for an importable file, or None if the suffix is ignored."""

    suffix = path.suffix.lower()
    if suffix == ".fit":
        return KIND_FIT_ACTIVITY
    if suffix == ".igc":
        return KIND_IGC_FLIGHT
    if suffix != ".json":
        return None
    name = path.name.lower()
    for prefix, kind in _PREFIXES:
        if name.startswith(prefix):
            return kind
    return KIND_UNKNOWN_JSON


def is_importable(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMPORT_SUFFIXES
