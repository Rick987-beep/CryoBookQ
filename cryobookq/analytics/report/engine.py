"""Minimal template engine: ``{{ var }}`` and ``{% include "path" %}``.

No third-party dependency. Values subclassing ``SafeHTML`` are inserted as-is;
everything else is HTML-escaped. Nested keys use dotted paths (``a.b.c``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cryobookq.analytics.report.format import SafeHTML, esc

_INCLUDE_RE = re.compile(r"""\{%\s*include\s+["']([^"']+)["']\s*%\}""")
_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _lookup(ctx: dict[str, Any], path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(f"template variable {path!r} not found")
    return cur


def _format_value(value: Any) -> str:
    if isinstance(value, SafeHTML):
        return str(value)
    if value is None:
        return ""
    return esc(value)


class TemplateEngine:
    """Load templates relative to a base directory and render with includes."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else TEMPLATES_DIR
        self._cache: dict[str, str] = {}

    def load(self, name: str) -> str:
        if name in self._cache:
            return self._cache[name]
        path = self.base_dir / name
        text = path.read_text(encoding="utf-8")
        self._cache[name] = text
        return text

    def render(self, name: str, ctx: dict[str, Any], *, _stack: tuple[str, ...] = ()) -> str:
        if name in _stack:
            chain = " → ".join([*_stack, name])
            raise RuntimeError(f"circular template include: {chain}")
        text = self.load(name)

        def include_one(match: re.Match[str]) -> str:
            return self.render(match.group(1), ctx, _stack=(*_stack, name))

        # Resolve includes until stable (nested includes inside snippets).
        for _ in range(32):
            if not _INCLUDE_RE.search(text):
                break
            text = _INCLUDE_RE.sub(include_one, text)
        else:
            raise RuntimeError(f"too many include passes in {name!r}")

        def var_one(match: re.Match[str]) -> str:
            return _format_value(_lookup(ctx, match.group(1)))

        return _VAR_RE.sub(var_one, text)


def render_template(name: str, ctx: dict[str, Any], *, base_dir: Path | None = None) -> str:
    return TemplateEngine(base_dir).render(name, ctx)
