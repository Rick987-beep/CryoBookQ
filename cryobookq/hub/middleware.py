"""WSGI middleware for subpath deployment (nginx ``/bookq/`` → hub root)."""

from __future__ import annotations

from collections.abc import Callable


class ScriptNameMiddleware:
    """Set ``SCRIPT_NAME`` so Flask ``url_for`` emits prefixed URLs."""

    def __init__(self, app: Callable, script_name: str) -> None:
        self.app = app
        self.script_name = script_name.rstrip("/") if script_name else ""

    def __call__(self, environ, start_response):
        if self.script_name:
            environ["SCRIPT_NAME"] = self.script_name
        return self.app(environ, start_response)
