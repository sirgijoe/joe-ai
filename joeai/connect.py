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


def _home() -> Path:
    return Path(os.environ.get("JOE_HOME_OVERRIDE") or Path.home())


def app_paths() -> dict[str, tuple[str, Path]]:
    """app id -> (name shown, settings file)."""
    h = _home()
    if WINDOWS:
        appdata = Path(os.environ.get("APPDATA") or h / "AppData" / "Roaming")
        claude = appdata / "Claude" / "claude_desktop_config.json"
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
    }


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
        installed = p.parent.exists()
        out.append({"id": app_id, "name": name, "installed": installed, "file": str(p),
                    "connected": bool(d and isinstance(d.get("mcpServers"), dict) and ENTRY in d["mcpServers"]),
                    "readable": d is not None})
    return out


def connect(app_id: str, entry: dict) -> dict:
    apps = app_paths()
    if app_id not in apps:
        return {"ok": False, "error": "Joe doesn't know that app."}
    name, p = apps[app_id]
    if not p.parent.exists():
        return {"ok": False, "error": f"{name} doesn't seem to be installed on this PC (no {p.parent})."}
    if p.suffix == ".toml":
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        if p.exists():
            shutil.copy2(p, p.with_name(p.name + ".before-joe"))
        body = _toml_strip_joe(text)
        _write(p, (body + "\n" if body.strip() else "") + _toml_joe(entry))
        return {"ok": True, "say": f"Joe is connected to {name}. Restart it; in ChatGPT, turn on Settings > "
                                   "Features > Developer mode if Joe doesn't show under Settings > MCP servers."}
    d = _read(p)
    if d is None:
        return {"ok": False, "error": f"{name}'s settings file isn't something Joe can read safely, so he left it "
                                      f"alone. Use SHOW THE CONNECTOR LINES and paste them in by hand."}
    if p.exists():
        shutil.copy2(p, p.with_name(p.name + ".before-joe"))
    servers = d.get("mcpServers") if isinstance(d.get("mcpServers"), dict) else {}
    servers[ENTRY] = entry
    d["mcpServers"] = servers
    _write(p, json.dumps(d, indent=2))
    return {"ok": True, "say": f"Joe is connected to {name}. Restart {name} to see him."}


def disconnect(app_id: str) -> dict:
    apps = app_paths()
    if app_id not in apps:
        return {"ok": False, "error": "Joe doesn't know that app."}
    name, p = apps[app_id]
    if p.suffix == ".toml":
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        if not _toml_has_joe(text):
            return {"ok": True, "say": f"Joe wasn't connected to {name}."}
        shutil.copy2(p, p.with_name(p.name + ".before-joe"))
        _write(p, _toml_strip_joe(text))
        return {"ok": True, "say": f"Joe is disconnected from {name}. Restart it."}
    d = _read(p)
    if not d or not isinstance(d.get("mcpServers"), dict) or ENTRY not in d["mcpServers"]:
        return {"ok": True, "say": f"Joe wasn't connected to {name}."}
    shutil.copy2(p, p.with_name(p.name + ".before-joe"))
    del d["mcpServers"][ENTRY]
    _write(p, json.dumps(d, indent=2))
    return {"ok": True, "say": f"Joe is disconnected from {name}. Restart {name}."}


def _write(p: Path, text: str) -> None:
    tmp = p.with_name(p.name + ".joe-tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)
