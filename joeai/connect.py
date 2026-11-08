"""One-click CONNECT: Joe writes his connector entry into an AI app's own settings file.

Setup > General > USE JOE FROM ANOTHER AI APP lists the apps Joe knows. CONNECT adds (or
updates) a "joe" entry under mcpServers in that app's settings file; DISCONNECT removes it.
Joe only ever touches his own entry: the rest of the file is kept as it is, a copy of the old
file is saved next to it first (<name>.before-joe), and a file Joe can't read as JSON is left
alone. The app must be restarted to see the change.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from .system import MAC, WINDOWS

ENTRY = "joe"


def _backup(p) -> None:
    """Keep the app's settings as they were before Joe ever touched them (the first copy wins)."""
    b = p.with_name(p.name + ".before-joe")
    if not b.exists():
        shutil.copy2(p, b)


def _home() -> Path:
    return Path(os.environ.get("JOE_HOME_OVERRIDE") or Path.home())


def claude_windows_files() -> list[Path]:
    """Claude Desktop's settings file(s) on Windows, the one the app really reads first.
    The installer from claude.ai (and the Store / WinGet) installs it as an MSIX package, and
    Windows quietly keeps its AppData\\Roaming\\Claude inside
    %LOCALAPPDATA%\\Packages\\Claude_<id>\\LocalCache\\Roaming\\Claude. Older installs use
    %APPDATA%\\Claude itself."""
    h = _home()
    local = Path(os.environ.get("LOCALAPPDATA") or h / "AppData" / "Local")
    appdata = Path(os.environ.get("APPDATA") or h / "AppData" / "Roaming")
    msix = []
    try:
        msix = sorted((d / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
                       for d in (local / "Packages").glob("Claude_*") if d.is_dir()),
                      key=lambda f: -(f.parent.stat().st_mtime if f.parent.exists() else 0))
    except OSError:
        msix = []
    classic = appdata / "Claude" / "claude_desktop_config.json"
    # Newer Claude Desktop installs can keep their data outside the package (it asks once):
    # %LOCALAPPDATA%\Claude-Data\claude_<id>\claude_desktop_config.json. When that exists, it's the
    # one the app reads, so it comes first.
    outside = []
    try:
        outside = sorted((d / "claude_desktop_config.json" for d in (local / "Claude-Data").glob("[Cc]laude_*")
                          if d.is_dir()), key=lambda f: -(f.stat().st_mtime if f.exists() else 0))
    except OSError:
        outside = []
    outside = [f for f in outside if f.exists()]
    have = [f for f in msix if f.parent.exists()] or msix
    return outside + have + [classic]


def app_paths() -> dict[str, tuple[str, Path]]:
    """app id -> (name shown, settings file)."""
    h = _home()
    if WINDOWS:
        claude = claude_windows_files()[0]
    elif MAC:
        claude = h / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        claude = h / ".config" / "Claude" / "claude_desktop_config.json"
    return {
        "claude": ("Claude Desktop", claude),
        "gemini": ("Gemini CLI", h / ".gemini" / "settings.json"),
        "cursor": ("Cursor", h / ".cursor" / "mcp.json"),
        "lmstudio": ("LM Studio", h / ".lmstudio" / "mcp.json"),
        # ChatGPT's desktop app shares its MCP servers with Codex (~/.codex/config.toml, TOML)
        "chatgpt": ("ChatGPT desktop (and Codex)", h / ".codex" / "config.toml"),
        "vscode": ("VS Code (Copilot)", _vscode_file(h)),
    }


def _vscode_file(h: Path) -> Path:
    if WINDOWS:
        return Path(os.environ.get("APPDATA") or h / "AppData" / "Roaming") / "Code" / "User" / "mcp.json"
    if MAC:
        return h / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    return h / ".config" / "Code" / "User" / "mcp.json"


def _servers_key(app_id: str) -> str:
    return "servers" if app_id == "vscode" else "mcpServers"


# --------------------------------------------------------------------------- one-click: the app adds Joe itself
def deeplink(app_id: str, entry: dict) -> str:
    """The app's own install link (it shows its own "add Joe?" box), or '' when it has none."""
    import base64
    from urllib.parse import quote
    if app_id == "cursor":
        cfg = base64.b64encode(json.dumps(entry, separators=(",", ":")).encode()).decode()
        return f"cursor://anysphere.cursor-deeplink/mcp/install?name={ENTRY}&config={quote(cfg)}"
    if app_id == "lmstudio":
        cfg = base64.b64encode(json.dumps(entry, separators=(",", ":")).encode()).decode()
        return f"lmstudio://add_mcp?name={ENTRY}&config={quote(cfg)}"
    if app_id == "vscode":
        return "vscode:mcp/install?" + quote(json.dumps({"name": ENTRY, "type": "stdio", **entry}, separators=(",", ":")))
    return ""


def open_link(url: str) -> bool:
    import subprocess
    try:
        if WINDOWS:
            os.startfile(url)                            # noqa: S606 (the app's own registered link)
        elif MAC:
            subprocess.Popen(["open", url])
        else:
            subprocess.Popen(["xdg-open", url])
        return True
    except (OSError, AttributeError):
        return False


def gemini_add(entry: dict, run=None) -> str:
    """Gemini CLI's own command: gemini mcp add -s user joe <command> <args...>. '' = done."""
    import subprocess
    exe = shutil.which("gemini")
    if not exe:
        return "no gemini command"
    run = run or subprocess.run
    try:
        run([exe, "mcp", "remove", "-s", "user", ENTRY], capture_output=True, text=True, timeout=60)
        r = run([exe, "mcp", "add", "-s", "user", ENTRY, entry["command"], *entry.get("args", [])],
                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)
    return "" if r.returncode == 0 else ((r.stderr or r.stdout or "").strip()[:200] or "gemini mcp add failed")


def mcpb_bundle(entry: dict, dest: Path, version: str) -> Path:
    """A Claude Desktop extension (.mcpb) for this PC's Joe: double-click it and Claude Desktop shows
    its own Install box, no settings files involved. It holds only a manifest and a 3-line starter
    that runs this PC's Joe in connector mode (so it's made fresh on each PC, never shared)."""
    import zipfile
    v = re.match(r"\d+\.\d+\.\d+", version)
    starter = ("# Starts this PC's Joe as a connector for Claude Desktop (made by Joe's CONNECT).\n"
               "import os, runpy, sys\n"
               f"sys.argv = [{json.dumps(entry['args'][0] if entry.get('args') else '')}] + {json.dumps(entry.get('args', [])[1:])}\n"
               f"os.environ.update({json.dumps(entry.get('env', {}))})\n"
               "runpy.run_path(sys.argv[0], run_name='__main__')\n")
    manifest = {
        "manifest_version": "0.3", "name": "joe-ai", "display_name": "Joe (your local AI helper)",
        "version": v.group(0) if v else "1.0.0",
        "description": "Joe works on this PC with local AI: queue his work, make pictures, run his tools on "
                       "files in his Inbox, see his status and results. Free and open source (GPL-3.0).",
        "author": {"name": "Joe (joe-ai)", "url": "https://github.com/sirgijoe/joe-ai"},
        "homepage": "https://github.com/sirgijoe/joe-ai", "license": "GPL-3.0-or-later",
        "server": {"type": "python", "entry_point": "server/joe_connector.py",
                   "mcp_config": {"command": entry["command"], "args": ["${__dirname}/server/joe_connector.py"],
                                  "env": entry.get("env", {})}},
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("server/joe_connector.py", starter)
    return dest


# ---- TOML (ChatGPT desktop / Codex): only Joe's own [mcp_servers.joe] tables are touched.
_TOML_HEAD = re.compile(r"^\s*\[+\s*([^\]]+?)\s*\]+\s*(#.*)?$")


def _toml_strip_joe(text: str) -> str:
    out, skip = [], False
    for line in text.splitlines():
        m = _TOML_HEAD.match(line)
        if m:
            name = m.group(1).replace('"', "").replace("'", "")
            skip = name == f"mcp_servers.{ENTRY}" or name.startswith(f"mcp_servers.{ENTRY}.")
        if not skip:
            out.append(line)
    return "\n".join(out).rstrip() + ("\n" if out else "")


def _toml_str(v: str) -> str:
    return json.dumps(v)          # a JSON string is a valid TOML basic string


def _toml_joe(entry: dict) -> str:
    lines = [f"[mcp_servers.{ENTRY}]", f"command = {_toml_str(entry['command'])}",
             "args = [" + ", ".join(_toml_str(a) for a in entry.get("args", [])) + "]"]
    if entry.get("env"):
        lines += ["", f"[mcp_servers.{ENTRY}.env]"] + [f"{k} = {_toml_str(v)}" for k, v in entry["env"].items()]
    return "\n".join(lines) + "\n"


def _toml_has_joe(text: str) -> bool:
    return any((m := _TOML_HEAD.match(ln)) and m.group(1).replace('"', "") == f"mcp_servers.{ENTRY}"
               for ln in text.splitlines())


def _read(p: Path) -> dict | None:
    """The file's JSON ({} if it doesn't exist yet), or None if it isn't readable JSON."""
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig") or "{}")
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _installed(app_id: str, p: Path) -> bool:
    if p.parent.exists():
        return True
    if app_id == "claude" and WINDOWS and "Packages" in p.parts:   # MSIX app, settings folder not made yet
        try:
            return p.parents[3].is_dir()
        except (IndexError, OSError):
            return False
    return False


def status() -> list[dict]:
    out = []
    for app_id, (name, p) in app_paths().items():
        if p.suffix == ".toml":
            try:
                text = p.read_text(encoding="utf-8") if p.exists() else ""
            except OSError:
                text = ""
            out.append({"id": app_id, "name": name, "installed": p.parent.exists(), "file": str(p),
                        "connected": _toml_has_joe(text), "readable": True})
            continue
        d = _read(p)
        installed = _installed(app_id, p)
        key = _servers_key(app_id)
        got = (d or {}).get(key) if isinstance((d or {}).get(key), dict) else {}
        mine = got.get(ENTRY) if isinstance(got.get(ENTRY), dict) else None
        out.append({"id": app_id, "name": name, "installed": installed, "file": str(p),
                    "connected": mine is not None, "readable": d is not None,
                    "points_to": " ".join([str(mine.get("command", ""))] + [str(x) for x in mine.get("args", [])])
                    if mine else "", "link": bool(deeplink(app_id, {"command": "x"}))})
    return out


def entry_matches(have: str, entry: dict) -> bool:
    """Does the app start THIS Joe (same Python and same Joe.pyw)?"""
    want = " ".join([str(entry.get("command", ""))] + [str(x) for x in entry.get("args", [])])
    norm = lambda t: t.replace("\\", "/").lower().strip()      # noqa: E731
    return norm(have) == norm(want)


def check(entry: dict, connected_before: list[str]) -> list[dict]:
    """Problems for System check: an app Joe was connected to that lost his entry (it moved or reset
    its settings), or one that starts Joe from an old place (folder moved, Python updated, other copy)."""
    out = []
    for st in status():
        if st["id"] not in connected_before or not st["installed"]:
            continue
        if not st["connected"]:
            out.append({"app": st["id"], "name": st["name"], "why": "missing"})
        elif st["id"] != "chatgpt" and not entry_matches(st["points_to"], entry):
            out.append({"app": st["id"], "name": st["name"], "why": "old", "points_to": st["points_to"]})
    return out


# The program each app runs as, to check it's closed before Joe touches its settings: an app that's
# open keeps its own copy of the settings and writes it back later, wiping out Joe's entry.
PROCESSES = {
    "claude": {"win": ("claude.exe",), "mac": ("Claude",), "linux": ("claude-desktop", "Claude")},
    "cursor": {"win": ("Cursor.exe",), "mac": ("Cursor",), "linux": ("cursor", "Cursor")},
    "lmstudio": {"win": ("LM Studio.exe",), "mac": ("LM Studio",), "linux": ("lm-studio", "LM Studio")},
    "chatgpt": {"win": ("ChatGPT.exe", "Codex.exe"), "mac": ("ChatGPT", "Codex"), "linux": ("chatgpt", "codex")},
}
CLOSE_HOW = {
    "claude": "Claude Desktop keeps running in the tray when its window is closed: open Task Manager "
              "(Ctrl+Shift+Esc), right-click every \"Claude\" under Processes and pick End task.",
}


def app_running(app_id: str, run=None) -> bool:
    """True when the app's program is running (False when Joe can't tell)."""
    import subprocess
    names = PROCESSES.get(app_id)
    if not names:
        return False                                  # Gemini CLI: a terminal program, nothing to close
    run = run or subprocess.run
    try:
        if WINDOWS:
            from .system import no_window_flags
            r = run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=15,
                    creationflags=no_window_flags())
            have = {line.split('","')[0].strip('"').lower() for line in (r.stdout or "").splitlines() if line}
            return any(n.lower() in have for n in names["win"])
        for n in names["mac" if MAC else "linux"]:
            r = run(["pgrep", "-x", n], capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and (r.stdout or "").strip():
                return True
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return False


def closed_first(app_id: str, name: str) -> dict | None:
    """None when the app is closed; else the plain-words 'close it first' answer."""
    if not app_running(app_id):
        return None
    how = CLOSE_HOW.get(app_id, f"Quit {name} completely (not just its window), then try again.") if WINDOWS else \
        f"Quit {name} completely (Cmd+Q on a Mac), then try again."
    return {"ok": False, "running": True,
            "error": f"{name} is still running. Close it first: while it's open it keeps its own copy of its "
                     f"settings and would write over Joe's change. {how}"}


def connect(app_id: str, entry: dict) -> dict:
    apps = app_paths()
    if app_id not in apps:
        return {"ok": False, "error": "Joe doesn't know that app."}
    name, p = apps[app_id]
    if (busy := closed_first(app_id, name)) is not None:
        return busy
    if not _installed(app_id, p):
        return {"ok": False, "error": f"{name} doesn't seem to be installed on this PC (no {p.parent})."}
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix == ".toml":
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        if p.exists():
            _backup(p)
        body = _toml_strip_joe(text)
        _write(p, (body + "\n" if body.strip() else "") + _toml_joe(entry))
        return {"ok": True, "say": f"Joe is connected to {name}. Restart it; in ChatGPT, turn on Settings > "
                                   "Features > Developer mode if Joe doesn't show under Settings > MCP servers."}
    d = _read(p)
    if d is None:
        return {"ok": False, "error": f"{name}'s settings file isn't something Joe can read safely, so he left it "
                                      f"alone. Use SHOW THE CONNECTOR LINES and paste them in by hand."}
    if p.exists():
        _backup(p)
    key = _servers_key(app_id)
    servers = d.get(key) if isinstance(d.get(key), dict) else {}
    servers[ENTRY] = {"type": "stdio", **entry} if app_id == "vscode" else entry
    d[key] = servers
    _write(p, json.dumps(d, indent=2))
    if app_id == "claude" and WINDOWS:                # MSIX + old-style copies: keep both in step
        for other in claude_windows_files():
            if other != p and other.parent.exists():
                od = _read(other)
                if od is not None:
                    if other.exists():
                        _backup(other)
                    osv = od.get("mcpServers") if isinstance(od.get("mcpServers"), dict) else {}
                    osv[ENTRY] = entry
                    od["mcpServers"] = osv
                    _write(other, json.dumps(od, indent=2))
    return {"ok": True, "say": f"Joe is connected to {name}. Open {name} now and start a new chat to use him."}


def disconnect(app_id: str, force: bool = False) -> dict:
    apps = app_paths()
    if app_id not in apps:
        return {"ok": False, "error": "Joe doesn't know that app."}
    name, p = apps[app_id]
    if not force and (busy := closed_first(app_id, name)) is not None:
        return busy
    if p.suffix == ".toml":
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        if not _toml_has_joe(text):
            return {"ok": True, "say": f"Joe wasn't connected to {name}."}
        _backup(p)
        _write(p, _toml_strip_joe(text))
        return {"ok": True, "say": f"Joe is disconnected from {name}. Restart it."}
    d = _read(p)
    key = _servers_key(app_id)
    if not d or not isinstance(d.get(key), dict) or ENTRY not in d[key]:
        return {"ok": True, "say": f"Joe wasn't connected to {name}."}
    _backup(p)
    del d[key][ENTRY]
    _write(p, json.dumps(d, indent=2))
    if app_id == "claude" and WINDOWS:
        for other in claude_windows_files():
            od = _read(other) if other != p else None
            if od and isinstance(od.get("mcpServers"), dict) and ENTRY in od["mcpServers"]:
                _backup(other)
                del od["mcpServers"][ENTRY]
                _write(other, json.dumps(od, indent=2))
    return {"ok": True, "say": f"Joe is disconnected from {name}. Restart {name}."}


def _write(p: Path, text: str) -> None:
    tmp = p.with_name(p.name + ".joe-tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)


def disconnect_all() -> int:
    """Uninstalling Joe: take his entry out of every app, so none keeps trying to start a Joe
    that's gone. Returns how many were removed."""
    n = 0
    for st in status():
        if st["connected"]:
            try:
                if disconnect(st["id"], force=True).get("ok"):
                    n += 1
            except OSError:
                continue
    return n
