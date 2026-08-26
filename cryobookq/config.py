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
    coincall_api_key: str | None = None
    coincall_api_secret: str | None = None
    coincall_env: str = "production"
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    @property
    def has_coincall_creds(self) -> bool:
        return bool(self.coincall_api_key and self.coincall_api_secret)


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
        coincall_api_key=os.getenv("COINCALL_API_KEY") or None,
        coincall_api_secret=os.getenv("COINCALL_API_SECRET") or None,
        coincall_env=os.getenv("COINCALL_ENV", "production"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
    )
