"""Standard-tier options fee math."""

from __future__ import annotations

from cryobookq.fees import STANDARD_TIER, taker_fee_usd


def test_deribit_uncapped_on_rich_premium() -> None:
    # 3 bps of 100k = $30; 12.5% of $2,000 = $250 → uncapped wins.
    fee = taker_fee_usd("deribit", index_usd=100_000.0, premium_usd=2_000.0)
    assert fee is not None
    assert abs(fee - 30.0) < 1e-9


def test_deribit_cap_on_cheap_premium() -> None:
    # 3 bps of 100k = $30; 12.5% of $80 = $10 → cap wins.
    fee = taker_fee_usd("deribit", index_usd=100_000.0, premium_usd=80.0)
    assert fee == 10.0


def test_bybit_help_center_taker_example_shape() -> None:
    """Bybit: min(taker_rate × index, 7% × premium) × size.

    Help-center maker example used 0.02%; here we check the same shape at 0.03% taker.
    index 42_000, premium 3_000, size 0.3 → min(12.6, 210) × 0.3 = 3.78
    """
    fee = taker_fee_usd("bybit", index_usd=42_000.0, premium_usd=3_000.0, size_btc=0.3)
    assert abs(fee - 3.78) < 1e-9


def test_bybit_cap_on_cheap_option() -> None:
    # min(0.03% × 42_000, 7% × 30) × 0.3 = min(12.6, 2.1) × 0.3 = 0.63
    fee = taker_fee_usd("bybit", index_usd=42_000.0, premium_usd=30.0, size_btc=0.3)
    assert abs(fee - 0.63) < 1e-9


def test_unknown_venue_is_none() -> None:
    assert taker_fee_usd("not-an-exchange", index_usd=100_000.0, premium_usd=100.0) is None


def test_all_preferred_venues_have_a_schedule() -> None:
    for v in ("deribit", "coincall", "bybit", "okx", "binance"):
        assert v in STANDARD_TIER
        assert STANDARD_TIER[v].taker_rate > 0
        assert 0 < STANDARD_TIER[v].premium_cap <= 1
