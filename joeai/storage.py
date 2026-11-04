"""Storage housekeeping (F8): how much space Joe uses, capped logs, and cleanups.

Rules:
- Logs are trimmed automatically (they keep their newest lines).
- ComfyUI keeps its own copy of every picture it renders. Once Joe has saved his copy in
  Output, ComfyUI's copy is removed (Setup: comfy.delete_copies, on by default). Only files
  in ComfyUI's output\\Joe folder are ever touched: Joe never deletes your own ComfyUI renders.
- Everything else (rejected pictures, old versions, old reports) is only cleaned when you
  press the button and say yes. Those files go to the Recycle Bin / Trash, not gone forever.
"""
from __future__ import annotations

import ctypes
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from . import media as media_mod
from .config import Settings
from .sandbox import Sandbox

LOG_MAX_BYTES = 2 * 1024 * 1024        # a log over 2 MB ...
LOG_KEEP_BYTES = 1024 * 1024           # ... is cut back to its newest 1 MB
REPORT_MAX_AGE_DAYS = 30
JOE_COMFY_SUBFOLDER = "Joe"            # Joe renders with filename prefix "Joe/<task>"

CLEANUPS = {
    "rejected": "Pictures and videos you marked X (reject)",
    "versions": "Old versions (_v2, _v3 ... kept: the newest of each)",
    "reports": f"Reports older than {REPORT_MAX_AGE_DAYS} days",
    "comfy": "Leftover ComfyUI copies of Joe's pictures",
}


# --------------------------------------------------------------------------- logs
def cap_log(path: Path, max_bytes: int = LOG_MAX_BYTES, keep_bytes: int = LOG_KEEP_BYTES) -> bool:
    """If a log is bigger than max_bytes, keep only its newest keep_bytes (whole lines)."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size <= max_bytes:
        return False
    try:
        with open(path, "rb") as f:
            f.seek(max(0, size - keep_bytes))
            tail = f.read()
        nl = tail.find(b"\n")
        if 0 <= nl < len(tail) - 1:
            tail = tail[nl + 1:]
        note = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] (older lines removed to save space)\n"
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(note.encode("utf-8") + tail)
        os.replace(tmp, path)
        return True
    except OSError:
        return False                    # open in another program: try again later


def log_files(sb: Sandbox) -> list[Path]:
    from .addons import addons_dir
    from .config import config_dir
    out = [sb.output / "_log.txt", config_dir() / "crash.log"]
    a = addons_dir()
    if a.is_dir():
        out += sorted(a.glob("*.log"))
    return out


def cap_logs(sb: Sandbox) -> int:
    return sum(cap_log(p) for p in log_files(sb))


# --------------------------------------------------------------------------- sizes
def folder_size(path: Path, skip: tuple[str, ...] = ()) -> tuple[int, int]:
    """(bytes, files) under path, not following links. skip = folder names to leave out."""
    total = files = 0
    stack = [Path(path)]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if e.name not in skip:
                            stack.append(Path(e.path))
                    elif e.is_file(follow_symlinks=False):
                        total += e.stat(follow_symlinks=False).st_size
                        files += 1
                except OSError:
                    continue
    return total, files


def comfy_output_dir(settings: Settings) -> Path | None:
    """ComfyUI's own output folder (desktop app or portable), if it can be found."""
    c = settings.comfy
    cands: list[Path] = []
    if c.output_dir:
        cands.append(Path(c.output_dir))
    from .finder import find_comfy
    inst = find_comfy(c.start_command, c.start_dir, c.models_dir)
    if inst and inst.output_dir:
        cands.append(inst.output_dir)
    if c.models_dir:
        cands.append(Path(c.models_dir).parent / "output")
    if c.start_dir:
        sd = Path(c.start_dir)
        cands += [sd / "ComfyUI" / "output", sd / "output"]
    for p in cands:
        if p.is_dir():
            return p
    return None


def usage(settings: Settings, sb: Sandbox) -> dict:
    from .addons import addons_dir
    rows = []

    def add(key: str, label: str, path: Path | None, skip: tuple[str, ...] = ()):
        if path is None:
            return
        b, n = folder_size(path, skip) if path.exists() else (0, 0)
        rows.append({"key": key, "label": label, "path": str(path), "bytes": b, "files": n})

    add("output", "Output (Joe's work)", sb.output, skip=(".joe",))
    add("meta", "Joe's bookkeeping (state, old reports)", sb.meta)
    for name in ("Inbox", "Projects", "Missions", "Workflows", "Themes"):
        add(name.lower(), name, sb.root / name)
    add("addons", "Add-ons (voice, voice copy)", addons_dir())
    cd = comfy_output_dir(settings)
    if cd:
        add("comfy", "ComfyUI copies of Joe's pictures", cd / JOE_COMFY_SUBFOLDER)
    logs = [p for p in log_files(sb) if p.exists()]
    rows.append({"key": "logs", "label": "Logs (capped at 2 MB each)", "path": "",
                 "bytes": sum(_size(p) for p in logs), "files": len(logs)})
    workspace = sum(r["bytes"] for r in rows if r["key"] in
                    ("output", "meta", "inbox", "projects", "missions", "workflows", "themes"))
    try:
        du = shutil.disk_usage(sb.root)
        disk = {"total": du.total, "free": du.free}
    except OSError:
        disk = None
    return {"rows": rows, "workspace_bytes": workspace, "disk": disk,
            "cleanups": [{"kind": k, "label": v, **_summary(candidates(settings, sb, k))}
                         for k, v in CLEANUPS.items()]}


def _size(p: Path) -> int:
    try:
        return p.stat().st_size if p.is_file() else folder_size(p)[0]
    except OSError:
        return 0


def _summary(paths: list[Path]) -> dict:
    return {"count": len(paths), "bytes": sum(_size(p) for p in paths)}


# --------------------------------------------------------------------------- cleanups
_VER = re.compile(r"^(?P<stem>.+?)_v(?P<n>\d+)$")


def candidates(settings: Settings, sb: Sandbox, kind: str) -> list[Path]:
    if kind == "rejected":
        return _rejected(sb)
    if kind == "versions":
        return _old_versions(sb)
    if kind == "reports":
        return _old_reports(sb)
    if kind == "comfy":
        cd = comfy_output_dir(settings)
        d = cd / JOE_COMFY_SUBFOLDER if cd else None
        return sorted(p for p in d.rglob("*") if p.is_file()) if d and d.is_dir() else []
    raise ValueError(f"unknown cleanup: {kind}")


def _rejected(sb: Sandbox) -> list[Path]:
    out = []
    for man in sb.output.rglob(media_mod.MANIFEST):
        folder = man.parent
        for name, meta in media_mod.load(folder).get("items", {}).items():
            if isinstance(meta, dict) and meta.get("review") == "reject":
                p = folder / name
                if p.is_file():
                    out.append(p)
    return sorted(out)


def _protected_folder(folder: Path) -> bool:
    """A picture folder with anything marked keep or star is never 'old'."""
    items = media_mod.load(folder).get("items", {})
    return any(isinstance(m, dict) and m.get("review") in ("keep", "star") for m in items.values())


def _old_versions(sb: Sandbox) -> list[Path]:
    """Every versioned group (name, name_v2, name_v3 ...): all but the newest one."""
    groups: dict[tuple[Path, str, str, bool], list[Path]] = {}
    for p in sb.output.rglob("*"):
        if ".joe" in p.parts or p.name.startswith(("_", ".")):
            continue
        is_dir = p.is_dir()
        stem, suffix = (p.name, "") if is_dir else (p.stem, p.suffix)
        m = _VER.match(stem)
        base = m["stem"] if m else stem
        groups.setdefault((p.parent, base, suffix.lower(), is_dir), []).append(p)
    out = []
    for (parent, base, suffix, is_dir), members in groups.items():
        if len(members) < 2 or not any(_VER.match(m.name if is_dir else m.stem) for m in members):
            continue
        members.sort(key=lambda m: _mtime(m))
        for old in members[:-1]:                         # keep the newest
            if is_dir and _protected_folder(old):
                continue
            out.append(old)
    return sorted(out)


def _old_reports(sb: Sandbox) -> list[Path]:
    d = sb.meta / "reports"
    if not d.is_dir():
        return []
    cutoff = time.time() - REPORT_MAX_AGE_DAYS * 86400
    return sorted(p for p in d.glob("REPORT_*.md") if _mtime(p) < cutoff)


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def clean(settings: Settings, sb: Sandbox, kind: str) -> dict:
    """Move one kind of clutter to the Recycle Bin / Trash. Returns counts."""
    paths = candidates(settings, sb, kind)
    allowed = [sb.output]
    if kind == "comfy":
        cd = comfy_output_dir(settings)
        allowed = [cd / JOE_COMFY_SUBFOLDER] if cd else []
    moved = freed = 0
    errors = []
    for p in paths:
        if not any(_inside(p, a) for a in allowed):
            continue
        size = _size(p)
        try:
            trash(p)
        except OSError as e:
            errors.append(f"{p.name}: {e}")
            continue
        moved += 1
        freed += size
        if kind == "rejected":
            _forget_review(p)
    return {"ok": not errors, "moved": moved, "freed": freed, "errors": errors[:5]}


def _forget_review(p: Path) -> None:
    d = media_mod.load(p.parent)
    if d.get("items", {}).pop(p.name, None) is not None:
        media_mod.save(p.parent, d)


def _inside(p: Path, root: Path) -> bool:
    try:
        Path(os.path.realpath(p)).relative_to(Path(os.path.realpath(root)))
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------- ComfyUI copies
def delete_comfy_copies(settings: Settings, files: list[dict]) -> int:
    """After Joe saved his copy: remove ComfyUI's own copy of these outputs.
    Only files under ComfyUI's output\\Joe\\ folder are touched."""
    if not settings.comfy.delete_copies or not files:
        return 0
    cd = comfy_output_dir(settings)
    if not cd:
        return 0
    joe_dir = cd / JOE_COMFY_SUBFOLDER
    n = 0
    for f in files:
        if f.get("type", "output") != "output":
            continue
        sub = str(f.get("subfolder", "")).replace("\\", "/").strip("/")
        name = str(f.get("filename", ""))
        if not name or "/" in name or "\\" in name or ".." in sub.split("/"):
            continue
        p = cd.joinpath(*[s for s in sub.split("/") if s], name)
        if not _inside(p, joe_dir) or not p.is_file():
            continue
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n


# --------------------------------------------------------------------------- trash
def trash(p: Path) -> None:
    """Send a file or folder to the Recycle Bin (Windows) / Trash (Mac, Linux)."""
    p = Path(p)
    if not p.exists():
        return
    if sys.platform == "win32":
        _win_recycle(p)
    elif sys.platform == "darwin":
        _move_unique(p, Path.home() / ".Trash")
    else:
        _freedesktop_trash(p)


def _move_unique(p: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest, n = dest_dir / p.name, 2
    while dest.exists():
        dest = dest_dir / f"{p.stem} {n}{p.suffix}"
        n += 1
    shutil.move(str(p), str(dest))
    return dest


def _freedesktop_trash(p: Path) -> None:
    from urllib.parse import quote
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "Trash"
    (root / "info").mkdir(parents=True, exist_ok=True)
    src = p.resolve()
    dest = _move_unique(p, root / "files")
    (root / "info" / f"{dest.name}.trashinfo").write_text(
        f"[Trash Info]\nPath={quote(str(src))}\nDeletionDate={datetime.now():%Y-%m-%dT%H:%M:%S}\n",
        encoding="utf-8")


def _win_recycle(p: Path) -> None:
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint),
                    ("pFrom", ctypes.c_wchar_p), ("pTo", ctypes.c_wchar_p),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", ctypes.c_int),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 4, 16, 64, 1024
    op = SHFILEOPSTRUCTW(None, FO_DELETE, str(p.resolve()) + "\0", None,
                         FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI, 0, None, None)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc or op.fAnyOperationsAborted or p.exists():
        raise OSError(f"could not move to the Recycle Bin (code {rc})")
