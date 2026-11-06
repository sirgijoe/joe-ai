"""Joe as an MCP connector (local, stdio) for Claude Desktop and other MCP apps.

    python -m joeai mcp

The app starts this itself (Setup > General > Use Joe from another AI app shows the lines to
paste into its settings). It speaks JSON-RPC 2.0, one message per line, on stdin/stdout. What
the other app can do, and nothing more:
  - see Joe's status (is the window open, Ollama/ComfyUI up, what's running, what's waiting)
  - read the mission format, the last report, the end of the log, the files Joe made
  - check a mission (no changes) and queue one (a file in Missions/Queue; Joe runs it when his
    window is open, or at the night-shift time)
It can't run programs, install anything, change settings, or read or write outside Joe's folder.
Standard library only; no network.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from . import __version__

PROTOCOL = "2025-06-18"
MAX_READ = 200_000                       # characters returned from one file

TOOLS = [
    {"name": "joe_status",
     "description": "Joe's status: whether his window is open, whether Ollama (writing) and ComfyUI "
                    "(pictures/video) are up, what he's doing now, and the missions waiting in his queue.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "joe_mission_format",
     "description": "The exact mission format Joe understands, with the tools on this PC. Read this "
                    "before writing a mission.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "joe_check_mission",
     "description": "Check a mission block for mistakes without running it. Returns the tasks Joe "
                    "would do, or the problem to fix.",
     "inputSchema": {"type": "object", "properties": {"mission": {"type": "string"}},
                     "required": ["mission"]}},
    {"name": "joe_queue_mission",
     "description": "Give Joe a mission: it's checked, then saved in his queue (or for tonight's night "
                    "shift). He runs it when his window is open. Nothing runs if the check fails.",
     "inputSchema": {"type": "object", "properties": {
         "mission": {"type": "string"},
         "name": {"type": "string", "description": "short file name, e.g. product-blurbs"},
         "tonight": {"type": "boolean", "description": "true = wait for the night-shift time"}},
         "required": ["mission"]}},
    {"name": "joe_report",
     "description": "Joe's last report (what finished, what failed, what's left).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "joe_log",
     "description": "The end of Joe's work log.",
     "inputSchema": {"type": "object", "properties": {"lines": {"type": "integer", "minimum": 1,
                                                                "maximum": 2000}}}},
    {"name": "joe_list_files",
     "description": "Files Joe made, in his Output folder (or a folder inside it).",
     "inputSchema": {"type": "object", "properties": {"folder": {"type": "string"}}}},
    {"name": "joe_read_file",
     "description": "Read a text file Joe made (inside his Output folder).",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}},
                     "required": ["path"]}},
]
TEXT_EXT = {".md", ".txt", ".csv", ".json", ".html", ".py", ".js", ".css", ".srt", ".vtt", ".log"}


class Joe:
    """Everything the connector does, on files in Joe's folder (no window needed)."""

    def __init__(self, settings=None):
        from .config import Settings
        from .sandbox import Sandbox
        self.s = settings or Settings.load()
        self.sb = Sandbox(self.s.workspace_path).ensure()

    # -- tools --------------------------------------------------------------
    def status(self) -> str:
        from .services import ServiceManager
        lines = [f"Joe {__version__}. Workspace: Joe's folder (Missions, Output, Inbox)."]
        lines.append("Joe's window: " + ("open" if _window_open() else
                                         "closed (queued missions wait until it opens or the night shift starts)"))
        try:
            st = ServiceManager(self.s, log=lambda *_: None).status()
            lines.append(f"Ollama (writing): {'up' if st['ollama'] else 'not running'}; "
                         f"ComfyUI (pictures/video): {'up' if st['comfyui'] else 'not running'}")
        except Exception:                   # noqa: BLE001
            pass
        prog = self.sb.output / "_progress.txt"
        if prog.exists() and time.time() - prog.stat().st_mtime < 900:
            lines.append("Working on: " + prog.read_text(encoding="utf-8", errors="replace").strip()[:300])
        for label, folder in (("Waiting in the queue", self.sb.missions / "Queue"),
                              ("Waiting for the night shift", self.sb.missions / "Tonight")):
            names = _mission_files(folder)
            lines.append(f"{label}: " + (", ".join(names) if names else "nothing"))
        probs = _mission_files(self.sb.missions / "Queue" / "problems")
        if probs:
            lines.append("Queue files with problems (see the .problem.txt next to each): " + ", ".join(probs[-5:]))
        if self.s.schedule.enabled:
            lines.append(f"Night shift: on, starts at {self.s.schedule.time}")
        return "\n".join(lines)

    def mission_format(self) -> str:
        from .bigger import EXTRA_KEYS
        from .describe import planner_text
        return planner_text().replace("Reply with ONLY the mission block,\nnothing before or after it.",
                                      "").strip() + "\n\n" + EXTRA_KEYS

    def check(self, text: str) -> tuple[bool, str]:
        from .describe import extract_block
        from .mission import MissionError, parse
        from .sandbox import SandboxError
        block = extract_block(text) or text
        try:
            m = parse(block)
            for j in m.jobs:
                self.sb.resolve(j.save)
        except (MissionError, SandboxError) as e:
            return False, f"Problem: {e}"
        out = [f"OK: {len(m.jobs)} task(s)" + (f" for project {m.project}" if m.project else "")]
        for j in m.jobs:
            n = len(j.part_prompts) or j.parts * j.part_size
            shape = (f"{n} prompt(s) x {j.variants}" if j.media else
                     f"{j.parts} guided parts" if j.guided else f"{j.total_items} items")
            out.append(f"- [{'csv' if j.is_csv else j.type}] {j.name}: {shape} -> Output/{j.save}")
        return True, "\n".join(out)

    def queue(self, text: str, name: str = "", tonight: bool = False) -> str:
        from .describe import extract_block
        from .fsutil import atomic_write_text
        from .mission import slug
        ok, msg = self.check(text)
        if not ok:
            return msg + "\nNothing was queued. Fix the mission and try again."
        block = extract_block(text) or text
        if not name:
            from .mission import parse
            jobs = parse(block).jobs
            name = jobs[0].name if jobs else ""
        folder = self.sb.missions / ("Tonight" if tonight else "Queue")
        folder.mkdir(parents=True, exist_ok=True)
        stem = (slug(name) or "mission")[:40] + datetime.now().strftime("_%Y%m%d_%H%M%S")
        target = folder / f"{stem}.txt"
        atomic_write_text(target, block.strip() + "\n")
        if tonight:
            when = (f"at {self.s.schedule.time} tonight (night shift is on)" if self.s.schedule.enabled
                    else "when the night shift is turned on in Setup > General")
            return f"{msg}\nSaved for the night shift as {target.name}. Joe starts it {when}."
        return (f"{msg}\nQueued as {target.name}. " +
                ("Joe's window is open, so he picks it up within a few seconds." if _window_open()
                 else "Joe's window is closed: it runs when he opens."))

    def report(self) -> str:
        p = self.sb.output / "_REPORT.md"
        return p.read_text(encoding="utf-8", errors="replace")[:MAX_READ] if p.exists() else "No report yet."

    def log(self, lines: int = 80) -> str:
        p = self.sb.output / "_log.txt"
        if not p.exists():
            return "No log yet."
        tail = p.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(int(lines), 2000)):]
        return "\n".join(tail)

    def _inside_output(self, rel: str) -> Path:
        from .sandbox import SandboxError
        out = self.sb.output.resolve()
        p = (out / (rel or "").replace("\\", "/").lstrip("/")).resolve()
        if p != out and out not in p.parents:
            raise SandboxError("That's outside Joe's Output folder.")
        return p

    def list_files(self, folder: str = "") -> str:
        p = self._inside_output(folder)
        if not p.is_dir():
            return "No such folder in Output."
        rows = []
        for c in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
            if c.name.startswith("."):
                continue
            rows.append(c.name + "/" if c.is_dir() else f"{c.name}  ({c.stat().st_size:,} bytes)")
            if len(rows) >= 500:
                rows.append("... (more not shown)")
                break
        return "\n".join(rows) or "(empty)"

    def read_file(self, rel: str) -> str:
        p = self._inside_output(rel)
        if not p.is_file():
            return "No such file in Output."
        if p.suffix.lower() not in TEXT_EXT:
            return f"{p.name} isn't a text file ({p.stat().st_size:,} bytes); open it in Joe's Files (F7)."
        return p.read_text(encoding="utf-8", errors="replace")[:MAX_READ]

    def call(self, name: str, args: dict) -> str:
        if name == "joe_status":
            return self.status()
        if name == "joe_mission_format":
            return self.mission_format()
        if name == "joe_check_mission":
            return self.check(str(args.get("mission", "")))[1]
        if name == "joe_queue_mission":
            return self.queue(str(args.get("mission", "")), str(args.get("name", "")), bool(args.get("tonight")))
        if name == "joe_report":
            return self.report()
        if name == "joe_log":
            return self.log(int(args.get("lines") or 80))
        if name == "joe_list_files":
            return self.list_files(str(args.get("folder", "")))
        if name == "joe_read_file":
            return self.read_file(str(args.get("path", "")))
        raise KeyError(name)


def _mission_files(folder: Path) -> list[str]:
    try:
        return [p.name for p in sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime)
                if p.is_file() and p.suffix.lower() in (".txt", ".md") and not p.name.endswith(".problem.txt")]
    except OSError:
        return []


def _window_open() -> bool:
    try:
        from .app import _lock_path
        import urllib.request
        info = json.loads(_lock_path().read_text(encoding="utf-8"))
        req = urllib.request.Request(f"http://127.0.0.1:{info['port']}/api/ping",
                                     headers={"X-NR-Token": info["token"]})
        with urllib.request.urlopen(req, timeout=2):
            return True
    except (OSError, KeyError, ValueError):
        return False


# --------------------------------------------------------------------------- JSON-RPC
def handle(joe: Joe | None, msg: dict) -> dict | None:
    """One request in, one reply out (None for notifications)."""
    mid, method = msg.get("id"), msg.get("method", "")
    if mid is None:                                  # notifications (initialized, cancelled...)
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        want = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
        return ok({"protocolVersion": want, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "joe", "title": "Joe (joe-ai)", "version": __version__},
                   "instructions": "Joe is a local helper that does work overnight with local AI models. "
                                   "Call joe_mission_format before writing a mission, joe_check_mission to "
                                   "test it, then joe_queue_mission. joe_report and joe_log show results."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        p = msg.get("params") or {}
        try:
            text = (joe or Joe()).call(p.get("name", ""), p.get("arguments") or {})
            return ok({"content": [{"type": "text", "text": text}], "isError": False})
        except KeyError:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool: {p.get('name')}"}}
        except Exception as e:                       # noqa: BLE001 (report it, keep serving)
            return ok({"content": [{"type": "text", "text": f"Joe couldn't do that: {e}"}], "isError": True})
    if method in ("resources/list", "prompts/list"):
        return ok({method.split("/")[0]: []})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    joe = None
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            if joe is None and msg.get("method") == "tools/call":
                joe = Joe()
            reply = handle(joe, msg) if isinstance(msg, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
    return 0


def client_config() -> dict:
    """The lines to paste into Claude Desktop's claude_desktop_config.json (or any MCP app)."""
    from .system import joe_command
    cmd = joe_command("mcp", console=True)
    entry = {"command": cmd[0], "args": cmd[1:], "env": {"PYTHONIOENCODING": "utf-8"}}
    if cmd[1:3] == ["-m", "joeai"]:
        entry["env"]["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    return {"mcpServers": {"joe": entry}}
