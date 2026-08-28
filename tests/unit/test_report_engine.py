"""Unit tests for the minimal template engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from cryobookq.analytics.report.engine import TemplateEngine, render_template
from cryobookq.analytics.report.format import SafeHTML


def test_var_escaping(tmp_path: Path) -> None:
    (tmp_path / "t.html").write_text("<p>{{ name }}</p>", encoding="utf-8")
    out = render_template("t.html", {"name": "<b>x</b>"}, base_dir=tmp_path)
    assert out == "<p>&lt;b&gt;x&lt;/b&gt;</p>"


def test_safe_html_passthrough(tmp_path: Path) -> None:
    (tmp_path / "t.html").write_text("{{ body }}", encoding="utf-8")
    out = render_template("t.html", {"body": SafeHTML("<b>ok</b>")}, base_dir=tmp_path)
    assert out == "<b>ok</b>"


def test_include_and_nested(tmp_path: Path) -> None:
    (tmp_path / "snippets").mkdir()
    (tmp_path / "snippets" / "inner.html").write_text("Hello {{ who }}", encoding="utf-8")
    (tmp_path / "outer.html").write_text(
        'X {% include "snippets/inner.html" %} Y', encoding="utf-8"
    )
    out = TemplateEngine(tmp_path).render("outer.html", {"who": "world"})
    assert out == "X Hello world Y"


def test_circular_include(tmp_path: Path) -> None:
    (tmp_path / "a.html").write_text('{% include "b.html" %}', encoding="utf-8")
    (tmp_path / "b.html").write_text('{% include "a.html" %}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="circular"):
        TemplateEngine(tmp_path).render("a.html", {})


def test_missing_var(tmp_path: Path) -> None:
    (tmp_path / "t.html").write_text("{{ missing }}", encoding="utf-8")
    with pytest.raises(KeyError):
        render_template("t.html", {}, base_dir=tmp_path)
