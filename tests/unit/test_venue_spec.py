"""Unit: VenueSpec defaults and OKX contract multiplier."""

from cryobookq.types import Instrument, OptionKey
from cryobookq.venues.spec import SPECS, VenueSpec, spec_for, spec_from_instrument


def _inst(venue: str, raw: dict | None = None) -> Instrument:
    key = OptionKey("BTC", 1_800_000_000_000, 80_000.0, True)
    return Instrument(venue=venue, venue_symbol="X", key=key, raw=raw or {})


def test_default_specs() -> None:
    assert spec_for("deribit") == VenueSpec("deribit", "BTC", 1.0)
    assert spec_for("coincall").price_ccy == "USD"
    assert spec_for("bybit").size_to_btc == 1.0
    assert spec_for("binance").price_ccy == "USD"
    assert spec_for("okx") == VenueSpec("okx", "BTC", 0.01)


def test_okx_from_instrument_raw() -> None:
    spec = spec_from_instrument(_inst("okx", {"ctVal": "1", "ctMult": "0.01"}))
    assert spec.size_to_btc == 0.01
    assert spec.price_ccy == "BTC"


def test_okx_missing_raw_uses_default() -> None:
    spec = spec_from_instrument(_inst("okx", {}))
    assert spec.size_to_btc == SPECS["okx"].size_to_btc


def test_non_okx_ignores_ct_fields() -> None:
    spec = spec_from_instrument(_inst("bybit", {"ctVal": "1", "ctMult": "0.01"}))
    assert spec.size_to_btc == 1.0
    assert spec.price_ccy == "USD"
