"""A help file for getting support: one zip someone can send when Joe misbehaves.

What goes in: Joe's version and how he was installed, the system (OS, Python, graphics, memory),
System check's findings, settings with every key/topic/password blanked, and the end of each
log. What never goes in: your Inbox and Output files, chats, recordings, voices, missions.
Your home folder and user name are replaced with ~ and <user> everywhere. A README inside says
all this, so people can look before they send it.
"""
from __future__ import annotations

import getpass
import json
import platform
import re
import sys
import zipfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from . import __version__

LOG_TAIL = 300_000                  # bytes kept from the end of each log
SECRET = re.compile(r"(?<!ptt_)key$|token|topic|password|secret|_start$|start_command", re.I)   # not the push-to-talk key
_USERINFO = re.compile(r"(\w+://)[^/@\s:]+(?::[^/@\s]*)?@")             # https://user:pass@host -> https://host

README = """JOE HELP FILE
=============
Made {when} by Joe {version}. Send this zip to whoever is helping you.

Inside:
  about.txt          Joe's version, how he was installed, the system, graphics, memory
  system-check.json  what System check (Setup) found: programs, models, problems
  settings.json      your settings, with every key, topic and password replaced by (hidden)
  logs/              the last part of each log Joe keeps

Never inside: your Inbox or Output files, chats, recordings, voices or missions.
Your home folder is shown as ~ and your user name as <user>.
The logs can mention task names and file names. Open the files and check before sending.
"""


def _scrub_text(text: str) -> str:
    home = str(Path.home())
    for h in {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}:
        if h and len(h) > 3:
            text = text.replace(h, "~")
    try:
        user = getpass.getuser()
    except Exception:                                  # noqa: BLE001 (no user name: nothing to hide)
        user = ""
    if user and len(user) >= 3:                    # whole words only, so "joe" doesn't eat every "Joe"
        text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(user)}(?![A-Za-z0-9])", "<user>", text, flags=re.I)
    return _USERINFO.sub(r"\1", text)


def _scrub_settings(d):
    if isinstance(d, dict):
        return {k: ("(hidden)" if SECRET.search(k) and v not in ("", None, 0, False)
                    and not isinstance(v, (dict, list))
                    else _USERINFO.sub(r"\1", v) if isinstance(v, str) else _scrub_settings(v))
                for k, v in d.items()}
    if isinstance(d, list):
        return [_scrub_settings(x) for x in d]
    return d


def _tail(p: Path) -> str:
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - LOG_TAIL))
            data = f.read()
    except OSError:
        return ""
    text = data.decode("utf-8", "replace")
    return ("(earlier lines left out)\n" + text.split("\n", 1)[-1]) if size > LOG_TAIL else text


def about(settings=None) -> str:
    from . import hardware
    from .system import pretty_name
    from .update import install_kind
    g = hardware.gpu()
    lines = [f"Joe {__version__} ({install_kind()})",
             f"System: {pretty_name()} ({platform.platform()}, {platform.machine()})",
             f"Python: {sys.version.split()[0]}",
             f"Graphics: {g['name'] + ' (' + str(g.get('vendor')) + ', ' + str(hardware.vram_total_gb()) + ' GB)' if g else 'none found'}",
             f"Memory: {hardware.ram_total_gb()} GB"]
    if g and hardware.gpu_advice(g):
        lines.append("Note: " + hardware.gpu_advice(g))
    return "\n".join(lines) + "\n"


def make_help_file(settings, sb, check: dict | None = None, out_dir: Path | None = None,
                   debug: list | None = None) -> Path:
    """Write Joe-help-<date>.zip (in Output unless out_dir is given) and return it."""
    from .storage import log_files
    now = datetime.now()
    dest = (out_dir or sb.output) / f"Joe-help-{now:%Y-%m-%d-%H%M}.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README.format(when=f"{now:%Y-%m-%d %H:%M}", version=__version__))
        z.writestr("about.txt", _scrub_text(about(settings)))
        if check is not None:
            z.writestr("system-check.json", _scrub_text(json.dumps(check, indent=2, default=str)))
        try:
            z.writestr("settings.json", _scrub_text(json.dumps(_scrub_settings(asdict(settings)), indent=2)))
        except TypeError:
            pass
        if debug:                                  # timing lines kept out of the window's log
            z.writestr("logs/debug.txt", _scrub_text("\n".join(debug)))
        seen = set()
        for p in log_files(sb):
            if p.is_file() and p.name not in seen:
                seen.add(p.name)
                z.writestr(f"logs/{p.name}", _scrub_text(_tail(p)))
    return dest
