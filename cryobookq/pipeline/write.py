"""Atomic daily Parquet writers for raw_books and pair_scores.

P0: each snapshot writes its own ``part-{ts_ms}.parquet`` file. We never
read-modify-rewrite a growing daily blob (that was O(n²) I/O by end of day).
Loaders glob all parts under ``date=YYYY-MM-DD/``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from cryobookq.schemas import PAIR_SCORE_COLUMNS, RAW_BOOK_COLUMNS, atomic_write_parquet

logger = logging.getLogger(__name__)


class ParquetStore:
    """Hive-ish daily layout under data_dir/{raw_books,pair_scores}/date=YYYY-MM-DD/."""

    def __init__(self, data_dir: Path, *, depth: int = 5, cadence_min: int = 15) -> None:
        self.data_dir = Path(data_dir)
        self.depth = depth
        self.cadence_min = cadence_min
        self.raw_dir = self.data_dir / "raw_books"
        self.scores_dir = self.data_dir / "pair_scores"

    def _day_dir(self, root: Path, ts_ms: int) -> Path:
        day = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d")
        return root / f"date={day}"

    def raw_path(self, ts_ms: int) -> Path:
        return self._day_dir(self.raw_dir, ts_ms) / f"part-{ts_ms}.parquet"

    def scores_path(self, ts_ms: int) -> Path:
        return self._day_dir(self.scores_dir, ts_ms) / f"part-{ts_ms}.parquet"

    def write_raw_books(
        self,
        rows: list[dict],
        ts_ms: int,
        *,
        append: bool = False,  # noqa: ARG002 — kept for API compat; ignored
        extra: dict[str, str] | None = None,
    ) -> Path:
        """Write one snapshot part file. ``append`` is ignored (parts are immutable)."""
        if not rows:
            raise ValueError("no raw book rows to write")
        df = pd.DataFrame(rows)
        for col in RAW_BOOK_COLUMNS:
            if col not in df.columns:
                df[col] = None
        df = df[RAW_BOOK_COLUMNS]
        path = self.raw_path(ts_ms)
        if path.is_file():
            # Same ts_ms twice would overwrite; log loudly — BoundaryTracker should prevent this.
            logger.warning("Overwriting existing raw part %s", path)
        meta = {"table": "raw_books", **(extra or {})}
        atomic_write_parquet(df, path, depth=self.depth, cadence_min=self.cadence_min, extra=meta)
        logger.info("Wrote %d raw_books rows → %s", len(df), path)
        return path

    def write_pair_scores(
        self,
        rows: list[dict],
        ts_ms: int,
        *,
        append: bool = False,  # noqa: ARG002
        extra: dict[str, str] | None = None,
    ) -> Path:
        if not rows:
            raise ValueError("no pair score rows to write")
        df = pd.DataFrame(rows)
        for col in PAIR_SCORE_COLUMNS:
            if col not in df.columns:
                df[col] = None
        df = df[PAIR_SCORE_COLUMNS]
        path = self.scores_path(ts_ms)
        if path.is_file():
            logger.warning("Overwriting existing scores part %s", path)
        meta = {"table": "pair_scores", **(extra or {})}
        atomic_write_parquet(df, path, depth=self.depth, cadence_min=self.cadence_min, extra=meta)
        logger.info("Wrote %d pair_scores rows → %s", len(df), path)
        return path

    def load_raw_books(self, dates: list[str] | None = None) -> pd.DataFrame:
        return self._load_table(self.raw_dir, dates)

    def load_pair_scores(self, dates: list[str] | None = None) -> pd.DataFrame:
        return self._load_table(self.scores_dir, dates)

    def _load_table(self, root: Path, dates: list[str] | None) -> pd.DataFrame:
        if not root.is_dir():
            return pd.DataFrame()
        files: list[Path] = []
        if dates:
            for d in dates:
                files.extend(sorted((root / f"date={d}").glob("part-*.parquet")))
                # Legacy single-file layout from pre-P0
                files.extend(sorted((root / f"date={d}").glob("part-000.parquet")))
        else:
            files = sorted(root.glob("date=*/part-*.parquet"))
        # De-dupe while preserving order
        seen: set[Path] = set()
        uniq: list[Path] = []
        for f in files:
            if f not in seen:
                seen.add(f)
                uniq.append(f)
        if not uniq:
            return pd.DataFrame()
        return pd.concat([pd.read_parquet(f) for f in uniq], ignore_index=True)
