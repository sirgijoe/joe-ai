"""BACK UP MY SETTINGS / RESTORE FROM A BACKUP (Setup > General).

One zip with everything you set up by hand, for a new computer, after a reinstall, or to give
a friend your setup:
  settings.json      every setting (writing templates of your own, workflow words, looks...).
                     Keys, passwords and the phone-ping topic only if you tick "include keys".
  Themes/            your color themes and screen savers
  Workflows/         ComfyUI workflow files you imported
  Projects/          project profiles (brand voice, facts, rules)
  Missions/Packs/    starter packs of your own
  manifest.json      what this is, which Joe made it, when

Never inside: your Inbox and Output files, chats, recordings, voices or models.
Restoring never touches where things are on THIS computer (Joe's folder, program paths), and
never overwrites a file you already have: a different file with the same name comes back as
"name (restored)".
"""
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from . import __version__

FOLDERS = ("Themes", "Workflows", "Projects", "Missions/Packs")
KEY_PATHS = (("mcp_key",), ("web", "ollama_key"), ("comfort", "ntfy_topic"), ("comfort", "ntfy_server"))
# where things are on THIS computer: never taken from a backup
LOCAL_PATHS = (("workspace",), ("pandoc",), ("ollama", "exe"), ("ollama", "engine_start"),
               ("comfy", "start_command"), ("comfy", "start_dir"), ("comfy", "models_dir"),
               ("comfy", "ffmpeg"), ("comfy", "output_dir"), ("ui", "welcomed"))
MAX_TOTAL = 300_000_000            # a settings backup is small; refuse anything huge
MAX_FILES = 5000
MARK = "joe-settings-backup"


def _get(d: dict, path: tuple[str, ...]):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _set(d: dict, path: tuple[str, ...], value) -> None:
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = value


def _drop(d: dict, path: tuple[str, ...]) -> None:
    for k in path[:-1]:
        if not isinstance(d, dict) or k not in d:
            return
        d = d[k]
    if isinstance(d, dict):
        d.pop(path[-1], None)


def make(settings, sb, keys: bool = False) -> Path:
    """The backup zip, saved in Output/Backups. Returns its path."""
    data = asdict(settings)
    if not keys:
        for p in KEY_PATHS:
            if _get(data, p) not in (None, ""):
                _set(data, p, "")
    for p in LOCAL_PATHS:                 # meaningless on another computer
        _drop(data, p)
    out_dir = sb.output / "Backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"joe-settings-{datetime.now():%Y-%m-%d_%H%M}.zip"
    n = 2
    while dest.exists():
        dest = out_dir / f"joe-settings-{datetime.now():%Y-%m-%d_%H%M}-{n}.zip"
        n += 1
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps({"kind": MARK, "joe": __version__,
                                                "made": datetime.now().isoformat(timespec="seconds"),
                                                "keys": bool(keys)}, indent=1))
        z.writestr("settings.json", json.dumps(data, indent=2))
        for folder in FOLDERS:
            root = sb.root / folder
            if not root.is_dir():
                continue
            for f in sorted(root.rglob("*")):
                if f.is_file() and not f.name.startswith(".") and f.suffix.lower() != ".part":
                    z.write(f, (Path(folder) / f.relative_to(root)).as_posix())
    return dest


def _safe_name(n: str) -> bool:
    parts = n.replace("\\", "/").split("/")
    return not (n.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]))


def read(data: bytes) -> tuple[dict, zipfile.ZipFile]:
    """Open and check a backup; raises ValueError with a plain reason."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError("That isn't a Joe settings backup (not a zip file).") from e
    names = z.namelist()
    if "manifest.json" not in names or "settings.json" not in names:
        raise ValueError("That zip isn't a Joe settings backup (made with BACK UP MY SETTINGS).")
    try:
        man = json.loads(z.read("manifest.json"))
    except ValueError as e:
        raise ValueError("That backup's label is damaged.") from e
    if not isinstance(man, dict) or man.get("kind") != MARK:
        raise ValueError("That zip isn't a Joe settings backup.")
    infos = z.infolist()
    if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_TOTAL:
        raise ValueError("That backup is far bigger than a settings backup can be.")
    for n in names:
        if not _safe_name(n):
            raise ValueError("That backup has an unsafe file name in it; nothing was restored.")
        if n not in ("manifest.json", "settings.json") and not any(
                n.startswith(f + "/") for f in FOLDERS) and n.rstrip("/") not in FOLDERS:
            raise ValueError(f"That backup has an unexpected file in it ({n}); nothing was restored.")
    return man, z


def restore(settings, sb, data: bytes) -> dict:
    """Bring a backup back. Returns {ok, settings: bool, files: n, renamed: n, joe}."""
    from .config import _merge
    man, z = read(data)
    try:
        incoming = json.loads(z.read("settings.json"))
    except ValueError as e:
        raise ValueError("The settings in that backup are damaged; nothing was restored.") from e
    if not isinstance(incoming, dict):
        raise ValueError("The settings in that backup are damaged; nothing was restored.")
    for p in LOCAL_PATHS:                 # this computer's places stay as they are
        _drop(incoming, p)
    for p in KEY_PATHS:                   # a backup without keys keeps the keys you have now
        if _get(incoming, p) in (None, ""):
            _drop(incoming, p)
    _merge(settings, incoming)
    files = renamed = 0
    for info in z.infolist():
        n = info.filename
        if info.is_dir() or n in ("manifest.json", "settings.json"):
            continue
        dest = sb.root / Path(*n.split("/"))
        sb.check(dest)
        body = z.read(info)
        if dest.exists():
            try:
                if dest.read_bytes() == body:
                    continue              # already the same
            except OSError:
                pass
            stem, ext, k = dest.stem, dest.suffix, 1
            alt = dest.with_name(f"{stem} (restored){ext}")
            while alt.exists():
                k += 1
                alt = dest.with_name(f"{stem} (restored {k}){ext}")
            dest, renamed = alt, renamed + 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        files += 1
    return {"ok": True, "settings": True, "files": files, "renamed": renamed, "joe": man.get("joe", ""),
            "made": man.get("made", ""), "keys": bool(man.get("keys"))}
