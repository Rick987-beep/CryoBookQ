"""Configuration from environment (`BOOKQ_*` and Coincall keys)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]


def load_env(dotenv_path: Path | None = None) -> None:
    """Load `.env` from repo root (or given path). Idempotent."""
    path = dotenv_path or (_REPO_ROOT / ".env")
    if path.is_file():
        load_dotenv(path, override=False)


@dataclass(frozen=True, slots=True)
class Settings:
    underlying: str = "BTC"
    depth: int = 5
    snapshot_interval_min: int = 15
    data_dir: Path = Path("./data")
    hub_port: int = 8088
    health_port: int = 8091
    coincall_api_key: str | None = None
    coincall_api_secret: str | None = None
    coincall_env: str = "production"
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    # P0 quality / disk
    coverage_floor_deribit: float = 0.90
    coverage_floor_coincall: float = 0.80
    coverage_floor_bybit: float = 0.80
    coverage_floor_okx: float = 0.80
    coverage_floor_binance: float = 0.80
    # Peer wait_for budget: lead-open collect is ~34s; leave headroom for
    # connect/subscribe + WS teardown (see Coincall close-handshake timeouts).
    burst_timeout_s: float = 55.0
    ws_collect_s: float = 30.0
    # Binance is a slow sampler (stream cap + REST weight). Peers keep burst_timeout_s.
    binance_collect_s: float = 30.0
    binance_rest_budget_s: float = 45.0
    binance_timeout_s: float = 90.0
    disk_free_warn_mb: int = 5000
    disk_free_abort_mb: int = 500
    # P1
    instrument_cache_ttl_s: float = 1800.0  # 30 minutes
    clock_resync_every_s: float = 900.0  # re-sync Deribit clock at least this often
    hub_snapshot_n: int = 4  # rolling mean window for public dashboard
    hub_mount: str = ""  # e.g. /bookq when nginx proxies a subpath

    @property
    def has_coincall_creds(self) -> bool:
        return bool(self.coincall_api_key and self.coincall_api_secret)

    def coverage_floors(self) -> dict[str, float]:
        return {
            "deribit": self.coverage_floor_deribit,
            "coincall": self.coverage_floor_coincall,
            "bybit": self.coverage_floor_bybit,
            "okx": self.coverage_floor_okx,
            "binance": self.coverage_floor_binance,
        }

    def burst_wait_s(self, venue: str) -> float:
        """Per-venue asyncio.wait_for budget. Only Binance uses the long sampler cap."""
        if venue.strip().lower() == "binance":
            return float(self.binance_timeout_s)
        return float(self.burst_timeout_s)

    def burst_duration_s(self, venue: str, requested: float) -> float:
        """WS collect window. All venues listen at least ws_collect_s; Binance uses its own floor."""
        if venue.strip().lower() == "binance":
            return max(float(requested), float(self.binance_collect_s))
        return max(float(requested), float(self.ws_collect_s))


def get_settings(*, load: bool = True) -> Settings:
    if load:
        load_env()
    data_dir = Path(os.getenv("BOOKQ_DATA_DIR", "./data"))
    return Settings(
        underlying=os.getenv("BOOKQ_UNDERLYING", "BTC").upper(),
        depth=int(os.getenv("BOOKQ_DEPTH", "5")),
        snapshot_interval_min=int(os.getenv("BOOKQ_SNAPSHOT_INTERVAL_MIN", "15")),
        data_dir=data_dir,
        hub_port=int(os.getenv("BOOKQ_HUB_PORT", "8088")),
        health_port=int(os.getenv("BOOKQ_HEALTH_PORT", "8091")),
        coincall_api_key=os.getenv("COINCALL_API_KEY") or None,
        coincall_api_secret=os.getenv("COINCALL_API_SECRET") or None,
        coincall_env=os.getenv("COINCALL_ENV", "production"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        coverage_floor_deribit=float(os.getenv("BOOKQ_COVERAGE_FLOOR_DERIBIT", "0.90")),
        coverage_floor_coincall=float(os.getenv("BOOKQ_COVERAGE_FLOOR_COINCALL", "0.80")),
        coverage_floor_bybit=float(os.getenv("BOOKQ_COVERAGE_FLOOR_BYBIT", "0.80")),
        coverage_floor_okx=float(os.getenv("BOOKQ_COVERAGE_FLOOR_OKX", "0.80")),
        coverage_floor_binance=float(os.getenv("BOOKQ_COVERAGE_FLOOR_BINANCE", "0.80")),
        burst_timeout_s=float(os.getenv("BOOKQ_BURST_TIMEOUT_S", "55")),
        ws_collect_s=float(os.getenv("BOOKQ_WS_COLLECT_S", "30")),
        binance_collect_s=float(os.getenv("BOOKQ_BINANCE_COLLECT_S", "30")),
        binance_rest_budget_s=float(os.getenv("BOOKQ_BINANCE_REST_BUDGET_S", "45")),
        binance_timeout_s=float(os.getenv("BOOKQ_BINANCE_TIMEOUT_S", "90")),
        disk_free_warn_mb=int(os.getenv("BOOKQ_DISK_FREE_WARN_MB", "5000")),
        disk_free_abort_mb=int(os.getenv("BOOKQ_DISK_FREE_ABORT_MB", "500")),
        instrument_cache_ttl_s=float(os.getenv("BOOKQ_INSTRUMENT_CACHE_TTL_S", "1800")),
        clock_resync_every_s=float(os.getenv("BOOKQ_CLOCK_RESYNC_EVERY_S", "900")),
        hub_snapshot_n=int(os.getenv("BOOKQ_HUB_SNAPSHOT_N", "4")),
        hub_mount=os.getenv("BOOKQ_HUB_MOUNT", "").strip(),
    )
