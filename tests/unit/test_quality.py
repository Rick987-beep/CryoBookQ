"""Unit: quality gate."""

from cryobookq.capture.quality import evaluate_quality


def test_both_venues_ok() -> None:
    v = evaluate_quality(
        {
            "deribit": {"coverage": 1.0, "n_with_update": 900},
            "coincall": {"coverage": 0.95, "n_with_update": 850},
        },
        requested=["deribit", "coincall"],
    )
    assert v.ok
    assert not v.incomplete
    assert v.reasons == ()


def test_low_coverage_incomplete() -> None:
    v = evaluate_quality(
        {
            "deribit": {"coverage": 0.5},
            "coincall": {"coverage": 0.95},
        },
        requested=["deribit", "coincall"],
    )
    assert not v.ok
    assert v.incomplete
    assert any("deribit:coverage" in r for r in v.reasons)


def test_venue_error_incomplete_but_peer_usable() -> None:
    v = evaluate_quality(
        {
            "deribit": {"coverage": 1.0},
            "coincall": {"coverage": 0.0, "error": "ConnectionClosed"},
        },
        requested=["deribit", "coincall"],
    )
    assert not v.ok
    assert v.incomplete
    assert "coincall" in v.venue_errors
    assert v.coverages["deribit"] == 1.0


def test_none_meet_floor() -> None:
    v = evaluate_quality(
        {
            "deribit": {"coverage": 0.1},
            "coincall": {"coverage": 0.1},
        },
        requested=["deribit", "coincall"],
    )
    assert not v.ok
    assert "no_venue_met_coverage_floor" in v.reasons
