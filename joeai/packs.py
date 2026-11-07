"""Starter packs: ready-made bundles of work (a shop starter, a month of posts...).

Each pack is a mission in joeai/packs/*.txt with three header lines (PACK, ABOUT, ASK). The
person answers one plain question ("What's your shop and what do you sell?") and the answer
goes wherever the pack says {for}. The result is checked and shown like any other plan.
Your own packs: put the same kind of file in Missions/Packs in Joe's folder.
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent / "packs"


def _read(p: Path) -> dict | None:
    try:
        text = p.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    head = dict(re.findall(r"(?m)^(PACK|ABOUT|ASK):[ \t]*(.+)$", text.split("===", 1)[0]))
    body = text[text.find("==="):] if "===" in text else ""
    if not head.get("PACK") or not body:
        return None
    return {"id": p.stem, "name": head["PACK"].strip(), "about": head.get("ABOUT", "").strip(),
            "ask": head.get("ASK", "What's it for?").strip(), "mission": body.strip()}


def list_packs(sb=None) -> list[dict]:
    """Built-in packs first, then the person's own (Missions/Packs)."""
    out, seen = [], set()
    roots = [HERE] + ([sb.missions / "Packs"] if sb is not None else [])
    for root in roots:
        if not root.is_dir():
            continue
        for p in sorted(root.glob("*.txt")):
            pk = _read(p)
            if pk and pk["id"] not in seen:
                pk["own"] = root != HERE
                seen.add(pk["id"])
                out.append(pk)
    return out


def build(sb, pack_id: str, answer: str) -> str:
    """The pack's mission with the person's answer in place of {for}."""
    from .mission import _safe
    pk = next((p for p in list_packs(sb) if p["id"] == pack_id), None)
    if pk is None:
        raise KeyError(pack_id)
    ans = " ".join(_safe(answer or "").split())[:200].strip(" .") or "my project"
    return pk["mission"].replace("{for}", ans)


def split_blocks(text: str) -> list[str]:
    """A file with several mission blocks (a pack someone saved, a long night's list) -> one
    mission per block. A file with one block or none comes back as it is."""
    blocks = re.findall(r"===\s*JOE\s+MISSION\s*===.*?(?:===\s*END\s*===|(?====\s*JOE\s+MISSION)|\Z)",
                        text or "", re.S | re.I)
    return [b.strip() for b in blocks] if len(blocks) > 1 else [text]


def drop_task(text: str, name: str) -> str:
    """The mission without one task (a pack part this PC can't do yet)."""
    import re as _re
    parts = _re.split(r"(?m)^(?=TASK:)", text)
    keep = [p for p in parts if not _re.match(rf"TASK:[ \t]*{_re.escape(name)}(?:[ \t]*$|[ \t]{{2,}}[A-Z][A-Z ]*:)",
                                              p.splitlines()[0] if p else "")]
    out = "".join(keep)
    if "=== END ===" not in out:
        out = out.rstrip() + "\n=== END ===\n"
    return out


def plan(app, text: str) -> tuple[dict, str, list[str]]:
    """Check a pack's mission; a task this PC can't do yet is left out (and said so) instead of
    failing the whole pack. Returns (check result, mission text, notes)."""
    import re as _re
    notes: list[str] = []
    for _ in range(5):
        chk = app.check(text)
        if chk["ok"]:
            return chk, text, notes
        m = _re.match(r"Task '([^']+)': (.*)", chk.get("error", ""))
        if not m or "needs" not in m.group(2) and "isn't installed" not in m.group(2):
            return chk, text, notes
        text = drop_task(text, m.group(1))
        notes.append(f"Left out '{m.group(1)}': {m.group(2)}")
    return app.check(text), text, notes
