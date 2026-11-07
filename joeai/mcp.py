"""Joe as an MCP connector (local, stdio) for Claude Desktop and other MCP apps.

    python -m joeai mcp

The app starts this itself (Setup > General > Use Joe from another AI app shows the lines to
paste into its settings). It speaks JSON-RPC 2.0, one message per line, on stdin/stdout. What
the other app can do, and nothing more:
  - see Joe's status (is the window open, Ollama/ComfyUI up, what's running, what's waiting)
  - read the mission format, the last report, the end of the log, the files Joe made
  - check a mission (no changes) and queue one (a file in Missions/Queue; Joe runs it when his
    window is open, or at the night-shift time); make pictures; run a tool on Inbox files
  - look at the pictures Joe made, and ask him to stop a run
It can't run programs, install anything, change settings, or read or write outside Joe's folder.
The same tools are at http://127.0.0.1:<Joe's port>/mcp while his window is open (with a key).
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

# What every connected AI app reads first (MCP "instructions"): how to work WITH Joe, the way a
# helper hands grunt work to an assistant and then polishes what comes back.
INSTRUCTIONS = """Joe is a free helper running on this person's own PC with local AI models (writing,
pictures, video, sound, and tools for their files). He works for free and keeps working while
the person sleeps, but his models are smaller than you, so his drafts need your polish.

How to work with Joe:
1. When the person wants bulk or slow work (many items, long drafts, a batch of pictures,
   transcribing recordings, translating documents, restoring photos, product descriptions,
   social posts...), suggest giving the grunt work to Joe and say what he'd make. Call
   joe_capabilities first to see what this PC can do and how long things take.
2. Write the plan: joe_mission_format shows the exact format; joe_check_mission tests it;
   joe_queue_mission hands it over (tonight=true waits for the night shift). For pictures,
   joe_make_pictures; for tools on the person's files, joe_list_inbox + joe_run_tool.
3. Check in with joe_status and joe_report. When it's done, read the results with
   joe_list_files, joe_read_file and joe_show_picture.
4. Polish: fix facts, tighten wording, pick the best pictures, and fill in anything marked
   [CHECK] with the person. Tell them what Joe made and what you changed.
Never invent results Joe didn't produce. If his window is closed, queued work waits until it
opens (or the night-shift time)."""

TOOLS = [
    {"name": "joe_status",
     "description": "Joe's status: whether his window is open, whether Ollama (writing) and ComfyUI "
                    "(pictures/video) are up, what he's doing now, and the missions waiting in his queue.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "joe_capabilities",
     "description": "What Joe can do on THIS PC right now: writing and picture models, tools that are "
                    "ready, how long typical work takes here, and what's waiting. Call this before "
                    "suggesting work for Joe.",
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
    {"name": "joe_make_pictures",
     "description": "Have Joe make pictures with his local picture models. Queued like any plan; the "
                    "files land in Output/<folder>. Styles: photo, watercolor, anime, coloring, cartoon, "
                    "illustration, product, painting, character, bw and more.",
     "inputSchema": {"type": "object", "properties": {
         "description": {"type": "string", "description": "what the pictures show"},
         "count": {"type": "integer", "minimum": 1, "maximum": 40},
         "style": {"type": "string"},
         "folder": {"type": "string", "description": "a short name for the output folder"}},
         "required": ["description"]}},
    {"name": "joe_list_tools",
     "description": "Joe's tools for files (transcribe, translate, proofread, restore photos, remove "
                    "backgrounds, fix one spot, change the lighting...) with their options.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "joe_list_inbox",
     "description": "Files waiting in Joe's Inbox, to use with joe_run_tool.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "joe_run_tool",
     "description": "Run one of Joe's tools on files in his Inbox (see joe_list_tools and joe_list_inbox). "
                    "Queued like any plan.",
     "inputSchema": {"type": "object", "properties": {
         "tool": {"type": "string"}, "files": {"type": "array", "items": {"type": "string"}},
         "options": {"type": "array", "items": {"type": "string"}},
         "instruction": {"type": "string", "description": "the tool's text box (what to change, scenes...)"},
         "name": {"type": "string"}}, "required": ["tool"]}},
    {"name": "joe_stop",
     "description": "Ask Joe to stop his current run after the step he's on (only works while his window is open).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "joe_show_picture",
     "description": "Look at a picture Joe made (a path inside his Output folder). Returns the picture.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
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

    def capabilities(self) -> str:
        from . import stats as stats_mod
        from .tools import TOOLS
        lines = ["Joe can make: lists of items (descriptions, posts, emails, FAQs), documents section by "
                 "section, spreadsheets (CSV), code drafts, AI pictures (many styles), short video clips, "
                 "music and sound effects (when installed)."]
        try:
            from .doctor import ollama_models
            from .services import ServiceManager
            sm = ServiceManager(self.s, log=lambda *_: None)
            names = [m["name"] for m in ollama_models(sm) if m.get("writer", True)]
            if names:
                lines.append("Writing models here: " + ", ".join(names[:8]))
        except Exception:                                   # noqa: BLE001
            pass
        lines.append("Tools for the person's files (some need a one-time download the person approves in "
                     "Joe; joe_list_tools has the details): " + ", ".join(t.name for t in TOOLS.values() if t.ready))
        try:
            sp = stats_mod.speeds(self.sb)
            lines.append(f"Typical time on this PC: about {round(sp.get('part', 25))} s per part of a list "
                         f"(4-10 items), {round(sp.get('image', 30))} s per picture, "
                         f"{round(sp.get('video', 240) / 60)} min per video clip.")
        except Exception:                                   # noqa: BLE001
            pass
        q = self.s.quality
        lines.append(f"Quality settings: writing {q.writing}, pictures {q.pictures}, video {q.video}.")
        lines.append(self.status())
        return "\n".join(lines)

    def mission_format(self) -> str:
        from .bigger import HOW_TO_ANSWER, extra_keys, format_text
        return format_text() + "\n\n" + extra_keys() + "\n\n" + HOW_TO_ANSWER

    def check(self, text: str) -> tuple[bool, str]:
        from .bigger import tidy
        from .mission import MissionError, parse
        from .sandbox import SandboxError
        block = tidy(text)[0] or text
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
        from .bigger import tidy
        from .fsutil import atomic_write_text
        from .mission import slug
        ok, msg = self.check(text)
        if not ok:
            return msg + "\nNothing was queued. Fix the mission and try again."
        block = tidy(text)[0] or text
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
        if any(part.startswith(".") for part in p.relative_to(out).parts):   # .joe = chats, state: private
            raise SandboxError("That's one of Joe's private folders (chats and run state stay on this PC).")
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

    def make_pictures(self, description: str, count: int = 4, style: str = "", folder: str = "") -> str:
        from .mission import _safe
        from .styles import NAMES
        desc = " ".join(_safe(description).split())[:600]
        if not desc:
            return "Say what the pictures should show."
        n = max(1, min(40, int(count or 4)))
        size = next((k for k in (8, 6, 4, 5, 7, 3, 2) if n > 8 and n % k == 0), n)
        parts = n // size
        style = (style or "").strip().lower()
        lines = ["=== JOE MISSION ===", f"TASK: {folder.strip() or desc[:40]}", "TYPE: image",
                 f"CHUNKS: {parts} x {size}", f"FORMAT: {desc}"]
        if style in NAMES:
            lines.append(f"STYLE: {style}")
        lines.append("=== END ===")
        out = self.queue("\n".join(lines), folder or desc[:40])
        return out + ("" if style in NAMES or not style else f"\n(Style '{style}' isn't one of Joe's; he picks one.)")

    def list_tools(self) -> str:
        from .tools import TOOLS
        rows = []
        for t in TOOLS.values():
            if not t.ready:
                continue
            opts = "; ".join((f"{o.key} " + "|".join(c[0] for c in o.choices)) if o.choices else o.key
                             for o in t.options)
            rows.append(f"- {t.id}: {t.name}. {t.blurb}" + (f" Options: {opts}." if opts else "")
                        + (f" Files: {' '.join(t.accepts)}" if t.accepts else ""))
        return "\n".join(rows)

    def list_inbox(self) -> str:
        from .tools import inbox_media
        files = inbox_media(self.sb, limit=300)
        return "\n".join(files) if files else "Joe's Inbox is empty. Put files in the Inbox folder of Joe's folder."

    def run_tool(self, tool: str, files: list | None, options: list | None, instruction: str = "",
                 name: str = "") -> str:
        from .mission import _safe
        from .tools import TOOLS
        if tool not in TOOLS or not TOOLS[tool].ready:
            return f"Joe has no tool called '{tool}'. joe_list_tools lists them."
        lines = ["=== JOE MISSION ===", f"TASK: {' '.join(_safe(name or TOOLS[tool].name).split())[:60]}",
                 f"TYPE: {tool}"]
        files = [str(f) for f in (files or []) if str(f).strip()]
        if files:
            lines.append("INPUT: " + ", ".join(_safe(f) for f in files))
        if options:
            lines.append("OPTIONS: " + ", ".join(_safe(str(o)) for o in options))
        if instruction.strip():
            lines.append("FORMAT: " + _safe(instruction.strip())[:2000])
        lines.append("=== END ===")
        return self.queue("\n".join(lines), name or tool)

    def stop(self) -> str:
        try:
            import urllib.request
            from .app import _lock_path
            info = json.loads(_lock_path().read_text(encoding="utf-8"))
            req = urllib.request.Request(f"http://127.0.0.1:{info['port']}/api/stop", data=b"{}", method="POST",
                                         headers={"X-NR-Token": info["token"], "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).close()
            return "Joe will stop after the step he's on."
        except (OSError, KeyError, ValueError):
            return "Joe's window isn't open, so nothing is running."

    def show_picture(self, rel: str) -> dict:
        """MCP image content (shrunk to at most 1280 px as JPEG when FFmpeg is there)."""
        import base64
        p = self._inside_output(rel)
        if not p.is_file() or p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            return {"type": "text", "text": "No such picture in Output."}
        data, mime = p.read_bytes(), {"jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(p.suffix[1:].lower(),
                                                                                  f"image/{p.suffix[1:].lower()}")
        try:
            from .doctor import ffmpeg_exe
            from .tools import fit_size, image_size, photo_command
            ff = ffmpeg_exe(self.s.comfy.ffmpeg)
            if ff:
                import subprocess
                import tempfile
                dims = image_size(ff, p)
                with tempfile.TemporaryDirectory() as td:
                    out = Path(td) / "small.jpg"
                    cmd = photo_command(ff, p, out, fit_size(*dims, 1280), 1, "jpg", None, None, None, "") if dims else None
                    if cmd and subprocess.run(cmd, capture_output=True, timeout=120).returncode == 0 and out.exists():
                        data, mime = out.read_bytes(), "image/jpeg"
        except Exception:                                  # noqa: BLE001 (send the original)
            pass
        if len(data) > 8_000_000:
            return {"type": "text", "text": "That picture is too big to send; open it in Joe's Files (F7)."}
        return {"type": "image", "data": base64.b64encode(data).decode(), "mimeType": mime}

    def call(self, name: str, args: dict):
        if name == "joe_status":
            return self.status()
        if name == "joe_capabilities":
            return self.capabilities()
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
        if name == "joe_make_pictures":
            return self.make_pictures(str(args.get("description", "")), args.get("count") or 4,
                                      str(args.get("style", "")), str(args.get("folder", "")))
        if name == "joe_list_tools":
            return self.list_tools()
        if name == "joe_list_inbox":
            return self.list_inbox()
        if name == "joe_run_tool":
            return self.run_tool(str(args.get("tool", "")), args.get("files"), args.get("options"),
                                 str(args.get("instruction", "")), str(args.get("name", "")))
        if name == "joe_stop":
            return self.stop()
        if name == "joe_show_picture":
            return self.show_picture(str(args.get("path", "")))
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
        return ok({"protocolVersion": want, "capabilities": {"tools": {}, "prompts": {}},
                   "serverInfo": {"name": "joe", "title": "Joe (joe-ai)", "version": __version__},
                   "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        p = msg.get("params") or {}
        try:
            res = (joe or Joe()).call(p.get("name", ""), p.get("arguments") or {})
            content = res if isinstance(res, dict) else {"type": "text", "text": str(res)}
            return ok({"content": [content], "isError": False})
        except KeyError:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool: {p.get('name')}"}}
        except Exception as e:                       # noqa: BLE001 (report it, keep serving)
            return ok({"content": [{"type": "text", "text": f"Joe couldn't do that: {e}"}], "isError": True})
    if method == "prompts/list":
        return ok({"prompts": [{"name": "work-with-joe", "title": "Hand the grunt work to Joe",
                                "description": "Plan a job so Joe does the bulk work on this PC and you polish it.",
                                "arguments": [{"name": "job", "description": "what the person wants made",
                                               "required": True}]}]})
    if method == "prompts/get":
        job = str(((msg.get("params") or {}).get("arguments") or {}).get("job", "")).strip()
        text = (INSTRUCTIONS + "\n\nThe person wants: " + (job or "(ask them)") +
                "\n\nStart with joe_capabilities, then propose which parts Joe should do, how long they'll "
                "take, and what you'll polish afterwards. Queue it only after the person says yes.")
        return ok({"description": "Hand the grunt work to Joe",
                   "messages": [{"role": "user", "content": {"type": "text", "text": text}}]})
    if method == "resources/list":
        return ok({"resources": []})
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
            if not isinstance(msg, dict):          # a batch or a stray value: say so, keep running
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
            else:
                if joe is None and msg.get("method") == "tools/call":
                    try:
                        joe = Joe()
                    except Exception as e:     # noqa: BLE001 (settings unreadable etc.: answer, don't die)
                        stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"),
                                                 "error": {"code": -32603, "message": f"Joe couldn't start: {e}"}}) + "\n")
                        stdout.flush()
                        continue
                reply = handle(joe, msg)
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
