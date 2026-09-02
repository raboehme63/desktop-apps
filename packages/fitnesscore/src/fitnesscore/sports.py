"""Canonical sport slugs for Polar IDs, Polar names, and FIT enums."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# Polar numeric IDs observed in the Flow export, plus common FIT names.
_POLAR_ID_TO_SLUG: dict[str, str] = {
    "1": "running",
    "2": "cycling",
    "3": "walking",
    "4": "jogging",
    "5": "mountain-biking",
    "6": "indoor-cycling",
    "7": "road-cycling",
    "11": "hiking",
    "15": "strength",
    "16": "running",
    "17": "treadmill-running",
    "18": "indoor-cycling",
    "24": "xc-ski-freestyle",
    "25": "xc-ski-classic",
    "38": "other-outdoor",
    "55": "cross-trainer",
    "59": "rollerski-freestyle",
    "94": "other-indoor",
    "100": "kitesurfing",
    "113": "ski-touring",
    "117": "indoor-rowing",
    "118": "spinning",
    "163": "circuit-training",
    "177": "e-biking",
    "179": "e-mountain-biking",
    "195": "other-outdoor",
}

_NAME_TO_SLUG: dict[str, str] = {
    "mountainbiken": "mountain-biking",
    "wandern": "hiking",
    "jogging": "jogging",
    "laufen (laufb.)": "treadmill-running",
    "laufen": "running",
    "kitesurfen": "kitesurfing",
    "kitesurfing": "kitesurfing",
    "tourenskilauf": "ski-touring",
    "freest.-skilangl.": "xc-ski-freestyle",
    "freestyle-skilanglauf": "xc-ski-freestyle",
    "freistil-rollski": "rollerski-freestyle",
    "cross-trainer": "cross-trainer",
    "crosstrainer": "cross-trainer",
    "indoor-rudern": "indoor-rowing",
    "spinning": "spinning",
    "krafttraining": "strength",
    "e-bike-fahren": "e-biking",
    "e-biking": "e-biking",
    "e_biking": "e-biking",
    "cycling": "cycling",
    "mountain": "mountain-biking",
    "walking": "walking",
    "hiking": "hiking",
    "running": "running",
    "watersports_kitesurfing": "kitesurfing",
    "paragliding": "paragliding",
    "paragliden": "paragliding",
    "gleitschirm": "paragliding",
    "gleitschirmfliegen": "paragliding",
    "hang-gliding": "hang-gliding",
    "hanggliding": "hang-gliding",
    "drachenfliegen": "hang-gliding",
    "gliding": "gliding",
    "segelflug": "gliding",
    "sailplane": "gliding",
}

_FIT_SPORT_TO_SLUG: dict[tuple[str, str], str] = {
    ("e_biking", "generic"): "e-biking",
    ("cycling", "mountain"): "mountain-biking",
    ("cycling", "generic"): "cycling",
    ("cycling", "road"): "road-cycling",
    ("kitesurfing", "generic"): "kitesurfing",
    ("hiking", "generic"): "hiking",
    ("running", "generic"): "running",
    ("walking", "generic"): "walking",
    ("training", "strength"): "strength",
}


@dataclass(frozen=True, slots=True)
class SportRef:
    slug: str
    raw: str
    polar_id: str | None = None


def normalize_slug(value: str) -> str:
    text = value.strip().lower().replace("_", "-").replace(" ", "-")
    while "--" in text:
        text = text.replace("--", "-")
    return text


def resolve_sport(
    *,
    polar_id: str | None = None,
    name: str | None = None,
    fit_sport: str | None = None,
    fit_sub_sport: str | None = None,
) -> SportRef | None:
    raw_parts = [part for part in (name, fit_sport, fit_sub_sport, polar_id) if part]
    raw = " / ".join(raw_parts) if raw_parts else ""
    if fit_sport:
        key = (fit_sport.lower(), (fit_sub_sport or "generic").lower())
        slug = _FIT_SPORT_TO_SLUG.get(key)
        if slug is None:
            slug = _FIT_SPORT_TO_SLUG.get((fit_sport.lower(), "generic"))
        if slug is None:
            slug = normalize_slug(fit_sport)
        return SportRef(slug=slug, raw=raw or slug, polar_id=polar_id)
    if polar_id:
        mapped = _POLAR_ID_TO_SLUG.get(str(polar_id))
        if mapped:
            return SportRef(slug=mapped, raw=raw or mapped, polar_id=str(polar_id))
        fallback = f"polar-{polar_id}"
        return SportRef(slug=fallback, raw=raw or fallback, polar_id=str(polar_id))
    if name:
        mapped = _NAME_TO_SLUG.get(name.strip().lower())
        if mapped:
            return SportRef(slug=mapped, raw=name, polar_id=polar_id)
        return SportRef(slug=normalize_slug(name), raw=name, polar_id=polar_id)
    return None


def resolve_igc_sport(glider: str | None) -> SportRef:
    """Map IGC glider-type text to a flight sport; default is paragliding."""

    text = (glider or "").strip()
    lowered = text.lower()
    if any(token in lowered for token in ("hang", "drachen")):
        return SportRef(slug="hang-gliding", raw=text or "hang-gliding")
    if any(token in lowered for token in ("segel", "sail", "glider")) and "para" not in lowered:
        return SportRef(slug="gliding", raw=text or "gliding")
    if any(token in lowered for token in ("para", "gleit")):
        slug = "paragliding"
        if "hang" in lowered:
            slug = "hang-gliding"
        return SportRef(slug=slug, raw=text or slug)
    return SportRef(slug="paragliding", raw=text or "paragliding")


def parse_sport_args(values: Sequence[str] | None) -> tuple[str, ...] | None:
    """Split CLI tokens and commas. None or empty means no sport filter."""

    if not values:
        return None
    parts: list[str] = []
    for value in values:
        for piece in value.split(","):
            text = piece.strip()
            if text:
                parts.append(text)
    return tuple(parts) or None


def match_sports(queries: Sequence[str] | None, slug: str | None) -> bool:
    if not queries:
        return True
    return any(match_sport(query, slug) for query in queries)


def match_sport(query: str, slug: str | None) -> bool:
    if not slug:
        return False
    wanted = normalize_slug(query)
    if wanted in {"*", "all", "alle"}:
        return True
    if slug == wanted:
        return True
    aliases = {normalize_slug(name) for name, mapped in _NAME_TO_SLUG.items() if mapped == slug}
    aliases.add(slug)
    return wanted in aliases
