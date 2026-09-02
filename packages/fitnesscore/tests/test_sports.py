from fitnesscore.sports import match_sport, match_sports, parse_sport_args, resolve_sport


def test_resolve_polar_id_and_fit_enum() -> None:
    polar = resolve_sport(polar_id="177", name="")
    assert polar is not None
    assert polar.slug == "e-biking"
    fit = resolve_sport(fit_sport="e_biking", fit_sub_sport="generic")
    assert fit is not None
    assert fit.slug == "e-biking"
    mtb = resolve_sport(fit_sport="cycling", fit_sub_sport="mountain")
    assert mtb is not None
    assert mtb.slug == "mountain-biking"


def test_match_sport_accepts_aliases() -> None:
    assert match_sport("e-biking", "e-biking")
    assert match_sport("e_biking", "e-biking")
    assert match_sport("E-Bike-Fahren", "e-biking")
    assert not match_sport("kitesurfing", "e-biking")


def test_parse_and_match_optional_sports() -> None:
    assert parse_sport_args(None) is None
    assert parse_sport_args([]) is None
    assert parse_sport_args(["kitesurfing,e-biking", "hiking"]) == (
        "kitesurfing",
        "e-biking",
        "hiking",
    )
    assert match_sports(None, "hiking")
    assert match_sports(("kitesurfing", "e-biking"), "e-biking")
    assert not match_sports(("kitesurfing",), "hiking")
