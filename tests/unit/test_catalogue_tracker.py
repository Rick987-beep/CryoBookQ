"""Unit: catalogue progress note parsing."""

from cryobookq.types import BookL5
from cryobookq.venues._util import CatalogueTracker, catalogue_series


def test_catalogue_series_parses_notes() -> None:
    notes = [
        "subscribed=10",
        "cat_ws_start=0/10",
        "cat_ws_10s=7/10",
        "cat_ws_done=8/10",
        "rest_ok=1",
    ]
    series = catalogue_series(notes)
    assert series == [("ws_start", 0, 10), ("ws_10s", 7, 10), ("ws_done", 8, 10)]


def test_catalogue_tracker_log_appends() -> None:
    books: dict[str, BookL5] = {}
    notes: list[str] = []
    cat = CatalogueTracker("okx", 4, books, notes, t_start=0.0)
    cat.log("ws_start")
    assert notes[-1] == "cat_ws_start=0/4"
    books["A"] = BookL5.empty("okx", "A")
    cat.log("ws_10s")
    assert notes[-1] == "cat_ws_10s=1/4"
