"""2.1 watch folders: files dropped in Inbox/Watch/<tool> run by themselves."""
from __future__ import annotations

import os
import time

from test_tools import app  # noqa: F401


def test_watch_folders(app):  # noqa: F811
    assert app.watch_tick() == []                                     # off by default
    assert app.save_settings({"schedule": {"watch": True}})["ok"]
    root = app.sb.inbox / "Watch"
    assert (root / "summarize").is_dir() and (root / "READ ME.txt").exists()
    assert not (root / "translate").exists() and not (root / "brainstorm").exists()   # must-pick / no-file tools
    f = root / "summarize" / "lease.md"
    f.write_text("The lease runs a year.", encoding="utf-8")
    (root / "summarize" / "skip.exe").write_bytes(b"x")
    assert app.watch_tick() == []                                     # too new: may still be copying
    old = time.time() - 30
    os.utime(f, (old, old))
    assert app.watch_tick() == ["summarize"]
    app.thread.join(timeout=60)
    assert app.watch_tick() == []                                     # seen: not again
    out = [p for p in app.sb.output.glob("watch-summarize*/lease-summary.md")]
    assert out and "Summary" in out[0].read_text(encoding="utf-8")
