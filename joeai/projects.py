"""Projects: several missions that belong together, with a project page (Files F7 > PROJECTS).

A mission joins a project with a PROJECT: line (Joe adds its folder here when it runs), or by
ADD A FOLDER on the project page. Nothing is moved: a project is a list of mission folders plus
the person's own notes and a "what's left" list. The "About" text is Projects/<name>.md, the
profile Joe already reads when he writes for that project.

Kept in Output/.joe/projects.json: {"projects": {name: {notes, todo: [{text, done}], missions: [rel],
created}}}.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .fsutil import atomic_write_text

FILE = "projects.json"
MAX_NOTES = 20000
MAX_TODO = 200
FILE_LIMIT = 300


def _path(sb) -> Path:
    return sb.meta / FILE


def _load(sb) -> dict:
    try:
        d = json.loads(_path(sb).read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("projects"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"projects": {}}


def _save(sb, d: dict) -> None:
    sb.meta.mkdir(parents=True, exist_ok=True)
    atomic_write_text(_path(sb), json.dumps(d, indent=1, ensure_ascii=False))


def clean(name: str) -> str:
    from .filing import clean_name
    return clean_name(name, 50) if (name or "").strip(" .") else ""


def _find(d: dict, name: str) -> str | None:
    want = clean(name).lower()
    return next((k for k in d["projects"] if k.lower() == want), None)


def names(sb) -> list[str]:
    return sorted(_load(sb)["projects"], key=str.lower)


def ensure(sb, name: str) -> str:
    d = _load(sb)
    k = _find(d, name)
    if k:
        return k
    n = clean(name)
    if not n:
        raise ValueError("Give the project a name.")
    d["projects"][n] = {"notes": "", "todo": [], "missions": [],
                        "created": datetime.now().isoformat(timespec="seconds")}
    _save(sb, d)
    return n


def add_mission(sb, name: str, folder_rel: str) -> None:
    """Joe calls this when a mission with PROJECT: gets its folder (no folder is moved)."""
    if not (name or "").strip() or not folder_rel:
        return
    try:
        k = ensure(sb, name)
    except ValueError:
        return
    d = _load(sb)
    ms = d["projects"][k].setdefault("missions", [])
    if folder_rel not in ms:
        ms.append(folder_rel)
        _save(sb, d)


def _inside_output(sb, rel: str) -> Path:
    from .sandbox import SandboxError
    out = sb.output.resolve()
    p = (out / (rel or "").replace("\\", "/").lstrip("/")).resolve()
    if p == out or out not in p.parents:
        raise SandboxError("Pick a folder inside Output.")
    if any(part.startswith(".") for part in p.relative_to(out).parts):
        raise SandboxError("That's one of Joe's private folders.")
    return p


def add_folder(sb, name: str, folder_rel: str) -> dict:
    k = _find(_load(sb), name)
    if not k:
        return {"ok": False, "error": "No project by that name."}
    try:
        p = _inside_output(sb, folder_rel)
    except Exception as e:                           # noqa: BLE001
        return {"ok": False, "error": str(e)}
    if not p.is_dir():
        return {"ok": False, "error": "That folder isn't in Output."}
    add_mission(sb, k, str(p.relative_to(sb.output.resolve())).replace("\\", "/"))
    return {"ok": True}


def remove_folder(sb, name: str, folder_rel: str) -> dict:
    d = _load(sb)
    k = _find(d, name)
    if not k:
        return {"ok": False, "error": "No project by that name."}
    ms = d["projects"][k].get("missions", [])
    if folder_rel in ms:
        ms.remove(folder_rel)
        _save(sb, d)
    return {"ok": True, "note": "Taken off the project. The folder and its files stay in Output."}


def save(sb, name: str, notes: str | None = None, todo: list | None = None, about: str | None = None) -> dict:
    d = _load(sb)
    k = _find(d, name)
    if not k:
        return {"ok": False, "error": "No project by that name."}
    p = d["projects"][k]
    if notes is not None:
        p["notes"] = str(notes)[:MAX_NOTES]
    if todo is not None:
        items = []
        for t in list(todo)[:MAX_TODO]:
            if isinstance(t, dict) and str(t.get("text", "")).strip():
                items.append({"text": " ".join(str(t["text"]).split())[:300], "done": bool(t.get("done"))})
        p["todo"] = items
    _save(sb, d)
    if about is not None:
        sb.projects.mkdir(parents=True, exist_ok=True)
        f = sb.projects / f"{k}.md"
        if about.strip():
            atomic_write_text(f, str(about)[:MAX_NOTES].rstrip() + "\n")
        elif f.exists():
            from .storage import trash
            try:
                trash(f)
            except OSError:
                pass
    return {"ok": True}


def delete(sb, name: str) -> dict:
    d = _load(sb)
    k = _find(d, name)
    if not k:
        return {"ok": False, "error": "No project by that name."}
    del d["projects"][k]
    _save(sb, d)
    return {"ok": True, "note": "The project is gone from the list. Its folders, files and About text stay."}


def _about(sb, name: str) -> str:
    for ext in (".md", ".txt"):
        f = sb.projects / f"{name}{ext}"
        if f.is_file():
            try:
                return f.read_text(encoding="utf-8", errors="replace")[:MAX_NOTES]
            except OSError:
                pass
    return ""


def _unfinished(sb, folders: list[str]) -> list[str]:
    """Tasks inside this project's folders that didn't finish (from Joe's run state)."""
    left = []
    for f in (sb.meta / "state").glob("*.json"):
        try:
            st = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out = (st.get("output") or "").replace("\\", "/")
        if st.get("status") in ("done", "skipped") or not out:
            continue
        if any(out == m or out.startswith(m + "/") for m in folders):
            left.append(f"{st.get('name', '?')}: {st.get('status')}" + (f" ({st['note']})" if st.get("note") else ""))
    return left[:50]


def summary(sb) -> list[dict]:
    d = _load(sb)
    out = []
    for k in sorted(d["projects"], key=str.lower):
        p = d["projects"][k]
        out.append({"name": k, "missions": len(p.get("missions", [])),
                    "left": sum(1 for t in p.get("todo", []) if not t.get("done"))})
    return out


def page(sb, name: str) -> dict:
    d = _load(sb)
    k = _find(d, name)
    if not k:
        return {"ok": False, "error": "No project by that name."}
    p = d["projects"][k]
    missions = []
    count = 0
    for rel in p.get("missions", []):
        folder = sb.output / rel
        files = []
        if folder.is_dir():
            for f in sorted(folder.rglob("*")):
                if count >= FILE_LIMIT:
                    break
                r = f.relative_to(sb.output)
                if f.is_file() and not any(x.startswith(".") for x in r.parts):
                    files.append(str(r).replace("\\", "/"))
                    count += 1
        missions.append({"folder": rel, "there": folder.is_dir(), "files": files})
    return {"ok": True, "name": k, "about": _about(sb, k), "notes": p.get("notes", ""),
            "todo": p.get("todo", []), "missions": missions,
            "unfinished": _unfinished(sb, p.get("missions", [])), "more_files": count >= FILE_LIMIT}


def repoint(sb, swap) -> None:
    """After tidy/undo moved folders: the project lists follow them."""
    d = _load(sb)
    changed = False
    for p in d["projects"].values():
        new = [swap(m) for m in p.get("missions", [])]
        if new != p.get("missions", []):
            p["missions"], changed = new, True
    if changed:
        _save(sb, d)
