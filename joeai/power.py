"""Keep the computer awake during a run, and optional sleep/shutdown afterwards.

The per-system details live in system.py; this module keeps the old names.
"""
from __future__ import annotations

from .system import keep_awake, when_finished  # noqa: F401
