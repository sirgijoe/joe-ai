"""Household profiles: each person on a shared PC gets their own Joe.

A profile is its own settings folder (settings, keys, chats index, agents, memory, phone link, the
window's sign-ins, the night shift) and its own workspace folder (Inbox, Output, Missions...). The
big shared things stay shared: Ollama and ComfyUI models, the voice add-on and the program itself.

Where:  <Joe's settings folder>/profiles/<id>/        the profile's settings
        Documents/Joe-ai - <Name>/                   the profile's workspace (Setup can move it)
        <Joe's settings folder>/profiles.json         the list of people, and who used Joe last
Nothing changes for a PC with no profiles: Joe starts exactly as before. The original settings and
workspace are "Main" (id "main"), and stay as they are.

Choosing: `--profile NAME` (or the JOE_PROFILE environment variable) picks one. With no choice and at
least one profile made, Joe asks "Who's using Joe?" in a small window, and starts with who was last.
Each profile gets its own window and its own port, so two people can be signed in side by side
(fast user switching), and a profile's night shift is its own entry in the computer's scheduler.

Standard library only. Profiles are off in Portable Joe (the drive is one person's Joe).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ENV = "JOE_PROFILE"
MAIN = "main"                 # the original settings and workspace
FILE = "profiles.json"
MAX_PROFILES = 12
MAX_NAME = 30


def _portable() -> bool:
    from . import portable
    return portable.active()


def slug(name: str) -> str:
    """'Sam R.' -> 'sam-r': letters, digits and dashes only, so it is safe as a folder name on every system."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return s[:40].strip("-")


def base_dir() -> Path:
    """The settings folder Joe uses without profiles."""
    from .system import base_config_dir
    return base_config_dir()


def current() -> str:
    """The profile this Joe was started for ('' = Main, or no profiles at all)."""
    if _portable():
        return ""
    v = (os.environ.get(ENV) or "").strip().lower()
    return "" if v in ("", MAIN) else slug(v)


def chosen() -> bool:
    """Has this start already picked who is using Joe (a profile, or Main on purpose)?"""
    return ENV in os.environ


def profile_dir(pid: str) -> Path:
    return base_dir() / "profiles" / pid


def _read() -> dict:
    try:
        d = json.loads((base_dir() / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def _write(d: dict) -> None:
    from .fsutil import atomic_write_text
    base_dir().mkdir(parents=True, exist_ok=True)
    atomic_write_text(base_dir() / FILE, json.dumps(d, indent=2, ensure_ascii=False))


def people() -> list[dict]:
    """[{"id", "name"}] for every profile made (Main isn't listed: it is always there)."""
    out = []
    for e in _read().get("profiles") or []:
        if isinstance(e, dict) and isinstance(e.get("id"), str) and slug(e["id"]) == e["id"] and e["id"] != MAIN:
            out.append({"id": e["id"], "name": str(e.get("name") or e["id"])[:MAX_NAME]})
    return out


def display(pid: str) -> str:
    """The name to show for a profile id ('' / 'main' = Main)."""
    if pid in ("", MAIN):
        return str(_read().get("main_name") or "Main")[:MAX_NAME]
    return next((p["name"] for p in people() if p["id"] == pid), pid)


def workspace_for(pid: str) -> Path:
    from .system import documents_dir
    return documents_dir() / f"Joe-ai - {display(pid)}"


def add(name: str) -> dict:
    """Make a profile. {"ok": True, "id", "name", "folder", "workspace"} or {"ok": False, "error"}."""
    if _portable():
        return {"ok": False, "error": "Profiles aren't used in Portable Joe: the drive is one person's Joe."}
    name = " ".join((name or "").split())[:MAX_NAME]
    pid = slug(name)
    if not pid:
        return {"ok": False, "error": "Type a name (letters or numbers)."}
    if pid == MAIN:
        return {"ok": False, "error": "\"Main\" is the original Joe on this PC. Pick another name."}
    d = _read()
    have = people()
    if any(p["id"] == pid for p in have):
        return {"ok": False, "error": f"There is already a profile called {display(pid)}."}
    if len(have) >= MAX_PROFILES:
        return {"ok": False, "error": f"That's {MAX_PROFILES} profiles, the most Joe keeps on one PC."}
    folder = profile_dir(pid)
    folder.mkdir(parents=True, exist_ok=True)
    have.append({"id": pid, "name": name})
    d["profiles"] = have
    _write(d)
    return {"ok": True, "id": pid, "name": name, "folder": str(folder), "workspace": str(workspace_for(pid))}


def remove(pid: str) -> dict:
    """Take a profile off the list. Its settings and its workspace are NOT deleted: the person's files
    stay where they are, and the same name brings them all back."""
    pid = slug(pid)
    d = _read()
    have = people()
    if not any(p["id"] == pid for p in have):
        return {"ok": False, "error": "There is no such profile."}
    d["profiles"] = [p for p in have if p["id"] != pid]
    if d.get("last") == pid:
        d["last"] = MAIN
    _write(d)
    return {"ok": True, "kept": str(profile_dir(pid))}


def remember(pid: str) -> None:
    d = _read()
    d["last"] = pid or MAIN
    try:
        _write(d)
    except OSError:
        pass


def last() -> str:
    v = str(_read().get("last") or MAIN)
    return v if v == MAIN or any(p["id"] == v for p in people()) else MAIN


def use(pid: str) -> None:
    """Make this process Joe for `pid` ('' / 'main' = the original)."""
    os.environ[ENV] = pid or MAIN


def command_args() -> list[str]:
    """Arguments that start Joe for the same person later (the night shift, RESTART JOE)."""
    if _portable():
        return []
    if current():
        return ["--profile", current()]
    return ["--profile", MAIN] if people() else []


def take_arg(argv: list[str]) -> list[str]:
    """Pull `--profile NAME` (or `--profile=NAME`) out of the command line, use it, return the rest."""
    out, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--profile" and i + 1 < len(argv):
            use(slug(argv[i + 1]) or MAIN)
            i += 2
            continue
        if a.startswith("--profile="):
            use(slug(a.split("=", 1)[1]) or MAIN)
            i += 1
            continue
        out.append(a)
        i += 1
    return out


def pick_for_launch(chooser=None) -> str:
    """Joe's window is opening: decide who is using him. Returns the profile id ('' = Main).
    Nothing to decide (no profiles, Portable Joe, or already chosen on the command line): unchanged."""
    if _portable() or chosen() or not people():
        return current()
    options = [{"id": MAIN, "name": display(MAIN)}] + people()
    try:
        pid = (chooser or tk_chooser)(options, last())
    except Exception:                                   # noqa: BLE001 (no window system: carry on as before)
        pid = ""
    ids = {o["id"] for o in options}
    pid = pid if pid in ids else last()
    use(pid)
    remember(pid)
    return current()


def tk_chooser(options: list[dict], preselect: str) -> str:
    """A small "Who's using Joe?" window (tkinter comes with Python on Windows and Mac). Closing it
    carries on with whoever used Joe last."""
    import tkinter as tk
    root = tk.Tk()
    root.title("Joe")
    root.resizable(False, False)
    got = {"id": preselect}
    tk.Label(root, text="Who's using Joe?", font=("Segoe UI", 14, "bold"), padx=24, pady=12).pack()

    def pick(pid):
        got["id"] = pid
        root.destroy()
    for o in options:
        b = tk.Button(root, text=o["name"], width=26, pady=6, command=lambda pid=o["id"]: pick(pid))
        b.pack(padx=24, pady=3)
        if o["id"] == preselect:
            b.focus_set()
    tk.Label(root, text="", pady=4).pack()
    root.mainloop()
    return got["id"]


def summary() -> dict:
    """For Setup: who this Joe is, and everyone on the list."""
    me = current() or MAIN
    rows = [{"id": MAIN, "name": display(MAIN), "main": True, "me": me == MAIN,
             "workspace": str(_main_workspace())}]
    rows += [{"id": p["id"], "name": p["name"], "main": False, "me": me == p["id"],
              "workspace": str(workspace_for(p["id"]))} for p in people()]
    return {"ok": True, "enabled": not _portable(), "me": me, "name": display(me), "people": rows}


def _main_workspace() -> Path:
    from .system import documents_dir
    return documents_dir() / "Joe-ai"


def open_window_for(pid: str) -> dict:
    """Start (or reopen) another person's Joe in its own window. Each profile has its own port, so both can run."""
    pid = slug(pid) or MAIN
    if _portable():
        return {"ok": False, "error": "Profiles aren't used in Portable Joe."}
    if pid != MAIN and not any(p["id"] == pid for p in people()):
        return {"ok": False, "error": "There is no such profile."}
    if pid == (current() or MAIN):
        return {"ok": False, "error": "That's this Joe already."}
    from .system import joe_command, popen_detached
    try:
        popen_detached(joe_command("", console=False, who=["--profile", pid]))
    except OSError as e:
        return {"ok": False, "error": f"Couldn't start that Joe: {e}"}
    return {"ok": True, "say": f"Opening {display(pid)}'s Joe in a new window."}
