"""Past Talk chats: every time Joe opens (or NEW CHAT is pressed) a fresh chat starts, and
each one is saved in Joe's own folder (Output/.joe/chats/) so it can be read again later.

Chats can be deleted one at a time or all at once, and old ones are removed automatically
after Setup > Voice > "Delete chats after (days)" (0 = keep them). Nothing leaves the PC.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

_ID = re.compile(r"^\d{8}_\d{6}(_\d+)?$")


class Chats:
    def __init__(self, folder: Path):
        self.dir = folder
        self.current: dict | None = None

    # -- the chat being had right now -----------------------------------------------
    def new(self) -> None:
        """Start fresh. Nothing is written until the first message, so empty chats leave no file."""
        self.current = None

    def add(self, you: str, joe: str, mission: str = "") -> None:
        now = datetime.now()
        if self.current is None:
            cid = now.strftime("%Y%m%d_%H%M%S")
            n = 2
            while (self.dir / f"{cid}.json").exists():
                cid = now.strftime("%Y%m%d_%H%M%S") + f"_{n}"
                n += 1
            self.current = {"id": cid, "started": now.isoformat(timespec="seconds"),
                            "title": _title(you), "messages": []}
        ts = now.isoformat(timespec="seconds")
        self.current["messages"].append({"who": "you", "text": you, "ts": ts})
        joe_msg = {"who": "joe", "text": joe, "ts": ts}
        if mission:
            joe_msg["mission"] = mission
        self.current["messages"].append(joe_msg)
        self.current["updated"] = ts
        self._write(self.current)

    # -- past chats ------------------------------------------------------------------
    def list(self, q: str = "") -> list[dict]:
        """Newest first (by last message). q = only chats containing all these words."""
        words = [w for w in (q or "").lower().split() if w]
        out = []
        for p in self.dir.glob("*.json") if self.dir.is_dir() else []:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if words:
                hay = (d.get("title", "") + " " + " ".join(m.get("text", "") for m in d.get("messages", []))).lower()
                if not all(w in hay for w in words):
                    continue
            out.append({"id": d.get("id", p.stem), "title": d.get("title", ""),
                        "started": d.get("started", ""), "updated": d.get("updated", ""),
                        "messages": len(d.get("messages", [])), "bytes": p.stat().st_size,
                        "current": bool(self.current and self.current["id"] == p.stem)})
        out.sort(key=lambda c: c["updated"] or c["started"], reverse=True)
        return out

    def open(self, cid: str) -> dict | None:
        """Pick an old chat back up: new messages are added to it."""
        d = self.get(cid)
        if d:
            self.current = d
        return d

    def get(self, cid: str) -> dict | None:
        p = self._path(cid)
        if not p or not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def delete(self, cid: str) -> bool:
        p = self._path(cid)
        if not p or not p.exists():
            return False
        p.unlink()
        if self.current and self.current["id"] == cid:
            self.current = None
        return True

    def delete_all(self) -> int:
        n = 0
        for p in self.dir.glob("*.json"):
            if _ID.match(p.stem):
                p.unlink()
                n += 1
        self.current = None
        return n

    def prune(self, keep_days: int) -> int:
        """Remove chats not touched in keep_days days (0 = keep everything)."""
        if keep_days <= 0 or not self.dir.is_dir():
            return 0
        cutoff = time.time() - keep_days * 86400
        n = 0
        for p in self.dir.glob("*.json"):
            if not _ID.match(p.stem) or (self.current and p.stem == self.current["id"]):
                continue
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    n += 1
            except OSError:
                pass
        return n

    def size(self) -> int:
        return sum(p.stat().st_size for p in self.dir.glob("*.json")) if self.dir.is_dir() else 0

    # -- helpers -----------------------------------------------------------------------
    def _path(self, cid: str) -> Path | None:
        return self.dir / f"{cid}.json" if _ID.match(cid or "") else None   # never outside the folder

    def _write(self, d: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f"{d['id']}.json.tmp"
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.dir / f"{d['id']}.json")


def _title(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip() or "(a file)"
    return t if len(t) <= 60 else t[:57].rstrip() + "…"
