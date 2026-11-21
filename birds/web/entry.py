"""Build the app from environment variables: the single code path for Vercel (app.py) and for local runs."""

from __future__ import annotations

from collections.abc import Mapping

from .server import create_app
from .settings import Settings


def create_app_from_env(env: Mapping[str, str] | None = None):
    return create_app(Settings.from_env(env))
