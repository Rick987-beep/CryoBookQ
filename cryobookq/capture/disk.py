"""Disk free-space helpers (tickrecorder-style warn / abort thresholds)."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def disk_free_mb(path: Path | str) -> int:
    """Free megabytes on the filesystem containing *path*, or -1 on error."""
    try:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(p)
        return int(usage.free // (1024 * 1024))
    except OSError as exc:
        logger.warning("disk_free_mb failed for %s: %s", path, exc)
        return -1


class DiskFullError(RuntimeError):
    """Raised when free disk is below the abort threshold."""
