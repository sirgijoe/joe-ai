"""Crash-safe file writes: write to a temp file, then atomically replace."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_append_text(path: Path, text: str) -> None:
    """Append by rewriting the whole file atomically (outputs are small)."""
    path = Path(path)
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    atomic_write_text(path, old + text)
