"""Analytics query API over pair_scores Parquet."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from cryobookq.config import get_settings
from cryobookq.pipeline.write import ParquetStore


def load_scores(
    dates: list[str] | None = None,
    *,
    data_dir: Path | None = None,
) -> pd.DataFrame:
    store = ParquetStore(data_dir or get_settings().data_dir)
    return store.load_pair_scores(dates)


def who_wins(
    df: pd.DataFrame | None = None,
    *,
    metric: str = "winner_composite",
    session: str | None = None,
    dte_bucket: str | None = None,
    delta_bucket: str | None = None,
    matched_only: bool = True,
    data_dir: Path | None = None,
) -> pd.Series:
    """Win-rate counts by venue for a winner_* column.

    Returns Series indexed by venue name (deribit/coincall/tie) with counts,
    plus a ``win_rate`` attribute dict of rates excluding ties.
    """
    if df is None:
        df = load_scores(data_dir=data_dir)
    if df.empty:
        return pd.Series(dtype=int)

    q = df
    if matched_only and "match_status" in q.columns:
        q = q[q["match_status"] == "matched"]
    if session is not None:
        q = q[q["session"] == session]
    if dte_bucket is not None:
        q = q[q["dte_bucket"] == dte_bucket]
    if delta_bucket is not None:
        q = q[q["delta_bucket"] == delta_bucket]

    if metric not in q.columns:
        raise KeyError(f"metric {metric!r} not in columns")

    counts = q[metric].value_counts(dropna=True)
    decisive = counts.drop(labels=["tie"], errors="ignore")
    total = int(decisive.sum())
    rates = {k: (float(v) / total if total else 0.0) for k, v in decisive.items()}
    counts.attrs["win_rate"] = rates
    counts.attrs["n"] = int(len(q))
    return counts


def summarize_snapshot(df: pd.DataFrame) -> dict:
    """Compact summary for CLI / hub."""
    if df.empty:
        return {"n": 0}
    matched = df[df["match_status"] == "matched"] if "match_status" in df.columns else df
    wins = who_wins(matched, metric="winner_composite")
    spread = who_wins(matched, metric="winner_spread")
    cost = who_wins(matched, metric="winner_cost_buy")
    two_d = float(matched["deribit_two_sided"].mean()) if len(matched) else 0.0
    two_c = float(matched["coincall_two_sided"].mean()) if len(matched) else 0.0
    return {
        "n_rows": int(len(df)),
        "n_matched": int(len(matched)),
        "match_rate": float(len(matched) / len(df)) if len(df) else 0.0,
        "deribit_two_sided_rate": two_d,
        "coincall_two_sided_rate": two_c,
        "winner_composite": wins.to_dict(),
        "winner_composite_rate": wins.attrs.get("win_rate", {}),
        "winner_spread": spread.to_dict(),
        "winner_spread_rate": spread.attrs.get("win_rate", {}),
        "winner_cost_buy": cost.to_dict(),
        "winner_cost_buy_rate": cost.attrs.get("win_rate", {}),
        "by_session_composite": {
            s: who_wins(matched, metric="winner_composite", session=s).attrs.get("win_rate", {})
            for s in sorted(matched["session"].dropna().unique())
        }
        if "session" in matched.columns and len(matched)
        else {},
        "by_dte_composite": {
            b: who_wins(matched, metric="winner_composite", dte_bucket=b).attrs.get("win_rate", {})
            for b in sorted(matched["dte_bucket"].dropna().unique())
        }
        if "dte_bucket" in matched.columns and len(matched)
        else {},
    }
