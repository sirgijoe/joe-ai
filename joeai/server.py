"""Local app server: serves the retro UI and a small JSON API on 127.0.0.1 only.

Security:
- Binds to 127.0.0.1, checks the Host header (blocks DNS-rebinding tricks).
- Every API call needs a random per-launch token (other web pages can't call it).
- File access goes through the Sandbox: nothing outside the workspace.

The run happens in a background thread, so closing the window does NOT stop an
overnight run. The server exits on its own once the window is gone and no run is active.
"""
from __future__ import annotations

import collections
import re
import json
import mimetypes
import secrets
import threading
import time
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from . import comfy as comfy_mod
from .config import Settings, _merge, config_dir
from .engine import Engine
from .fsutil import atomic_write_text
from .mission import MissionError, parse
from .sandbox import Sandbox, SandboxError
from .services import ServiceManager
from . import stats as stats_mod
from . import doctor, hardware, system
from . import media as media_mod
from . import storage as storage_mod
from . import themes as themes_mod
from . import addons as addons_mod
from . import chat as chat_mod
from .chats import Chats
from . import notify as notify_mod
from . import portable as portable_mod

UI_DIR = Path(__file__).parent / "ui"


def local_font() -> Path | None:
    """The retro VT323 font shipped with Joe (SIL OFL 1.1, joeai/ui/fonts/OFL.txt)."""
    f = UI_DIR / "fonts" / "VT323-Regular.ttf"
    return f if f.is_file() and f.stat().st_size > 10_000 else None
TEXT_TYPES = {".md", ".txt", ".csv", ".json", ".log", ".py", ".cs", ".cpp", ".h", ".js",
              ".ts", ".html", ".css", ".ini", ".yaml", ".yml", ".ps1", ".bat", ".xml"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO_TYPES = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}
mimetypes.add_type("video/x-matroska", ".mkv")
mimetypes.add_type("video/mp4", ".m4v")
SECONDS_PER_PART = 25
SECONDS_PER_IMAGE = 30
SECONDS_PER_VIDEO = 240
IDLE_EXIT_S = 180
      # window gone (no polling) and no run -> quit


class App:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.load()
        self.sb = Sandbox(self.settings.workspace_path).ensure()
        storage_mod.cap_logs(self.sb)
        self.token = secrets.token_urlsafe(24)
        self.held_plan: dict = {}                 # a request that waits for the pictures to finish
        self.portable_job = portable_mod.Job()    # MAKE A PORTABLE JOE (one copy at a time)
        self.short_models: set[str] = set()       # last CHECK MY MODEL FILES: files that may be moved
        self.leaky_models: set[str] = set()       # Talk models that "think out loud" (asked with think on)
        self.lock = threading.RLock()
        self.logs: collections.deque[str] = collections.deque(maxlen=400)
        self.log_count = 0                   # lines logged since Joe started (never goes down)
        self.log_from = 0                    # the Home screen shows lines from here (this chat)
        self.capture: list[str] | None = None   # the running mission's log, saved into its chat
        self.engine: Engine | None = None
        self.thread: threading.Thread | None = None
        self.stop = threading.Event()
        self.mission_text = ""
        self.run_started = 0.0
        self.parts_at_start = 0
        self.last_seen = time.monotonic()
        self.quit_now = False
        self.services_status = {"ollama": False, "comfyui": False, "loaded": []}
        self.dl_all: dict = {}            # Setup > Models > DOWNLOAD ALL progress
        self.restart_hint = ""            # "restart Joe" advice shown in the window (with a button)
        self.services = ServiceManager(self.settings, log=self.log)
        self.fix_result: dict = {}           # how the last System-check fix went (for the UI)
        self.busy = ""                       # a system-check fix running in the background
        self.busy_pct: float | None = None
        self.voice = addons_mod.VoiceWorker(self.log)
        # Tools (transcribing a long recording) get their own helper so Talk stays quick meanwhile.
        self.tool_voice = addons_mod.VoiceWorker(self.log)
        self.clone = addons_mod.VoiceWorker(self.log, python=str(addons_mod.clone_python()),
                                            script=Path(addons_mod.__file__).with_name("clone_worker.py"))
        self.chat_history: list[dict] = []   # this session only (fresh start every launch)
        self._chats: Chats | None = None     # saved copies of each chat (Talk > PAST CHATS)
        try:
            self.chats.prune(self.settings.voice.chat_keep_days)
        except OSError:
            pass
        self.talk_files: list[dict] = []     # files dropped into Talk, waiting for the next message
        self.queue: list = []                # (text, mission, entry) waiting to run
        self.run_log: list[dict] = []        # missions in the current/last queue run
        self.chain: list = []                # (mission, states) finished in this queue run
        self.queue_started = ""
        self.queue_finished = None
        self.pending_ping = ""               # phone ping held back by quiet hours
        self.finished = {"n": 0, "ok": True, "text": ""}   # last finished queue run (UI chime)
        from .phone import Phone
        self.phone = Phone(self)             # Joe Phone (Setup > Phone): started by serve() when it's on
        # The mission box always opens empty ("What can I help you with?"). Past missions
        # stay in Missions/ (F7, L loads one); _last_mission.txt is kept only as a backup.

    # -- helpers ---------------------------------------------------------------
    def debug(self, line: str) -> None:
        """Timing/diagnostic lines: kept for MAKE A HELP FILE, not shown in the window's log."""
        dl = getattr(self, "debug_lines", None)
        if dl is None:
            dl = self.debug_lines = []
        dl.append(time.strftime("[%H:%M:%S] ") + line)
        del dl[:-200]

    def log(self, line: str) -> None:
        self.logs.append(line)
        self.log_count += 1
        cap = self.capture
        if cap is not None and len(cap) < 5000:
            cap.append(line)

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def rel_path(self, rel: str) -> Path:
        rel = (rel or "").replace("\\", "/").strip("/")
        if any(p == ".." for p in rel.split("/")):
            raise SandboxError("'..' not allowed")
        return self.sb.check(self.sb.root / rel) if rel else self.sb.root

    def background_work(self) -> bool:
        """A download, install or portable copy is still going (closing the window mustn't kill it)."""
        try:
            return bool(self.busy or (self.dl_all or {}).get("running")
                        or self.portable_job.status().get("running"))
        except Exception:                          # noqa: BLE001
            return False

    def refresh_services(self) -> None:
        try:
            self.services_status = self.services.status()
        except Exception as e:  # never let a status probe kill the loop
            self.log(f"status check failed: {e}")

    # -- actions ---------------------------------------------------------------
    def check(self, text: str) -> dict:
        try:
            m = parse(text)
            for j in m.jobs:
                self.sb.resolve(j.save)
        except (MissionError, SandboxError) as e:
            return {"ok": False, "error": str(e)}
        warnings = []
        names = {x.name: x for x in m.jobs}
        if any(j.research for j in m.jobs) and not self.settings.web.enabled:
            warnings.append("A task asks Joe to look things up online, but online lookups are off. Turn on "
                            "Setup (F10) > Voice & Talk > Let Joe look things up online, or Joe writes from what he knows.")
        for j in m.jobs:
            src = names.get(j.source) if j.source else None
            if src is not None:
                have = src.total_items
                want = (len(j.part_prompts) or j.parts * j.part_size) if j.media else j.total_items
                if not j.guided and have and want != have and not (j.media and want < have):
                    warnings.append(f"Task '{j.name}' makes {want} but '{src.name}' (its FROM) makes "
                                    f"{have}: " + (f"only the first {want} are matched." if want < have
                                                   else f"the last {want - have} are written on their own."))
        for j in m.jobs:
            if not j.media:
                continue
            wf = j.workflow or self.settings.comfy.default_workflow
            if wf:
                from .comfy import WorkflowError, check_template, load_template
                name = wf if wf.lower().endswith(".json") else wf + ".json"
                try:
                    path = self.sb.resolve(name, base="Workflows")
                    if not path.is_file():
                        return {"ok": False, "error": f"Task '{j.name}': no Workflows/{name}"}
                    problem = check_template(load_template(path))
                except (WorkflowError, SandboxError) as e:
                    problem = str(e)
                if problem:
                    return {"ok": False, "error": f"Task '{j.name}': {problem}"}
            elif j.type == "video":
                from .comfy import WAN_VIDEO, wan_missing
                from .doctor import comfy_models_dir
                if wan_missing(comfy_models_dir(self.settings)):
                    return {"ok": False, "error": (
                        f"Task '{j.name}': the video model isn't installed yet. F10 > System check "
                        f"downloads {WAN_VIDEO['label']} (about {WAN_VIDEO['size_gb']:.0f} GB); restart "
                        "ComfyUI after. Or give the task a WORKFLOW.")}
        if any(j.media for j in m.jobs) and not (self.services.comfy_up() or self.services.comfy_exe()
                                                 or self.settings.comfy.start_command):
            warnings.append("ComfyUI isn't installed; image/video tasks will fail (F10 > System check).")
        from .picturetools import COMFY_TOOLS
        if any(j.media or j.type in COMFY_TOOLS for j in m.jobs) and not self.services.comfy_up():
            warnings.append("Joe will start ComfyUI (the picture maker) for this. If it's updating or waits "
                            "for a click in its own window, Joe waits for it.")
        if any(j.type == "video" and not j.workflow for j in m.jobs):
            from . import quality as quality_mod
            from .comfy import WAN_TURBO, wan_missing, wan_turbo_installed
            from .doctor import comfy_models_dir
            mdir = comfy_models_dir(self.settings)
            lv = quality_mod.level(self.settings, "video")
            if lv != "high" and mdir and not wan_missing(mdir) and not wan_turbo_installed(mdir):
                warnings.append(f"Based on your {lv.capitalize()} video setting, I'd recommend the "
                                f"{WAN_TURBO['label']} (under 1 GB) for this: several times faster. "
                                "Install it from Setup > System check, or run as is.")
        need = disk_need(m, self.sb)                  # room for what this plan makes?
        room = system.room_problem(self.sb.output, need, spare=2_000_000_000)
        if room:
            warnings.append("Low on space: " + room[0].lower() + room[1:])
        parts = sum(j.parts for j in m.jobs if not j.media and not j.tool)
        sp = stats_mod.speeds(self.sb)                # learned on this PC; rough defaults at first
        secs = parts * sp["part"]
        tool_info: dict[str, dict] = {}
        for j in m.jobs:
            if not j.tool:
                continue
            from . import tools as tools_mod
            problem = tools_mod.needs_problem(self.settings, j)
            if problem:
                return {"ok": False, "error": problem}
            info = tools_mod.plan_info(self.sb, j, sp)
            if not info["files"] and tools_mod.TOOLS[j.type].accepts and j.type not in tools_mod.NO_INPUT_OK:
                return {"ok": False, "error": f"Task '{j.name}': no files to work on yet. Add them "
                        "on the Tools tab (F3), or put them in Joe's Inbox folder."
                        + (f" ({info['problems'][0]})" if info["problems"] else "")}
            warnings += [f"Task '{j.name}': {p}" for p in info["problems"]]
            if j.type == "transcribe" and any(not str(x).lower().endswith(".wav") for x in j.inputs):
                from .doctor import ffmpeg_exe
                if not ffmpeg_exe(self.settings.comfy.ffmpeg):
                    warnings.append("FFmpeg isn't installed, so only .wav recordings can be read "
                                    "(Setup > System check installs it).")
            if j.type == "photo-batch":
                from .doctor import ffmpeg_exe
                if not ffmpeg_exe(self.settings.comfy.ffmpeg):
                    return {"ok": False, "error": f"Task '{j.name}': photo tools need FFmpeg first. "
                            "Setup (F10) > System check installs it."}
            if j.type == "read-aloud":
                from .doctor import ffmpeg_exe
                if not ffmpeg_exe(self.settings.comfy.ffmpeg):
                    warnings.append("FFmpeg isn't installed, so Joe saves WAV files (much bigger) "
                                    "instead of MP3 (Setup > System check installs it).")
            secs += info["seconds"]
            tool_info[j.job_id] = info
        for j in m.jobs:
            if j.media:
                n = (len(j.part_prompts) or j.parts * j.part_size)
                secs += n * j.variants * (sp["video"] if j.type == "video" else sp["image"])
                secs += 0 if j.prompts_as_written else n * 6
        return {"ok": True, "project": m.project, "parts": parts, "warnings": warnings,
                "eta_min": round(secs / 60), "eta_learned": bool(sp["learned"]),
                "jobs": [{"name": j.name, "type": "csv" if j.is_csv else j.type, "parts": j.parts,
                          "size": j.part_size, "items": j.total_items, "guided": j.guided,
                          "min_words": j.min_words, "save": j.save, "variants": j.variants,
                          "prompts": len(j.part_prompts) or j.parts * j.part_size,
                          "workflow": j.workflow, "options": j.options, "watermark": j.watermark,
                          "format": j.format if j.tool else "",
                          "files": tool_info.get(j.job_id, {}).get("files", 0),
                          "project": j.project or m.project, "source": j.source}
                         for j in m.jobs]}

    # -- queue: missions run back-to-back until the queue is empty ------------------
    def _save_mission_file(self, text: str) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        p, n = self.sb.missions / f"mission_{stamp}.txt", 2
        while p.exists():
            p, n = self.sb.missions / f"mission_{stamp}_{n}.txt", n + 1
        p.write_text(text, encoding="utf-8")
        return str(p.relative_to(self.sb.root)).replace("\\", "/")

    @staticmethod
    def _label(m) -> str:
        names = [j.name for j in m.jobs]
        head = ", ".join(names[:3]) + (f" +{len(names) - 3} more" if len(names) > 3 else "")
        return (f"{m.project}: " if m.project else "") + head

    def _write_last_run(self) -> None:
        """What this queue run covers, so a crash or power cut can be resumed next launch."""
        data = {"started": self.queue_started, "finished": self.queue_finished,
                "missions": self.run_log}
        try:
            atomic_write_text(self.sb.meta / "last_run.json", json.dumps(data, indent=1))
        except OSError:
            pass

    def watch_queue_folder(self) -> list[str]:
        """Missions dropped into Missions/Queue are queued on their own (oldest first), so
        work can be handed to Joe without pasting. A queued file moves to Queue/done; one
        with a problem moves to Queue/problems with a note saying what's wrong."""
        folder = self.sb.missions / "Queue"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            files = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".txt", ".md")),
                           key=lambda p: p.stat().st_mtime)
        except OSError:
            return []
        done = []
        for p in files:
            try:
                if time.time() - p.stat().st_mtime < 3:      # still being written
                    continue
                text = p.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            from .packs import split_blocks
            r = {"ok": True}
            for block in split_blocks(text):                 # a file with several missions: each one
                try:
                    one = self.enqueue(block)
                except Exception as e:                       # noqa: BLE001 (never stop the loop)
                    one = {"ok": False, "error": str(e)}
                if not one.get("ok"):
                    r = one
            sub = folder / ("done" if r.get("ok") else "problems")
            sub.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = sub / f"{p.stem}_{stamp}{p.suffix}"
            try:
                p.replace(target)
                if not r.get("ok"):
                    target.with_suffix(".problem.txt").write_text(
                        f"Joe couldn't queue {p.name}:\n{r.get('error', 'unknown problem')}\n", encoding="utf-8")
            except OSError:
                continue
            self.log(f"Mission file {p.name} " + ("queued" if r.get("ok") else f"not queued: {r.get('error')}"))
            done.append(p.name)
        return done

    def enqueue(self, text: str, only: list[str] | None = None) -> dict:
        """Add a mission to the queue; starts running if Joe is idle.
        only = run just these task names (resume: skip what already finished)."""
        chk = self.check(text)
        if not chk["ok"]:
            return chk
        mission = parse(text)
        if only is not None:
            mission.jobs = [j for j in mission.jobs if j.name in set(only)]
            if not mission.jobs:
                return {"ok": False, "error": "Nothing left to do in that mission."}
        with self.lock:
            entry = {"file": self._save_mission_file(text), "label": self._label(mission),
                     "tasks": [j.name for j in mission.jobs], "unfinished": [j.name for j in mission.jobs],
                     "eta_min": chk.get("eta_min", 0)}
            from . import describe as describe_mod
            entry["chat"] = self.note_chat(
                {"who": "joe", "kind": "run", "mission": text,
                 "text": ("Queued: " if self.running else "Started: ") + entry["label"],
                 "summary": describe_mod.plain_summary(chk)}, title=entry["label"])
            (self.sb.missions / "_last_mission.txt").write_text(text, encoding="utf-8")
            if self.running and not getattr(self, "accepting", True):
                self.thread.join(timeout=180)      # the run is wrapping up: let it finish, then start fresh
            if self.running and getattr(self, "accepting", True):
                self.queue.append((text, mission, entry))
                self.run_log.append(entry)
                self._write_last_run()
                self.log(f"Queued: {entry['label']} ({len(self.queue)} waiting)")
                return {"ok": True, "queued": len(self.queue)}
            self.queue = [(text, mission, entry)]
            self.run_log = [entry]
            self.chain = []
            self.queue_started = datetime.now().isoformat(timespec="seconds")
            self.queue_finished = None
            self._write_last_run()
            self.stop = threading.Event()
            self.accepting = True                  # the run thread still takes queued work
            self.run_started = time.time()
            self.parts_at_start = 0
            self.thread = threading.Thread(target=self._work, daemon=False, name="joe-run")
            self.thread.start()
        time.sleep(0.2)                       # count parts already done (resume)
        if self.engine:
            self.parts_at_start = sum(s.parts_done for s in self.engine.live)
        return {"ok": True, "queued": 0}

    def run(self, text: str) -> dict:
        with self.lock:                            # two quick presses (click + F5) must not start twice
            starting = getattr(self, "_starting", None)
            if starting is not None or self.running:
                if (text or "").strip() in (starting, (getattr(self, "mission_text", "") or "").strip()):
                    return {"ok": True, "already": True}   # same plan, already starting: nothing to do
                return {"ok": False, "error": "Joe is busy. Use ADD TO QUEUE, or stop the run first (F5)."}
            self._starting = (text or "").strip()
        try:
            return self.enqueue(text)
        finally:
            self._starting = None

    def _past_stop_time(self) -> bool:
        """Night shift "stop by": past it, missions not started yet wait for the next night."""
        from . import schedule
        until = schedule.read_stop(self.sb)
        return until is not None and datetime.now() >= until

    def _leave_for_tomorrow(self) -> None:
        """(under self.lock) Queue -> Missions/Tonight, noted in the log, report and phone ping."""
        from . import schedule
        left = [(e.get("label") or "plan", t) for t, _, e in self.queue]
        self.queue = []
        names = schedule.put_back(self.sb, left)
        self.left_labels += [lbl for lbl, _ in left][:len(names)]
        self.left_for_tomorrow = len(self.left_labels)
        if names:
            self.log(f"Stop time reached: {len(names)} mission{'s' if len(names) != 1 else ''} saved in "
                     "Missions/Tonight for tomorrow night.")

    def _work(self) -> None:
        self.left_for_tomorrow = 0
        self.left_labels: list[str] = []
        while True:
            with self.lock:
                if self.queue and not self.stop.is_set() and self._past_stop_time():
                    self._leave_for_tomorrow()
                if not self.queue or self.stop.is_set():
                    self.accepting = False         # from here on, new work starts a new run
                    break
                text, mission, entry = self.queue.pop(0)
                self.mission_text = text
                self.engine = Engine(self.settings, self.sb, services=self.services,
                                     log=self.log, stop=self.stop, voice=self.tool_voice)
                last = not self.queue
            self.capture = []
            try:
                states = self.engine.run_mission(mission, earlier=self.chain, finish=False)
            except Exception as e:
                self.log(f"!! Run crashed: {e!r}")
                self.run_result(entry, list(self.engine.live), self.capture or [])
                self.capture = None
                with self.lock:
                    self.accepting = False
                break
            lines, self.capture = self.capture or [], None
            self.run_result(entry, states, lines)
            self.chain.append((mission, states))
            entry["unfinished"] = [s.name for s in states if s.status != "done"]
            self._write_last_run()
        self.queue_finished = datetime.now().isoformat(timespec="seconds")
        self._write_last_run()
        stopped = self.stop.is_set()
        if self.queue and stopped:
            self.log(f"Run stopped; {len(self.queue)} queued mission(s) were not started.")
        self.queue = []
        from . import schedule
        schedule.clear_stop(self.sb)
        if self.left_labels:
            from . import report as report_mod
            report_mod.add_left_note(self.sb, self.left_labels)
        if not stopped:
            self._run_finished()
            from .power import when_finished
            when_finished(self.settings.engine.when_finished, self.log)

    # -- comfort: quiet hours, phone ping ---------------------------------------
    def quiet(self) -> bool:
        c = self.settings.comfort
        return notify_mod.in_quiet_hours(c.quiet_start, c.quiet_end)

    def _run_finished(self) -> None:
        text = notify_mod.summary_line(self.chain)
        n = getattr(self, "left_for_tomorrow", 0)
        if n:
            text += f" {n} mission{'s' if n != 1 else ''} left for tomorrow night."
        ok = all(s.status == "done" for _, st in self.chain for s in st)
        self.finished = {"n": self.finished["n"] + 1, "ok": ok, "text": text}
        if not self.settings.comfort.ntfy_topic.strip():
            return
        if self.quiet():
            self.pending_ping = text
            self.log("Phone ping waits until quiet hours end.")
        else:
            self.send_ping(text)

    def send_ping(self, text: str) -> str:
        c = self.settings.comfort
        err = notify_mod.send_ntfy(c.ntfy_server, c.ntfy_topic.strip(), text)
        self.log("Phone ping sent." if not err else f"Phone ping failed: {err}")
        return err

    def ping_tick(self) -> None:
        """Background loop: send a held-back ping once quiet hours are over."""
        if self.pending_ping and not self.quiet():
            text, self.pending_ping = self.pending_ping, ""
            self.send_ping(text)

    # -- watch folders: drop a file in Inbox/Watch/<tool> and Joe does it ------------------
    def watch_tools(self) -> list[str]:
        """Tools a watch folder can run: ready, reading files, no must-pick option."""
        from . import tools as tools_mod
        return [t.id for t in tools_mod.TOOLS.values() if t.ready and t.accepts
                and not any(o.required for o in t.options) and t.id not in tools_mod.NO_INPUT_OK
                and t.id not in ("ask-files", "ask-sheet")]

    def watch_setup(self) -> None:
        """Make Inbox/Watch/<tool> folders (with a note) when watch folders are on."""
        from . import tools as tools_mod
        root = self.sb.inbox / "Watch"
        try:
            root.mkdir(parents=True, exist_ok=True)
            for tid in self.watch_tools():
                (root / tid).mkdir(exist_ok=True)
            note = root / "READ ME.txt"
            if not note.exists():
                note.write_text("Watch folders: drop a file into one of these folders and Joe runs that tool on it by "
                                "himself (while Joe is open), with the tool's usual options. Results go to "
                                "Output/watch-<tool>. Each folder is named after its tool:\n\n"
                                + "\n".join(f"  {tid:16} {tools_mod.TOOLS[tid].name}" for tid in self.watch_tools())
                                + "\n\nTurn this off in Setup > General > Watch folders.\n", encoding="utf-8")
        except OSError as e:
            self.log(f"Watch folders: {e}")

    def watch_tick(self, now: float | None = None) -> list[str]:
        """New files in Inbox/Watch/<tool> -> one task per tool, queued. Returns the tools queued."""
        if not self.settings.schedule.watch:
            return []
        from . import tools as tools_mod
        now = now or time.time()
        root = self.sb.inbox / "Watch"
        seen_p = self.sb.meta / "watch_seen.json"
        try:
            seen = set(json.loads(seen_p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            seen = set()
        queued, changed = [], False
        for tid in self.watch_tools():
            folder = root / tid
            if not folder.is_dir():
                continue
            new = []
            try:
                for p in sorted(folder.iterdir()):
                    if not p.is_file() or p.name.startswith(".") or p.suffix.lower() not in tools_mod.TOOLS[tid].accepts:
                        continue
                    stt = p.stat()
                    if now - stt.st_mtime < 5:                   # still being copied in
                        continue
                    key = f"{tid}/{p.name}|{stt.st_size}|{int(stt.st_mtime)}"
                    if key in seen:
                        continue
                    seen.add(key)
                    changed = True
                    if "," in p.name:
                        self.log(f"Watch folder: {p.name} has a comma in its name; rename it to use it.")
                        continue
                    new.append(p.name)
            except OSError:
                continue
            if not new:
                continue
            name = tools_mod.TOOLS[tid].name
            text = (f"TASK: {name} (watch folder)  TYPE: {tid}\nSAVE: watch-{tid}\n"
                    f"INPUT: {', '.join(f'Watch/{tid}/{n}' for n in new)}")
            r = self.enqueue(text)
            self.log(f"Watch folder {tid}: {len(new)} new file(s) " + ("queued." if r.get("ok") else f"not queued: {r.get('error')}"))
            if r.get("ok"):
                queued.append(tid)
        if changed:
            try:
                self.sb.meta.mkdir(parents=True, exist_ok=True)
                atomic_write_text(seen_p, json.dumps(sorted(seen)[-5000:]))
            except OSError:
                pass
        return queued

    def connect_app(self, app_id: str, on: bool, how: str = "") -> dict:
        """CONNECT / DISCONNECT Joe in an AI app. Apps with their own install link (Cursor, LM Studio,
        VS Code) or command (Gemini CLI) add Joe themselves and ask the person; Claude Desktop can take
        an extension file (how="extension"); otherwise Joe writes his entry (with the app closed)."""
        from . import connect as connect_mod
        from .mcp import client_config
        entry = client_config()["mcpServers"]["joe"]
        apps = connect_mod.app_paths()
        if app_id not in apps:
            return {"ok": False, "error": "Joe doesn't know that app."}
        name = apps[app_id][0]
        if not on:
            r = connect_mod.disconnect(app_id)
            if r.get("ok") and app_id in self.settings.mcp_apps:
                self.settings.mcp_apps = [a for a in self.settings.mcp_apps if a != app_id]
                self.settings.save()
            return r
        link = connect_mod.deeplink(app_id, entry)
        if app_id == "claude" and how == "extension":
            from . import __version__
            f = connect_mod.mcpb_bundle(entry, self.sb.meta / "connector" / "Joe.mcpb", __version__)
            if not connect_mod.open_link(str(f)):
                return {"ok": False, "error": f"Couldn't open {f}. Double-click it, or drag it onto Claude Desktop."}
            r = {"ok": True, "say": "Claude Desktop is opening Joe's extension: press Install there. (If Joe was "
                                    "also connected the other way, press DISCONNECT afterwards so he's not there twice.)"}
        elif link:
            if not connect_mod.open_link(link):
                return {"ok": False, "error": f"Couldn't open {name}. Is it installed? You can paste the lines instead."}
            r = {"ok": True, "say": f"{name} is asking you to add Joe: press Install (or Add) there. Nothing in its "
                                    "files was touched by Joe."}
        elif app_id == "gemini" and not connect_mod.gemini_add(entry):
            r = {"ok": True, "say": "Added with Gemini CLI's own command (gemini mcp add). Start a new Gemini session to use Joe."}
        else:
            r = connect_mod.connect(app_id, entry)
        if r.get("ok") and app_id not in self.settings.mcp_apps:
            self.settings.mcp_apps = list(self.settings.mcp_apps) + [app_id]
            self.settings.save()
        return r

    def reminder_tick(self) -> None:
        """Reminders more than 3 days out go to ntfy once they're within its 3 days."""
        if not (self.settings.comfort.ntfy_topic or "").strip():
            return
        now = time.time()
        if now - getattr(self, "_rem_t", 0) < 600:
            return
        self._rem_t = now
        from . import reminders
        try:
            n = reminders.tick(self.sb, self.settings)
        except Exception as e:                      # noqa: BLE001 (never stop the background loop)
            self.log(f"Reminders: {e}")
            return
        if n:
            self.log(f"Sent {n} waiting reminder{'s' if n != 1 else ''} to your phone.")

    def dequeue(self, index: int) -> dict:
        with self.lock:
            if 0 <= index < len(self.queue):
                _, _, entry = self.queue.pop(index)
                if entry in self.run_log:
                    self.run_log.remove(entry)
                self._write_last_run()
                return {"ok": True}
        return {"ok": False, "error": "Not in the queue."}

    # -- fresh start / resume ---------------------------------------------------------
    def resume_offer(self) -> dict:
        if self.running:
            return {"offer": False}
        p = self.sb.meta / "last_run.json"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"offer": False}
        if data.get("dismissed"):
            return {"offer": False}
        left = [m for m in data.get("missions", []) if m.get("unfinished")]
        if not left:
            return {"offer": False}
        tasks = sum(len(m["unfinished"]) for m in left)
        return {"offer": True, "missions": len(left), "tasks": tasks,
                "names": [n for m in left for n in m["unfinished"]][:8],
                "when": data.get("started", "")}

    def resume(self, action: str) -> dict:
        p = self.sb.meta / "last_run.json"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"ok": False, "error": "Nothing to resume."}
        if action != "resume":
            data["dismissed"] = True                       # fresh start; history keeps it
            atomic_write_text(p, json.dumps(data, indent=1))
            return {"ok": True}
        started = 0
        for m in data.get("missions", []):
            if not m.get("unfinished"):
                continue
            f = self.sb.root / m["file"]
            if f.is_file():
                r = self.enqueue(f.read_text(encoding="utf-8", errors="replace"), only=m["unfinished"])
                started += bool(r.get("ok"))
        return {"ok": started > 0, "started": started,
                "error": "" if started else "The saved missions couldn't be found."}

    # -- history: revisit any past mission ---------------------------------------------
    def history(self, limit: int = 60) -> dict:
        out = []
        files = sorted(self.sb.missions.glob("mission_*.txt"), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files[:limit]:
            try:
                m = parse(f.read_text(encoding="utf-8", errors="replace"))
            except (MissionError, OSError):
                continue
            done = 0
            for j in m.jobs:
                st = self.sb.meta / "state" / f"{j.job_id}.json"
                try:
                    d = json.loads(st.read_text(encoding="utf-8"))
                    done += d.get("status") == "done" and d.get("spec_hash") == m.spec_hash(j)
                except (OSError, ValueError):
                    pass
            out.append({"file": str(f.relative_to(self.sb.root)).replace("\\", "/"),
                        "when": datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d-%y %H:%M"),
                        "label": self._label(m), "tasks": len(m.jobs), "done": done})
        return {"missions": out}

    def lists(self) -> dict:
        """Choices for the Builder's drop-downs."""
        def names(folder: Path, exts: tuple) -> list[str]:
            if not folder.is_dir():
                return []
            return sorted(f.name for f in folder.iterdir() if f.is_file() and f.suffix.lower() in exts
                          and not f.name.startswith(("_", ".")))
        try:
            imgs = [m.name for m in doctor.image_models(self.settings)]
        except Exception:
            imgs = []
        return {"projects": [Path(n).stem for n in names(self.sb.projects, (".md", ".txt"))],
                "workflows": names(self.sb.workflows, (".json",)),
                "inbox": names(self.sb.inbox, (".txt", ".md", ".csv", ".json")),
                "image_models": imgs}

    def session_log(self, n: int = 120) -> list[str]:
        """The Home screen's log: only what happened in this chat (a fresh chat starts empty)."""
        mine = max(0, min(len(self.logs), self.log_count - self.log_from))
        return list(self.logs)[len(self.logs) - mine:][-n:] if mine else []

    def new_session(self) -> dict:
        """A complete fresh start (Joe opening, or NEW CHAT): a new chat, an empty Home screen.
        Work that's still running stays on screen; it reports back to the chat it started in."""
        with self.lock:
            self.new_chat()
            self.mission_text = ""
            if self.running:
                return {"ok": True, "running": True}
            self.engine = None
            self.chain = []
            self.run_log = []
            self.log_from = self.log_count
        return {"ok": True, "running": False}

    def note_chat(self, msg: dict, title: str = "") -> str:
        try:
            return self.chats.note(msg, title)
        except OSError as e:
            self.log(f"Couldn't save this to the chat: {e}")
            return ""

    MEDIA_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".mp4", ".webm", ".mov")

    def media_of(self, states: list) -> list[str]:
        """Pictures and videos a run made, as Output/... paths. Media tasks list files from
        Output; tools list names inside their own folder."""
        out = []
        for st in states:
            for m in st.media_files:
                if not m.lower().endswith(self.MEDIA_EXT):
                    continue
                p = f"Output/{m}" if (self.sb.output / m).exists() or not st.output else f"Output/{st.output}/{m}"
                if p not in out:
                    out.append(p)
        return out

    def run_result(self, entry: dict, states: list, lines: list[str]) -> None:
        """When a mission ends: what happened, where the files are, the report and the log,
        saved into the chat the run started in."""
        if not entry.get("chat"):
            return
        tasks = [{"name": s.name, "status": s.status, "done": s.parts_done, "total": s.parts_total,
                  "output": ("Output/" + s.output) if s.output else "", "note": s.note,
                  "flags": len(s.flags)} for s in states]
        ok = sum(1 for t in tasks if t["status"] == "done")
        try:
            report = (self.sb.output / "_REPORT.md").read_text(encoding="utf-8")[:20000]
        except OSError:
            report = ""
        msg = {"who": "joe", "kind": "result",
               "text": f"Finished {entry['label']}: {ok} of {len(tasks)} task(s) done.",
               "tasks": tasks, "media": self.media_of(states)[:200], "report": report, "log": lines[-2000:]}
        try:
            self.chats.note_to(entry["chat"], msg)
        except OSError as e:
            self.log(f"Couldn't save the results to the chat: {e}")

    def plan_now(self, text: str) -> dict:
        from . import describe as describe_mod
        r = describe_mod.draft(self, text)
        if r.get("ok"):                          # the request and the plan go in this chat
            self.note_chat({"who": "you", "text": text.strip()[:4000]})
            self.note_chat({"who": "joe", "kind": "plan", "text": "Here's the plan (" + r["time"] + "):",
                            "summary": r["summary"], "mission": r["mission"]})
        return r

    def park_idea(self, idea: str) -> dict:
        """An idea saved for later, in the person's own words: Ideas.md in Joe's folder."""
        idea = " ".join((idea or "").split())
        if not idea:
            return {"ok": False, "error": "Say the idea after 'park this', like: park this: a recipe book for my mom."}
        p = self.sb.root / "Ideas.md"
        try:
            head = "" if p.exists() else "# Ideas for later\n\nParked with \"park this: ...\" in Joe's box.\n\n"
            with open(p, "a", encoding="utf-8") as f:
                f.write(head + f"- {datetime.now():%Y-%m-%d}: {idea}\n")
        except OSError as e:
            return {"ok": False, "error": f"Couldn't save it: {e}"}
        n = sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("- "))
        return {"ok": True, "count": n, "say": f"Parked. That's {n} idea{'s' if n != 1 else ''} in Ideas.md "
                                               "(Files, F7)."}

    def hold_plan(self, text: str) -> dict:
        """Joe is busy drawing (the graphics card is full): keep the request, plan it after."""
        from .chat import busy_drawing
        text = text.strip()
        if len(text) < 4:
            return {"ok": False, "error": "Tell Joe what you need first, in your own words."}

        def wait_then_plan():
            while busy_drawing(self) and self.held_plan.get("text") == text:
                time.sleep(3)
            if self.held_plan.get("text") != text:
                return                           # replaced or cancelled
            r = self.plan_now(text)
            if self.held_plan.get("text") == text:
                self.held_plan = {"text": text, "status": "ready", "result": r}
        self.held_plan = {"text": text, "status": "waiting"}
        threading.Thread(target=wait_then_plan, daemon=True).start()
        return {"ok": False, "held": True,
                "error": "Joe is busy drawing right now. He'll plan this as soon as the pictures "
                         "finish, and it'll show up here. You can leave it."}

    def state(self) -> dict:
        eng = self.engine
        jobs = []
        if eng:
            for s in eng.live:
                jobs.append({"id": s.job_id, "name": s.name, "status": s.status,
                             "parts_done": s.parts_done, "parts_total": s.parts_total,
                             "items": s.items, "words": s.words, "retries": s.retries,
                             "short": s.short_items, "flags": len(s.flags), "output": s.output,
                             "note": s.note, "current": s.job_id == eng.current,
                             "phase": s.phase, "media": bool(s.prompts),
                             "images_done": s.images_done})
        media = []                                   # newest pictures/videos from this run
        if eng:
            media += self.media_of(eng.live)
        for _, states in self.chain:
            media += [m for m in self.media_of(states) if m not in media]
        eta = None
        if self.running and eng:
            done = sum(j["parts_done"] for j in jobs) - self.parts_at_start
            left = sum(j["parts_total"] - j["parts_done"] for j in jobs
                       if j["status"] in ("pending", "running"))
            el = time.time() - self.run_started
            per = el / done if done > 0 else stats_mod.speeds(self.sb)["part"]
            eta = round(per * left)
        s = self.settings
        return {"version": __version__, "running": self.running,
                "stopping": self.running and self.stop.is_set(),
                "jobs": jobs, "eta_s": eta, "log": self.session_log(),
                "services": self.services_status, "workspace": str(self.sb.root),
                "engine_label": self.services.ollama.label if hasattr(self.services.ollama, "label") else "Ollama",
                "model": (getattr(eng, "text_model", "") if eng else "") or s.ollama.text_model or "auto",
                "ui": asdict(s.ui),
                "report": (self.sb.output / "_REPORT.md").exists(),
                "theme": self.theme_vars(), "hw": hardware.gpu(), "cpu_pct": hardware.cpu_pct(), "pause_c": s.engine.gpu_temp_pause_c,
                "busy": self.busy, "busy_pct": self.busy_pct, "fix_result": self.fix_result,
                "dl_all": {k: v for k, v in self.dl_all.items() if k != "stop"}, "restart_hint": self.restart_advice(),
                "attention": self.services.attention, "portable": portable_mod.active(),
                "queued": [e["label"] for _, _, e in self.queue],
                "queued_eta_s": 60 * sum(int(e.get("eta_min") or 0) for _, _, e in self.queue),
                "media": media[-12:][::-1],
                "chain": len(self.chain),
                "held_plan": {k: v for k, v in self.held_plan.items() if k != "thread"},
                "quiet": self.quiet(), "finished": self.finished,
                "comfort": {"screensaver_min": s.comfort.screensaver_min, "screensaver": s.comfort.screensaver}}

    def list_dir(self, rel: str) -> dict:
        p = self.rel_path(rel)
        if not p.is_dir():
            raise SandboxError("not a folder")
        entries = []
        for c in p.iterdir():
            try:
                st = c.stat()
            except OSError:
                continue
            entries.append({"name": c.name, "dir": c.is_dir(), "size": st.st_size,
                            "mtime": int(st.st_mtime), "hidden": c.name.startswith(".")})
        marks = media_mod.reviews(p)
        for e in entries:
            if e["name"] in marks:
                e["review"] = marks[e["name"]]
            ext = Path(e["name"]).suffix.lower()
            e["kind"] = ("image" if ext in IMAGE_TYPES else "video" if ext in VIDEO_TYPES else "")
        entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))
        return {"path": str(p.relative_to(self.sb.root)).replace("\\", "/").strip("."),
                "abs": str(p), "entries": entries,
                "ai": bool(media_mod.load(p).get("ai_generated"))}

    def preview(self, rel: str) -> dict:
        p = self.rel_path(rel)
        if not p.is_file():
            raise SandboxError("not a file")
        ext = p.suffix.lower()
        info = {"name": p.name, "size": p.stat().st_size, "abs": str(p)}
        if ext in IMAGE_TYPES or ext in VIDEO_TYPES:
            meta = media_mod.info(p.parent, p.name)
            return {**info, "kind": "image" if ext in IMAGE_TYPES else "video", "meta": meta}
        if ext in TEXT_TYPES or info["size"] < 200_000:
            raw = p.read_bytes()[:200_000]
            if b"\x00" not in raw[:4096]:
                return {**info, "kind": "text", "text": raw.decode("utf-8", "replace"),
                        "truncated": info["size"] > 200_000}
        return {**info, "kind": "binary"}

    def open_path(self, rel: str, how: str) -> dict:
        from . import system
        p = self.rel_path(rel)
        try:
            if how == "folder":
                system.reveal(p)
            elif how == "editor" and p.is_file():
                system.open_in_editor(p)
            elif p.exists():
                system.open_path(p)
        except OSError as e:
            return {"ok": False, "error": f"Couldn't open it: {e}"}
        return {"ok": True}

    def doctor_fix(self, b: dict) -> dict:
        """Run a System-check fix. The UI only sends approved=True after the user said yes."""
        if not b.get("approved"):
            return {"ok": False, "error": "Needs your OK first."}
        if self.busy:
            return {"ok": False, "error": f"Busy: {self.busy}"}
        action, tool, model = b.get("action"), b.get("tool", ""), b.get("model", "")
        if action == "mcp-fix":                    # RECONNECT an AI app that lost Joe or starts an old copy
            return self.connect_app(str(tool), True)
        if action == "get-engine":                 # another writing program: its own download page
            from . import textengines
            page = textengines.PAGES.get(textengines.engine_id(self.settings.ollama), "")
            if not page:
                return {"ok": False, "error": "No download page for that one: get it from its own site."}
            import webbrowser
            webbrowser.open(page)
            self.log(f"Opened {page} in your browser.")
            return {"ok": True}
        if action == "use-ollama":
            if self.running:
                return {"ok": False, "error": "Can't change the writing program during a run."}
            self.settings.ollama.engine = "ollama"
            self.settings.save()
            self.services = ServiceManager(self.settings, log=self.log)
            self.log("Writing program set back to Ollama.")
            return {"ok": True}
        if action == "use":
            if self.running:
                return {"ok": False, "error": "Can't change the model during a run."}
            self.settings.ollama.text_model = model
            self.settings.save()
            self.log(f"Text model set to {model}.")
            return {"ok": True}

        def prog(pct):
            self.busy_pct = round(pct, 1)

        def work():
            ok = True
            try:
                if action == "install":
                    ok = doctor.install(tool, self.log, approved=True)
                    if ok and tool == "comfyui":
                        self.log("Tip: so ComfyUI Desktop doesn't stop on its start screen each time, "
                                 "set ComfyUI menu (☰, top left) > Desktop Settings > Auto-launch on "
                                 "startup > your install, once it has finished setting up.")
                    if ok and tool in ("ollama", "comfyui"):
                        (self.services.ensure_ollama if tool == "ollama" else self.services.ensure_comfy)()
                elif action == "start":
                    (self.services.ensure_ollama if tool == "ollama" else self.services.ensure_comfy)()
                elif action == "update":
                    from . import upkeep
                    ok = (upkeep.update_ollama(self.log) if tool == "ollama"
                          else upkeep.install_comfy_own(self.log, progress=prog))
                    if ok:
                        upkeep.forget_updates()
                        self.log(f"{tool} is up to date." + (" Restart ComfyUI so it uses the new version."
                                                            if tool == "comfyui" and self.services.comfy_up() else ""))
                elif action == "pull":
                    if doctor.pull_ollama_model(self.services, model, self.log, approved=True, progress=prog):
                        if b.get("keep"):                              # refreshed an installed model
                            from . import upkeep
                            upkeep.forget_updates()
                        elif b.get("set") == "talk":                    # the quick Talk model
                            self.settings.voice.talk_model = model
                            self.settings.save()
                            self.log(f"Talk now uses {model} for quicker replies (Setup > Voice & Talk).")
                        elif (not self.running and self.settings.ollama.text_model
                                and b.get("id") not in ("pull-vision", "pull-small-model", "pull-embed")):
                            self.settings.ollama.text_model = model
                            self.settings.save()
                elif action == "download-image-model":
                    ok = doctor.download_image_model(self.settings, self.log, approved=True, progress=prog)
                elif action == "download-video-model":
                    ok = doctor.download_video_model(self.settings, self.log, approved=True, progress=prog)
                elif action == "download-video-turbo":
                    ok = doctor.download_video_turbo(self.settings, self.log, approved=True, progress=prog)
                elif action == "install-voice":
                    self.voice.close()
                    ok = addons_mod.install_voice(addons_mod.install_log(self.log), approved=True,
                                             stt_model=self.settings.voice.stt_model, progress=prog)
                elif action == "install-clone":
                    self.clone.close()
                    ok = addons_mod.install_clone(addons_mod.install_log(self.log), approved=True)
                elif action == "install-pandoc":
                    ok = addons_mod.install_pandoc(addons_mod.install_log(self.log), approved=True)
                elif action == "download-pack":
                    from . import picturetools
                    ok = picturetools.download_pack(self.settings, b.get("pack", ""), self.log,
                                                    approved=True, progress=prog)
                    if ok and self.services.comfy_up():
                        self.log("Restart ComfyUI (close and reopen it) so it sees the new model.")
                elif action == "install-whispercpp":
                    from . import whispercpp
                    ok = whispercpp.install(self.log, approved=True, progress=prog)
                    if ok:
                        whispercpp.get_model(self.settings.voice.stt_model or "base.en", self.log, prog)
                elif action == "share-models":
                    from . import sharedmodels
                    ok = bool(sharedmodels.share(self.services.comfy_install(), sharedmodels.find_webuis(), self.log))
                elif action == "import-models":
                    from . import stylemodels
                    mdir = doctor.comfy_models_dir(self.settings)
                    if stylemodels.found(mdir):
                        ok = stylemodels.import_downloads(mdir, self.log) > 0
                        if ok and self.services.comfy_up():
                            self.log("Restart ComfyUI (close and reopen it) so it sees the new model.")
                    elif b.get("page", "").startswith(stylemodels.PAGE_HOSTS):
                        import webbrowser
                        link = stylemodels.download_link(b["page"], file=str(b.get("file") or ""))
                        if link != b["page"]:
                            webbrowser.open(b["page"])          # the license and model card
                        webbrowser.open(link)
                        if "/resolve/" in link:
                            self.log("Opened the model's page (license) and started the download in your "
                                     "browser. When it's finished, press GET IT again and Joe moves it "
                                     "into ComfyUI.")
                        else:
                            self.log(f"Opened {link}. Read its license, download the .safetensors file "
                                     "there (into your Downloads folder), then press GET IT again and Joe "
                                     "moves it into ComfyUI.")
                    else:
                        self.log("No picture model files found in your Downloads folder.")
                        ok = False
                elif action == "update-joe":
                    from . import update as update_mod
                    info = update_mod.check()
                    f = update_mod.download(info, self.log, progress=prog) if info.get("newer") else None
                    ok = bool(f) and update_mod.launch(f, info.get("kind", "source"), self.log)
                    if ok and info.get("kind") in ("windows-installer", "linux-appimage"):
                        self.last_seen = 0.0                 # step aside so the new Joe can start
                        self.quit_now = True
                self.refresh_services()
            except Exception as e:      # report, never crash the server
                ok = False
                addons_mod.install_log(self.log)(f"!! {action} failed: {e!r}")
            finally:
                self.fix_result = {"action": action, "ok": bool(ok), "n": self.fix_result.get("n", 0) + 1}
                self.busy, self.busy_pct = "", None
        labels = {"install": f"installing {tool}", "start": f"starting {tool}", "update": f"updating {tool}",
                  "pull": f"downloading {model}", "download-image-model": "downloading image model",
                  "download-video-model": "downloading video model",
                  "download-video-turbo": "downloading the Turbo add-on",
                  "install-voice": "setting up Joe's voice", "install-pandoc": "installing Pandoc",
                  "install-clone": "setting up voice copy", "update-joe": "updating Joe",
                  "download-pack": "downloading a picture/sound model",
                  "import-models": "getting a picture model",
                  "share-models": "sharing model folders with ComfyUI",
                  "install-whispercpp": "installing whisper.cpp"}
        if action == "download-pack":
            from . import picturetools
            if b.get("pack") not in picturetools.PACKS:
                return {"ok": False, "error": "unknown model"}
        if action == "update-joe" and self.running:
            return {"ok": False, "error": "Joe is working: update after the run finishes."}
        if action not in labels:
            return {"ok": False, "error": "unknown fix"}
        self.busy = labels[action]
        doctor.run_in_thread(work)
        return {"ok": True, "started": self.busy}

    def restart_advice(self) -> str:
        """Why Joe must restart now ('' = he needn't): newer Joe files copied into his folder, or
        restart_hint set by something that truly can't be picked up live. Installs (voice, whisper.cpp,
        Ollama, ComfyUI) and model downloads are picked up without a restart, so they don't set it."""
        now = time.monotonic()
        if now - getattr(self, "_disk_checked", 0) > 30:
            self._disk_checked = now
            try:
                txt = (Path(__file__).parent / "__init__.py").read_text(encoding="utf-8")
                m = re.search(r'__version__\s*=\s*"([^"]+)"', txt)
                self._disk_version = m.group(1) if m else __version__
            except OSError:
                self._disk_version = __version__
        disk = getattr(self, "_disk_version", __version__)
        if disk != __version__:
            return (f"A newer Joe ({disk}) is in his folder; this window is still {__version__}. "
                    "Restart Joe to use the new one.")
        return self.restart_hint

    # -- Setup > Models > DOWNLOAD ALL: every offered model, one after another -------------
    DL_ALL_ACTIONS = ("pull", "download-image-model", "download-video-model", "download-video-turbo",
                      "download-pack")

    def download_all_items(self) -> list[dict]:
        """The model downloads System check offers now (no program installs, no browser ones)."""
        d = doctor.check(self.settings, self.services)
        return [it for it in d["issues"] if it.get("kind") and it.get("action") in self.DL_ALL_ACTIONS
                and it.get("group") != "updates"]

    def download_all(self, b: dict) -> dict:
        if not b.get("approved"):
            return {"ok": False, "error": "Needs your OK first."}
        if self.busy or self.dl_all.get("running"):
            return {"ok": False, "error": f"Busy: {self.busy or 'downloading'}"}
        skip = set(b.get("skip") or [])
        self.dl_all = {"running": True, "done": 0, "failed": [], "current": "", "stop": False}

        def work():
            tried: set[str] = set(skip)
            comfy_new = 0
            with system.keep_awake(True, self.log):
                self.log("DOWNLOAD ALL: getting every model Joe offers, one at a time. Leave Joe open; "
                         "the PC won't go to sleep until it's done.")
                while not self.dl_all.get("stop"):
                    todo = [it for it in self.download_all_items()
                            if (it.get("id", "") + it.get("model", "") + it.get("pack", "")) not in tried]
                    if not todo:
                        break                        # follow-on models appear after earlier ones land
                    it = todo[0]
                    key = it.get("id", "") + it.get("model", "") + it.get("pack", "")
                    tried.add(key)
                    self.dl_all["current"] = it.get("what") or it.get("text", "")[:80]
                    self.dl_all["left"] = len(todo) - 1
                    r = self.doctor_fix({**it, "approved": True})
                    if not r.get("ok"):
                        self.dl_all["failed"].append(f"{self.dl_all['current']}: {r.get('error')}")
                        continue
                    time.sleep(1)
                    while self.busy:
                        time.sleep(2)
                    if self.fix_result.get("ok"):
                        self.dl_all["done"] += 1
                        comfy_new += it.get("action") != "pull"     # Ollama sees new models by itself
                    else:
                        self.dl_all["failed"].append(self.dl_all["current"])
            n, bad = self.dl_all["done"], self.dl_all["failed"]
            self.log(f"DOWNLOAD ALL finished: {n} downloaded" + (f", {len(bad)} didn't work: " + "; ".join(bad)
                                                                 if bad else "") + ".")
            if comfy_new:          # ComfyUI needs the restart, not Joe: no RESTART JOE bar for this
                self.log("Restart ComfyUI (close and reopen it) so it sees the new picture/video/sound models.")
            self.dl_all = {"running": False, "done": n, "failed": bad, "current": "", "finished": True}

        doctor.run_in_thread(work)
        return {"ok": True, "started": "downloading every model"}

    def theme_vars(self) -> dict | None:
        ph = self.settings.ui.phosphor
        if not ph.startswith("custom:"):
            return None
        for t in themes_mod.list_themes(self.sb.themes):
            if t["id"] == ph[7:]:
                return t["vars"]
        return None

    def make_saver(self, desc: str) -> dict:
        """CUSTOM SCREEN SAVER: the local model picks an animation, colors, speed and words."""
        if self.running:
            return {"ok": False, "error": "Wait until the run finishes (the model is busy)."}
        if not self.services.handoff("text"):
            return {"ok": False, "error": "The writing program isn't running (F10 > System check)."}
        from . import savers
        from .doctor import resolve_text_model
        model = resolve_text_model(self.settings, self.services, self.log)
        try:
            sv = savers.generate(self.services.ollama, model, desc)
        except (ValueError, OSError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:                       # noqa: BLE001
            return {"ok": False, "error": f"model call failed: {e}"}
        sid = savers.save(self.sb.themes, sv)
        self.log(f"New screen saver '{sv['name']}' saved to Themes/savers/{sid[7:]}.json")
        return {"ok": True, "id": sid, "saver": {**sv, "id": sid}}

    def make_theme(self, desc: str) -> dict:
        if self.running:
            return {"ok": False, "error": "Wait until the run finishes (the model is busy)."}
        if not self.services.handoff("text"):
            return {"ok": False, "error": "Ollama isn't running (F10 > System check)."}
        from .doctor import resolve_text_model
        model = resolve_text_model(self.settings, self.services, self.log)
        try:
            t = themes_mod.generate(self.services.ollama, model, desc)
        except (ValueError, OSError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": f"model call failed: {e}"}
        tid = themes_mod.save(self.sb.themes, t)
        self.log(f"New theme '{t['name']}' saved to Themes/{tid}.json")
        return {"ok": True, "id": tid, "theme": t, "vars": themes_mod.css_vars(t)}

    # -- speed test: one real batch, so time estimates fit this PC ---------------------
    def speed_test(self) -> dict:
        if self.running:
            return {"ok": False, "error": "Joe is busy with a run; its timings teach him anyway."}
        if not self.services.ensure_ollama():
            return {"ok": False, "error": "Ollama isn't running (Setup > System check)."}
        from .doctor import resolve_text_model
        model = resolve_text_model(self.settings, self.services, self.log)
        try:
            self.services.ollama.warm(model)               # loading the model isn't part of the speed
        except Exception:
            pass
        msgs = [{"role": "system", "content": "You write short, plain product copy."},
                {"role": "user", "content": "Write exactly 5 NEW item(s) about handmade ceramic mugs. "
                 "Begin each item with a line: ## <title>. Then about 60 words."}]
        try:
            r = self.services.ollama.chat(msgs, model=model, keep_alive="20m")
        except Exception as e:
            return {"ok": False, "error": f"the model didn't answer: {e}"}
        secs = round(r.seconds, 1)
        self.sb.meta.mkdir(parents=True, exist_ok=True)
        with open(self.sb.meta / "runs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": "speedtest", "ok": True, "model": model, "seconds": secs,
                                "tokens_out": r.output_tokens,
                                "ts": datetime.now().isoformat(timespec="seconds")}) + "\n")
        per100 = max(1, round(secs * 1.15 * 20 / 60))
        return {"ok": True, "seconds": secs, "model": model,
                "text": f"A batch of 5 items took {secs:g} seconds with {model}. "
                        f"So 100 items takes about {per100} minute{'s' if per100 != 1 else ''} on this PC."}

    # -- talking to Joe ------------------------------------------------------------
    @property
    def chats(self) -> Chats:
        d = self.sb.meta / "chats"
        if self._chats is None or self._chats.dir != d:     # workspace moved: follow it
            self._chats = Chats(d)
        return self._chats

    def save_chat(self, you: str, r: dict) -> None:
        try:
            self.chats.add(you, r.get("say", ""), r.get("mission", ""), r.get("sources"))
        except OSError as e:
            self.log(f"Couldn't save this chat: {e}")

    def open_chat(self, cid: str) -> dict | None:
        d = self.chats.open(cid)
        if not d:
            return None
        hist = []
        for m in d.get("messages", [])[-20:]:
            text = m.get("text", "")
            if m.get("mission"):
                text += "\n" + m["mission"]
            hist.append({"role": "assistant" if m.get("who") == "joe" else "user", "content": text})
        self.chat_history = hist
        return d

    def new_chat(self) -> None:
        self.chat_history = []
        self.chats.new()
        try:
            self.chats.prune(self.settings.voice.chat_keep_days)
        except OSError:
            pass

    def talk(self, text: str) -> dict:
        r = chat_mod.reply(self, self.chat_history, text)
        if r.get("ok"):
            self.chat_history += [{"role": "user", "content": text},
                                  {"role": "assistant", "content": r.pop("raw", r["say"])}]
            self.chat_history = self.chat_history[-20:]
            self.save_chat(text, r)
        return r

    def warm_talk(self) -> None:
        """When Talk opens, load the thinking model and the voice models in the background,
        so the first question doesn't wait for them."""
        def work():
            try:
                if not self.running and self.services.ollama_up():
                    self.services.ollama.warm(chat_mod.talk_model(self))
            except Exception:
                pass
            if addons_mod.voice_ready():
                self.voice.call({"cmd": "warmup", "stt_model": self.settings.voice.stt_model}, timeout=300)
        threading.Thread(target=work, daemon=True, name="joe-warm").start()

    def listen(self, audio: bytes, ext: str) -> dict:
        if not addons_mod.voice_ready():
            return {"ok": False, "error": "Joe's voice isn't set up yet (F10 > System check)."}
        d = addons_mod.voice_dir() / "tmp"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"heard_{int(time.time() * 1000)}.{ext}"
        f.write_bytes(audio)
        try:
            t0 = time.monotonic()
            r = self.voice.call({"cmd": "stt", "audio": str(f), "stt_model": self.settings.voice.stt_model},
                                timeout=180)
            self.debug(f"Talk timing: hearing {time.monotonic() - t0:.1f}s ({self.settings.voice.stt_model})")
        finally:
            try:
                f.unlink()                           # never keep recordings
            except OSError:
                pass
        return r

    def speak(self, text: str) -> tuple[bytes, str]:
        if not addons_mod.voice_ready():
            return b"", "Joe's voice isn't set up yet (F10 > System check)."
        d = addons_mod.voice_dir() / "tmp"
        d.mkdir(parents=True, exist_ok=True)
        out = d / f"say_{int(time.time() * 1000)}.wav"
        v = self.settings.voice
        r = None
        t0 = time.monotonic()
        if v.voice == "mine" and addons_mod.has_my_voice() and addons_mod.clone_ready() and not self.running:
            r = self.clone.call({"cmd": "tts", "text": text[:4000], "out": str(out),
                                 "ref": str(addons_mod.my_voice_path())}, timeout=600)
            if not r.get("ok"):
                self.log(f"Voice copy failed ({r.get('error')}); using the built-in voice.")
                r = None
        if r is None:                 # built-in voice (also while a run uses the graphics card)
            voice = v.voice if v.voice in addons_mod.VOICES else "am_adam"
            r = self.voice.call({"cmd": "tts", "text": text[:6000], "out": str(out), "voice": voice,
                                 "speed": v.speed}, timeout=300)
        if len(text) < 400:                                   # one sentence of a streamed reply
            self.debug(f"Talk timing: speaking {time.monotonic() - t0:.1f}s for {len(text)} letters")
        try:
            if not r.get("ok"):
                return b"", r.get("error", "Joe lost his voice")
            return out.read_bytes(), ""
        finally:
            try:
                out.unlink()
            except OSError:
                pass

    def hello_audio(self) -> tuple[bytes, str]:
        """Joe's spoken hello when he opens. Made once per voice/speed/words and kept, so it
        plays straight away instead of waiting for the voice to warm up."""
        if self.quiet():
            return b"", "quiet hours"
        text = (self.settings.ui.hello_text or "").strip()[:200]
        if not text:
            return b"", "no hello text"
        v = self.settings.voice
        import hashlib
        mine = ""                     # "my voice": a new recording means a new hello
        if v.voice == "mine":
            try:
                mine = str(addons_mod.my_voice_path().stat().st_mtime)
            except OSError:
                pass
        key = hashlib.sha1(f"{v.voice}|{v.speed}|{mine}|{text}".encode()).hexdigest()[:16]
        cache = config_dir() / "hello" / f"{key}.wav"
        try:
            if cache.exists():
                return cache.read_bytes(), ""
        except OSError:
            pass
        audio, err = self.speak(text)
        if audio:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                for old in cache.parent.glob("*.wav"):        # only keep the current one
                    old.unlink()
                cache.write_bytes(audio)
            except OSError:
                pass
        return audio, err

    def import_workflow(self, text: str, name: str, style: str) -> dict:
        """Save a ComfyUI workflow (API format) into Workflows/. With a style it becomes
        style-<style>.json, which Joe uses for every picture of that style."""
        from . import styles
        try:
            g = comfy_mod.parse_template(text or "", name or "workflow")
        except comfy_mod.WorkflowError as e:
            return {"ok": False, "error": str(e)}
        problem = comfy_mod.check_template(g)
        if problem:
            return {"ok": False, "error": problem}
        style = (style or "").strip().lower()
        if style and (style not in styles.STYLES or style == "general"):
            return {"ok": False, "error": "unknown style"}
        stem = f"style-{style}" if style else re.sub(r"[^\w\- ]+", "", Path(name or "workflow").stem).strip()[:60]
        dest = self.sb.workflows / f"{stem or 'workflow'}.json"
        self.sb.workflows.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(g, indent=2), encoding="utf-8")
        what = f"used for {styles.STYLES[style].label} pictures" if style else "pick it per task (WORKFLOW line or Step by step)"
        self.log(f"Workflow saved: Workflows/{dest.name} ({what}).")
        return {"ok": True, "file": dest.name, "message": f"Saved as Workflows/{dest.name}: {what}."}

    def export(self, rel: str, formats: list[str]) -> dict:
        p = self.rel_path(rel)
        if not p.is_file() or p.suffix.lower() not in (".md", ".txt"):
            return {"ok": False, "error": "Pick a .md or .txt file to turn into a document."}
        pandoc = addons_mod.pandoc_exe(self.settings.pandoc)
        if not pandoc:
            return {"ok": False, "error": "Pandoc isn't installed (F10 > System check)."}
        made = addons_mod.export_document(p, formats, pandoc, self.log, settings=self.settings,
                                          cache=self.sb.meta / "templates")
        return {"ok": bool(made), "made": [m.name for m in made],
                "error": "" if made else "Couldn't make the document (see the log on F2)."}

    def to_mp4(self, rel: str) -> dict:
        p = self.rel_path(rel)
        ff = doctor.ffmpeg_exe(self.settings.comfy.ffmpeg)
        if not ff:
            return {"ok": False, "error": "FFmpeg not found (F10 > System check can install it)."}
        if not p.is_file() or p.suffix.lower() not in (".gif", ".webp", ".webm", ".mov", ".mkv", ".mp4"):
            return {"ok": False, "error": "Pick a GIF, WebP or video file."}
        out = media_mod.to_mp4(ff, p)
        if not out:
            return {"ok": False, "error": "FFmpeg couldn't convert that file."}
        meta = media_mod.info(p.parent, p.name)
        if meta:
            media_mod.record(p.parent, out.name, {**meta, "converted_from": p.name})
        return {"ok": True, "name": out.name}

    def save_settings(self, data: dict) -> dict:
        if self.running:
            return {"ok": False, "error": "Can't change settings during a run."}
        from . import schedule
        times = schedule.check_times(data or {})
        if times.get("error"):
            return {"ok": False, "error": times["error"]}
        if times.get("fixes"):                       # "7am" -> "07:00": ask before saving it that way
            return {"ok": False, "fixes": times["fixes"],
                    "error": "Joe needs times on the 24-hour clock. Check the change and save again."}
        old_ws = self.settings.workspace_path
        old_sched = (self.settings.schedule.enabled, self.settings.schedule.time, self.settings.schedule.stop)
        _merge(self.settings, data)
        return self._settings_changed(old_ws, old_sched)

    def reset_settings(self, paths: list[str] | None) -> dict:
        """Setup > RESET THIS PAGE (the page's settings) or RESET ALL SETTINGS (paths None)."""
        if self.running:
            return {"ok": False, "error": "Can't change settings during a run."}
        from .config import reset_paths
        old_ws = self.settings.workspace_path
        old_sched = (self.settings.schedule.enabled, self.settings.schedule.time, self.settings.schedule.stop)
        changed = reset_paths(self.settings, paths)
        if paths is None:
            self.settings.workflows = {}
        r = self._settings_changed(old_ws, old_sched)
        if r.get("ok"):
            r["changed"] = len(changed)
            self.log(f"Settings reset to how Joe came ({'all' if paths is None else len(changed)} "
                     f"setting{'s' if paths is None or len(changed) != 1 else ''}).")
        return r

    def _settings_changed(self, old_ws, old_sched) -> dict:
        from . import schedule
        sc = self.settings.schedule
        if (sc.stop or "").strip() and not schedule.parse_time(sc.stop):    # checked even with the night shift off
            sc.stop = old_sched[2] if len(old_sched) > 2 else ""
            return {"ok": False, "error": "Stop by should look like 07:00 (24-hour clock), or leave it blank."}
        self.settings.save()
        if self.settings.workspace_path != old_ws:
            self.sb = Sandbox(self.settings.workspace_path).ensure()
        if self.settings.schedule.watch:
            self.watch_setup()
        self.services = ServiceManager(self.settings, log=self.log)
        self.phone.apply()                   # Setup > Phone turned on/off or a new port
        if (self.settings.schedule.enabled, self.settings.schedule.time, self.settings.schedule.stop) != old_sched:
            from . import schedule
            r = schedule.apply(self.settings, self.log)
            if not r.get("ok"):
                self.settings.schedule.enabled = False
                self.settings.save()
                return {"ok": False, "error": r.get("error", "Couldn't set the night shift.")}
        return {"ok": True}


# ---------------------------------------------------------------------------
def disk_need(m, sb) -> int:
    """A rough upper guess of the bytes a mission makes: text is tiny, pictures a few MB, video
    clips tens of MB, tools about twice their input files (copies, cut-outs, frames)."""
    need = 0
    for j in m.jobs:
        if j.tool:
            for x in j.inputs or []:
                try:
                    need += 2 * (sb.inbox / x).stat().st_size
                except (OSError, TypeError):
                    continue
            need += 50_000_000
        elif j.type == "video":
            need += max(1, j.parts * j.part_size) * max(1, j.variants) * 40_000_000
        elif j.media:
            need += max(1, j.parts * j.part_size) * max(1, j.variants) * 4_000_000
        else:
            need += j.parts * 200_000
    return need


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        server_version = "Joe"

        def log_message(self, *a):
            pass

        # -- plumbing --
        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost")

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _authed(self, q: dict) -> bool:
            tok = self.headers.get("X-NR-Token") or (q.get("t") or [""])[0]
            return secrets.compare_digest(tok, app.token)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 2_000_000:
                return {}
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return {}

        # -- routes --
        def do_GET(self):
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            u = urlparse(self.path)
            q = parse_qs(u.query)
            app.last_seen = time.monotonic()
            if u.path in ("/", "/index.html"):
                html = (UI_DIR / "index.html").read_text(encoding="utf-8")
                html = html.replace("__INTRO__", "1" if app.settings.ui.intro else "0")
                return self._send(200, html.replace("__TOKEN__", app.token).encode(),
                                  "text/html; charset=utf-8",
                                  {"Content-Security-Policy":
                                   "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; "
                                   "style-src 'self' 'unsafe-inline'; "
                                   "font-src 'self'; script-src 'self'"})
            if u.path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if u.path == "/sounds/intro.wav":            # Joe's 8-bit intro jingle
                return self._send(200, (UI_DIR / "sounds" / "intro.wav").read_bytes(), "audio/wav")
            if u.path.startswith("/fonts/"):               # fonts shipped with Joe (OFL)
                name = u.path[len("/fonts/"):]
                f = UI_DIR / "fonts" / name
                if "/" not in name and "\\" not in name and f.suffix in (".ttf", ".css") and f.is_file():
                    return self._send(200, f.read_bytes(),
                                      "font/ttf" if f.suffix == ".ttf" else "text/css; charset=utf-8")
                return self._send(404, b"not found", "text/plain")
            if u.path in ("/app.css", "/app.js"):
                f = UI_DIR / u.path.lstrip("/")
                ctype = "text/css" if f.suffix == ".css" else "text/javascript"
                return self._send(200, f.read_bytes(), ctype + "; charset=utf-8")
            if not self._authed(q):
                return self._json({"error": "bad token"}, 401)
            arg = (q.get("path") or [""])[0]
            try:
                if u.path == "/api/ping":
                    from .update import install_kind
                    return self._json({"ok": True, "version": __version__, "running": app.running,
                                       "install_kind": install_kind()})
                if u.path == "/api/state":
                    return self._json(app.state())
                if u.path == "/api/mission":
                    return self._json({"text": app.mission_text})
                if u.path == "/api/files":
                    return self._json(app.list_dir(arg))
                if u.path == "/api/preview":
                    return self._json(app.preview(arg))
                if u.path == "/api/report":
                    p = app.sb.output / "_REPORT.md"
                    return self._json({"text": p.read_text(encoding="utf-8") if p.exists() else ""})
                if u.path == "/api/settings":
                    return self._json(asdict(app.settings))
                if u.path == "/api/storage":
                    return self._json(storage_mod.usage(app.settings, app.sb))
                if u.path == "/api/stats":
                    return self._json(stats_mod.collect(app.settings, app.sb, (q.get("period") or ["all"])[0]))
                if u.path == "/api/chats":
                    return self._json({"chats": app.chats.list((q.get("q") or [""])[0]), "bytes": app.chats.size(),
                                       "current": (app.chats.current or {}).get("id", ""),
                                       "keep_days": app.settings.voice.chat_keep_days})
                if u.path == "/api/history":
                    return self._json(app.history())
                if u.path == "/api/models":               # Setup > System check > Your models
                    from . import stylemodels
                    from .doctor import comfy_models_dir, ollama_models
                    try:
                        from .upkeep import picks as _p
                        pk = _p()
                    except Exception:                    # noqa: BLE001
                        pk = None
                    return self._json(stylemodels.inventory(comfy_models_dir(app.settings),
                                                            ollama_models(app.services), pk))
                if u.path == "/api/phone":                 # Setup > Phone: on?, address, paired phones
                    return self._json(app.phone.info())
                if u.path == "/api/lists":
                    return self._json(app.lists())
                if u.path == "/api/resume":
                    return self._json(app.resume_offer())
                if u.path == "/api/voice/status":
                    return self._json({**addons_mod.status(), "settings": asdict(app.settings.voice)})
                if u.path == "/api/themes":
                    return self._json({"themes": themes_mod.list_themes(app.sb.themes)})
                if u.path == "/api/tools":                # the Tools tab's cards
                    from . import tools as tools_mod
                    from .doctor import ffmpeg_exe
                    voice = Path(addons_mod.voice_python()).exists()
                    vision = None                        # unknown while Ollama is off
                    if app.services.ollama_up():
                        from .attach import vision_model
                        from .doctor import ollama_models
                        vision = bool(vision_model(ollama_models(app.services)))
                    from . import picturetools
                    from .doctor import comfy_models_dir
                    try:
                        mdir = comfy_models_dir(app.settings)
                    except Exception:                   # noqa: BLE001
                        mdir = None
                    packs = {p: {"ready": picturetools.pack_ready(mdir, p), "offer": picturetools.pack_offer(p, mdir),
                                 "short": picturetools.pack_short(p, mdir)} for p in picturetools.PACKS}
                    from .doctor import find_ollama_exe
                    have = {"voice": voice, "vision": vision,
                            "whispercpp": tools_mod.hearing_backend(app.settings) == "whisper.cpp",
                            "ffmpeg": bool(ffmpeg_exe(app.settings.comfy.ffmpeg)),
                            "ollama": app.services.ollama_up() or bool(find_ollama_exe(app.settings.ollama.exe))
                            or app.services.engine != "ollama",
                            "comfy": bool(mdir), "packs": packs,
                            "sdxl": tools_mod.sdxl_installed(mdir) if mdir else None}
                    return self._json({"tools": tools_mod.catalog(), "groups": list(tools_mod.GROUPS),
                                       "have": have, "status": tools_mod.tool_status(have)})
                if u.path == "/api/update":
                    from . import update as update_mod
                    if q.get("auto") and not app.settings.ui.check_updates:
                        return self._json({"ok": False, "off": True})
                    if q.get("force"):                    # the button: helpers and models too
                        from . import upkeep
                        upkeep.check_in_background(app.services.ollama.base,
                                                   doctor.ollama_models(app.services) if app.services.ollama_up() else [],
                                                   force=True)
                    return self._json(update_mod.check(force=bool(q.get("force"))))
                if u.path == "/api/doctor":
                    return self._json(doctor.check(app.settings, app.services))
                if u.path == "/raw":
                    return self._raw(app.rel_path(arg))
                if u.path == "/player":                  # a picture or video in its own window
                    p = app.rel_path(arg)
                    if not p.is_file():
                        return self._json({"error": "not a file"}, 404)
                    from html import escape
                    from urllib.parse import quote
                    src = f"/raw?t={quote(app.token)}&path={quote(arg)}"
                    vid = p.suffix.lower() in VIDEO_TYPES
                    tag = (f'<video src="{escape(src)}" controls autoplay loop playsinline></video>' if vid
                           else f'<img src="{escape(src)}" alt="">')
                    page = (f"<!doctype html><meta charset=utf-8><title>{escape(p.name)} - Joe</title>"
                            "<style>html,body{margin:0;height:100%;background:#000;color:#39ff6a;"
                            "font:14px Consolas,monospace}body{display:grid;place-items:center}"
                            "video,img{max-width:100vw;max-height:calc(100vh - 24px)}"
                            "p{position:fixed;bottom:0;left:0;right:0;margin:0;padding:3px 8px;"
                            "background:#000c}</style>" + tag +
                            f"<p>AI-GENERATED · {escape(p.name)}</p>")
                    return self._send(200, page.encode(), "text/html; charset=utf-8",
                                      {"Content-Security-Policy": "default-src 'none'; img-src 'self'; "
                                       "media-src 'self'; style-src 'unsafe-inline'"})
            except (SandboxError, OSError) as e:
                return self._json({"error": str(e)}, 400)
            self._json({"error": "not found"}, 404)

        do_HEAD = do_GET

        def _mcp_http(self):
            """MCP Streamable HTTP (JSON replies). Needs 'Authorization: Bearer <key>' (Setup >
            General shows it), so a web page in a browser can't drive Joe."""
            import secrets as _sec
            key = app.settings.mcp_key
            got = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            if not key or not got or not _sec.compare_digest(got, key):
                return self._json({"error": "Joe's connector key is missing or wrong (Setup > General)."}, 401)
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= 2_000_000:
                return self._json({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "empty"}}, 400)
            try:
                msg = json.loads(self.rfile.read(n))
            except ValueError:
                return self._json({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, 400)
            from . import mcp as mcp_mod
            joe = mcp_mod.Joe(app.settings)
            joe.sb = app.sb
            if isinstance(msg, list):
                out = [r for r in (mcp_mod.handle(joe, m) for m in msg if isinstance(m, dict)) if r is not None]
                return self._send(202, b"", "application/json") if not out else self._json(out)
            reply = mcp_mod.handle(joe, msg) if isinstance(msg, dict) else None
            if reply is None:
                return self._send(202, b"", "application/json")
            return self._json(reply)

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            u = urlparse(self.path)
            if u.path == "/mcp":                        # Joe's connector over HTTP, for AI apps on this PC
                return self._mcp_http()
            if not self._authed({}):
                return self._json({"error": "bad token"}, 401)
            app.last_seen = time.monotonic()
            if u.path == "/api/voice/myvoice":          # the user's own voice sample (WAV)
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 < n <= 20_000_000:
                    return self._json({"ok": False, "error": "recording too long"})
                err = addons_mod.save_my_voice(self.rfile.read(n), self.headers.get("X-Consent") == "my-own-voice")
                if not err:
                    app.settings.voice.voice = "mine"
                    app.settings.save()
                    app.log("Saved your voice sample (stays on this PC). Joe will use it when he talks.")
                return self._json({"ok": not err, "error": err})
            if u.path == "/api/voice/memory":           # A VOICE TO REMEMBER: a family recording is the body
                from urllib.parse import unquote
                from . import avtools
                from .doctor import ffmpeg_exe
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 < n <= 500_000_000:
                    return self._json({"ok": False, "error": "That file is empty or too big (500 MB at most)."})
                promises = {x.strip() for x in (self.headers.get("X-Promises") or "").split(",")}
                name = unquote(self.headers.get("X-Name") or "").strip()
                if set(addons_mod.MEMORY_PROMISES) - promises:
                    return self._json({"ok": False, "error": "Please tick all three promises first."})
                ff = ffmpeg_exe(app.settings.comfy.ffmpeg)
                if not ff:
                    return self._json({"ok": False, "error": "This needs FFmpeg (Setup > System check installs it)."})
                ext = re.sub(r"[^a-z0-9.]", "", unquote(self.headers.get("X-Ext") or ".wav").lower())[:6] or ".wav"
                tmpd = app.sb.meta / "tmp"
                tmpd.mkdir(parents=True, exist_ok=True)
                raw, wav = tmpd / f"memory-in{ext}", tmpd / "memory-sample.wav"
                try:
                    with open(raw, "wb") as fh:
                        left = n
                        while left > 0:
                            chunk = self.rfile.read(min(1 << 20, left))
                            if not chunk:
                                break
                            fh.write(chunk)
                            left -= len(chunk)
                    err = avtools.prepare_voice_sample(ff, raw, wav)
                    if err:
                        return self._json({"ok": False, "error": f"Joe couldn't read that recording: {err}"})
                    err = addons_mod.save_memory_voice(name, wav.read_bytes(), promises)
                finally:
                    for f in (raw, wav):
                        try:
                            f.unlink()
                        except OSError:
                            pass
                if not err:
                    app.log(f"Saved a voice to remember: {name} (stays on this PC).")
                return self._json({"ok": not err, "error": err, "voices": addons_mod.memory_voices()})
            if u.path == "/api/restore":                # RESTORE FROM A BACKUP: the zip itself is the body
                from . import backup
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 < n <= backup.MAX_TOTAL:
                    return self._json({"ok": False, "error": "That file is empty or far too big for a settings backup."})
                if app.running:
                    return self._json({"ok": False, "error": "Can't change settings during a run."})
                old_ws = app.settings.workspace_path
                old_sched = (app.settings.schedule.enabled, app.settings.schedule.time, app.settings.schedule.stop)
                try:
                    r = backup.restore(app.settings, app.sb, self.rfile.read(n))
                except (ValueError, OSError) as e:
                    return self._json({"ok": False, "error": str(e)})
                ch = app._settings_changed(old_ws, old_sched)
                app.log(f"Restored settings from a backup made {r['made'][:16].replace('T', ' ')} "
                        f"(Joe {r['joe']}): {r['files']} file(s)" + (f", {r['renamed']} kept as '(restored)'" if r["renamed"] else "") + ".")
                return self._json({**r, "warning": "" if ch.get("ok") else ch.get("error", "")})
            if u.path == "/api/tools/upload":           # a file for a tool (streamed to Inbox/tools/<id>/)
                from urllib.parse import unquote
                from . import tools as tools_mod
                n = int(self.headers.get("Content-Length") or 0)
                tool = (parse_qs(u.query).get("tool") or [""])[0]
                name = unquote(self.headers.get("X-Filename") or "file")
                if tool not in tools_mod.TOOLS or not tools_mod.TOOLS[tool].ready:
                    return self._json({"ok": False, "error": "unknown tool"})
                if not 0 < n <= tools_mod.UPLOAD_MAX_BYTES:
                    return self._json({"ok": False, "error": "That file is empty or over 8 GB."})
                if Path(name).suffix.lower() not in tools_mod.TOOLS[tool].accepts:
                    self.rfile.read(n)
                    return self._json({"ok": False, "error": f"{tools_mod.TOOLS[tool].name} can't use "
                                       f"{Path(name).suffix or 'that kind of file'} files."})
                try:
                    p = tools_mod.upload_target(app.sb, tool, name)
                    part = p.with_name(p.name + ".part")
                    left = n
                    with open(part, "wb") as f:
                        while left > 0:
                            chunk = self.rfile.read(min(left, 1 << 20))
                            if not chunk:
                                break
                            f.write(chunk)
                            left -= len(chunk)
                    if left:
                        part.unlink(missing_ok=True)
                        return self._json({"ok": False, "error": "The upload stopped part way."})
                    part.replace(p)
                except (OSError, SandboxError) as e:
                    try:
                        part.unlink(missing_ok=True)       # never leave a huge half-file behind
                    except (OSError, NameError):
                        pass
                    return self._json({"ok": False, "error": str(e)})
                rel = str(p.relative_to(app.sb.inbox)).replace("\\", "/")
                return self._json({"ok": True, "input": rel, "name": p.name, "bytes": n})
            if u.path == "/api/tools/mission":          # the Tools form -> a mission (not run yet)
                from . import tools as tools_mod
                n = int(self.headers.get("Content-Length") or 0)
                b = json.loads(self.rfile.read(n) or b"{}") if 0 < n <= 200_000 else {}
                tid = b.get("tool", "")
                if tid not in tools_mod.TOOLS or not tools_mod.TOOLS[tid].ready:
                    return self._json({"ok": False, "error": "unknown tool"})
                files = [str(x) for x in (b.get("files") or []) if str(x).strip()][:200]
                if not files and tools_mod.TOOLS[tid].accepts and tid not in tools_mod.NO_INPUT_OK:
                    return self._json({"ok": False, "error": "Add at least one file first."})
                text = tools_mod.mission_for(tid, files, [str(x) for x in b.get("options") or []],
                                             str(b.get("name") or ""), str(b.get("extra") or ""),
                                             str(b.get("mark") or ""))
                chk = app.check(text)
                if not chk["ok"]:
                    return self._json(chk)
                from . import describe as describe_mod
                return self._json({"ok": True, "mission": text, "summary": describe_mod.plain_summary(chk),
                                   "time": describe_mod.plain_time(chk["eta_min"])
                                   + ("" if chk.get("eta_learned") else describe_mod.ROUGH),
                                   "warnings": chk.get("warnings", [])})
            if u.path == "/api/talk/attach":            # a file dropped into Talk
                from urllib.parse import unquote
                from . import attach
                n = int(self.headers.get("Content-Length") or 0)
                name = unquote(self.headers.get("X-Filename") or "file")
                if not 0 < n <= attach.MAX_BYTES:
                    return self._json({"ok": False, "error": "That file is empty or over 25 MB."})
                try:
                    p = attach.save_drop(app.sb, name, self.rfile.read(n))
                    info = attach.extract(p, app.log)
                except (ValueError, OSError, SandboxError) as e:
                    return self._json({"ok": False, "error": str(e)})
                rel = str(p.relative_to(app.sb.root)).replace("\\", "/")
                f = {"id": secrets.token_hex(4), "name": p.name, "rel": rel, **info}
                app.talk_files.append(f)
                app.log(f"Got {p.name} (saved to {rel}).")
                return self._json({"ok": True, "id": f["id"], "name": p.name, "kind": f["kind"], "rel": rel,
                                   "chars": len(f.get("text", "")), "truncated": f.get("truncated", False)})
            if u.path == "/api/voice/listen":           # raw audio from the microphone
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 < n <= 15_000_000:
                    return self._json({"ok": False, "error": "recording too long"})
                ctype = (self.headers.get("Content-Type") or "").lower()
                ext = "ogg" if "ogg" in ctype else "wav" if "wav" in ctype else "mp4" if "mp4" in ctype else "webm"
                return self._json(app.listen(self.rfile.read(n), ext))
            b = self._body()
            try:
                if u.path == "/api/voice/hello":
                    audio, err = app.hello_audio()
                    if err:
                        return self._json({"ok": False, "error": err}, 200)
                    return self._send(200, audio, "audio/wav")
                if u.path == "/api/voice/speak":
                    audio, err = app.speak(str(b.get("text", "")))
                    if err:
                        return self._json({"ok": False, "error": err}, 200)
                    return self._send(200, audio, "audio/wav")
                if u.path == "/api/talk":
                    return self._json(app.talk(str(b.get("text", ""))))
                if u.path == "/api/talk/stream":
                    return self._talk_stream(str(b.get("text", "")))
                if u.path == "/api/talk/warm":
                    app.warm_talk()
                    return self._json({"ok": True})
                if u.path == "/api/voice/memory/list":
                    return self._json({"ok": True, "voices": addons_mod.memory_voices(),
                                       "promises": addons_mod.MEMORY_PROMISES, "ready": addons_mod.clone_ready()})
                if u.path == "/api/voice/memory/delete":
                    addons_mod.delete_memory_voice(str(b.get("id", "")))
                    return self._json({"ok": True, "voices": addons_mod.memory_voices()})
                if u.path == "/api/voice/myvoice/delete":
                    addons_mod.delete_my_voice()
                    if app.settings.voice.voice == "mine":
                        app.settings.voice.voice = "am_adam"
                        app.settings.save()
                    app.log("Deleted your voice sample.")
                    return self._json({"ok": True})
                if u.path == "/api/talk/detach":
                    app.talk_files = [f for f in app.talk_files if f["id"] != b.get("id")]
                    return self._json({"ok": True})
                if u.path == "/api/talk/clear":
                    app.new_chat()
                    return self._json({"ok": True})
                if u.path == "/api/web/test":
                    from . import websearch
                    w = app.settings.web
                    res = websearch.search("ceramic glaze", w.ollama_key.strip(), 3)
                    if not res:
                        return self._json({"ok": False, "error": "no results (check the internet connection"
                                           + (" and the key)" if w.ollama_key else ")")})
                    via = "Ollama web search" if res[0].source == "ollama" else "Wikipedia (no key, or the key didn't work)"
                    return self._json({"ok": True, "text": f"Works: {len(res)} results from {via}."
                                       + ("" if w.enabled else " Tick the box above to let Talk use it.")})
                if u.path == "/api/chats/open":
                    d = app.open_chat(str(b.get("id", "")))
                    return self._json({"ok": bool(d), "chat": d, "error": "" if d else "That chat is gone."})
                if u.path == "/api/chats/get":
                    d = app.chats.get(str(b.get("id", "")))
                    return self._json({"ok": bool(d), "chat": d, "error": "" if d else "That chat is gone."})
                if u.path == "/api/chats/delete":
                    if b.get("all"):
                        n = app.chats.delete_all()
                        app.chat_history = []
                        app.log(f"Deleted {n} past chat(s).")
                        return self._json({"ok": True, "deleted": n})
                    cid = str(b.get("id", ""))
                    was_current = bool(app.chats.current and app.chats.current["id"] == cid)
                    ok = app.chats.delete(cid)
                    if was_current:
                        app.chat_history = []
                    return self._json({"ok": ok, "deleted": int(ok), "was_current": was_current})
                if u.path == "/api/workflow/import":
                    return self._json(app.import_workflow(b.get("text", ""), b.get("name", ""), b.get("style", "")))
                if u.path == "/api/export":
                    return self._json(app.export(b.get("path", ""), b.get("formats") or ["docx", "pdf"]))
                if u.path == "/api/check":
                    return self._json(app.check(b.get("text", "")))
                if u.path == "/api/run":
                    return self._json(app.run(b.get("text", "")))
                if u.path == "/api/pick":               # [ + ] next to a folder/file box in Setup
                    kind = "file" if b.get("kind") == "file" else "folder"
                    return self._json({"ok": True, **system.pick_path(kind, str(b.get("title") or (
                        "Choose a file" if kind == "file" else "Choose a folder"))[:120], str(b.get("start") or ""))})
                if u.path == "/api/restart":            # RESTART JOE (asks first in the window)
                    if app.running:
                        return self._json({"ok": False, "error": "Joe is working: restart after the run finishes."})
                    if app.busy or app.dl_all.get("running"):
                        return self._json({"ok": False, "error": f"Busy: {app.busy or 'downloading'}. Restart when it's done."})
                    from .app import restart
                    if not restart(app.log):
                        return self._json({"ok": False, "error": "Couldn't start a new Joe."})
                    app.restart_hint = ""
                    app.last_seen = 0.0
                    app.quit_now = True
                    return self._json({"ok": True})
                if u.path == "/api/quit":
                    if app.running:
                        return self._json({"ok": False, "error": "a run is going"})
                    app.last_seen = 0.0                    # idle check exits within ~1 s
                    app.quit_now = True
                    return self._json({"ok": True})
                if u.path == "/api/phone/pair":            # a one-time QR code for a new phone
                    return self._json(app.phone.new_pairing())
                if u.path == "/api/phone/remove":
                    from .phone import remove_device
                    return self._json({"ok": remove_device(str(b.get("id", "")))})
                if u.path == "/api/stop":
                    app.stop.set()
                    app.log("Stop requested: finishing the current step...")
                    return self._json({"ok": True})
                if u.path == "/api/models/download-all":
                    if b.get("stop"):
                        app.dl_all["stop"] = True
                        return self._json({"ok": True})
                    if b.get("list"):
                        items = app.download_all_items()
                        return self._json({"ok": True, "items": [{"id": i.get("id"), "text": i.get("text"),
                                                                  "what": i.get("what", "")} for i in items]})
                    return self._json(app.download_all(b))
                if u.path == "/api/doctor/fix":
                    return self._json(app.doctor_fix(b))
                if u.path == "/api/backup":                     # BACK UP MY SETTINGS
                    from . import backup
                    try:
                        f = backup.make(app.settings, app.sb, keys=bool(b.get("keys")))
                    except OSError as e:
                        return self._json({"ok": False, "error": str(e)})
                    try:
                        from .system import reveal
                        reveal(f)
                    except OSError:
                        pass
                    return self._json({"ok": True, "path": str(f.relative_to(app.sb.output)).replace("\\", "/")})
                if u.path == "/api/models/check":               # Setup > Models > CHECK MY MODEL FILES
                    from . import modelcheck
                    from .doctor import comfy_models_dir
                    if b.get("fix"):                            # move one short file to the Recycle Bin
                        p = str(b["fix"])
                        if not b.get("approved") or p not in app.short_models:
                            return self._json({"ok": False, "error": "Check the files first, then say yes."})
                        try:
                            storage_mod.trash(Path(p))
                        except OSError as e:
                            return self._json({"ok": False, "error": f"Couldn't move it: {e}"})
                        app.short_models.discard(p)
                        app.log(f"Moved the cut-short model file {Path(p).name} to the Recycle Bin. "
                                "Setup > Models offers it again.")
                        return self._json({"ok": True})
                    r = modelcheck.scan(comfy_models_dir(app.settings))
                    app.short_models = {s["path"] for s in r["short"]}
                    return self._json({"ok": True, **r, "text": modelcheck.plain(r)})
                if u.path == "/api/abilities":                  # WHAT CAN JOE DO?
                    from . import abilities
                    aid = str(b.get("id", ""))
                    if aid:
                        e = abilities.explain(aid)
                        return self._json({"ok": bool(e), **(e or {"error": "unknown"})})
                    if b.get("ask"):
                        a = abilities.answer(str(b["ask"]))
                        return self._json({"ok": bool(a), **(a or {})})
                    return self._json({"ok": True, "groups": abilities.groups(), "text": abilities.overview()})
                if u.path == "/api/portable":                   # Setup > General > PORTABLE JOE
                    act = b.get("action", "info")
                    job = app.portable_job
                    if act == "info":
                        return self._json({"ok": True, **portable_mod.info(app.settings)})
                    if act == "plan":
                        return self._json({"ok": True, **portable_mod.plan(app.settings)})
                    if act == "status":
                        return self._json({"ok": True, **job.status()})
                    if act == "stop":
                        job.stop = True
                        return self._json({"ok": True})
                    if act == "make":
                        if not b.get("approved"):
                            return self._json({"ok": False, "error": "Needs your OK first."})
                        opts = {k: bool(b.get(k)) for k in ("work", "settings", "ollama_models", "comfy_models")}
                        return self._json(job.start(app.settings, str(b.get("dest", "")), opts, app.log))
                    return self._json({"ok": False, "error": "unknown action"})
                if u.path == "/api/help-file":                  # a zip to send when asking for help
                    from . import support
                    try:
                        chk = doctor.check(app.settings, app.services)
                    except Exception as e:                      # noqa: BLE001 (still make the file)
                        chk = {"error": repr(e)}
                    f = support.make_help_file(app.settings, app.sb, chk, debug=getattr(app, "debug_lines", None))
                    if b.get("show", True):
                        try:
                            from .system import reveal
                            reveal(f)
                        except OSError:
                            pass
                    return self._json({"ok": True, "path": f.name})
                if u.path == "/api/queue/add":
                    return self._json(app.enqueue(b.get("text", "")))
                if u.path == "/api/queue/remove":
                    return self._json(app.dequeue(int(b.get("index", -1))))
                if u.path == "/api/resume":
                    return self._json(app.resume(b.get("action", "")))
                if u.path == "/api/mission/parse":
                    from .mission import mission_to_dict
                    try:
                        return self._json({"ok": True, **mission_to_dict(parse((b.get("text", ""))))})
                    except MissionError as e:
                        return self._json({"ok": False, "error": str(e)})
                if u.path == "/api/notify/test":       # one test ping, only when the person asks
                    topic = (b.get("topic") or app.settings.comfort.ntfy_topic).strip()
                    server = b.get("server") or app.settings.comfort.ntfy_server
                    err = notify_mod.send_ntfy(server, topic, "Hi, it's Joe. Pings work. I'll tell you here when a run is done.")
                    return self._json({"ok": not err, "error": err})
                if u.path == "/api/speedtest":
                    return self._json(app.speed_test())
                if u.path == "/api/route":             # one box: command, chat, plan or unclear?
                    from .route import classify
                    return self._json(classify(str(b.get("text", ""))[:4000]))
                if u.path == "/api/describe":          # plain words in, a mission + summary out
                    from .chat import busy_drawing
                    if busy_drawing(app):              # hold it: plan once the pictures finish
                        return self._json(app.hold_plan(str(b.get("text", ""))))
                    return self._json(app.plan_now(str(b.get("text", ""))))
                if u.path == "/api/tools/mask":        # Fix one spot: the painted spot, as <picture>-mask.png
                    import base64 as _b64
                    rel = str(b.get("input", ""))
                    data = str(b.get("png", ""))
                    if data.startswith("data:"):
                        data = data.split(",", 1)[-1]
                    try:
                        raw = _b64.b64decode(data, validate=False)
                    except ValueError:
                        raw = b""
                    if not raw.startswith(b"\x89PNG") or len(raw) > 40_000_000:
                        return self._json({"ok": False, "error": "That mark couldn't be read. Try again."})
                    pic = app.sb.resolve(rel, base="Inbox")
                    if not pic.is_file():
                        return self._json({"ok": False, "error": "That picture isn't in Inbox any more."})
                    from .picturetools import MASK_SUFFIX
                    target = app.sb.check(pic.with_name(pic.stem + MASK_SUFFIX))
                    target.write_bytes(raw)
                    return self._json({"ok": True, "mask": target.name})
                if u.path == "/api/templates":         # Setup > Writing > Templates
                    from . import doctemplates
                    return self._json({"ok": True, **doctemplates.entries(app.settings)})
                if u.path == "/api/templates/add":     # a template of your own, copied from one of Joe's
                    from . import doctemplates
                    return self._json(doctemplates.add_custom(app.settings, str(b.get("name", "")),
                                                              str(b.get("base", "")), str(b.get("about", ""))))
                if u.path == "/api/templates/delete":
                    from . import doctemplates
                    return self._json(doctemplates.delete_custom(app.settings, str(b.get("id", ""))))
                if u.path in ("/api/templates/save", "/api/templates/reset", "/api/templates/defaults"):
                    from . import doctemplates
                    if u.path.endswith("defaults"):
                        return self._json(doctemplates.save_defaults(app.settings, b.get("defaults") or {}))
                    vals = b.get("values") if u.path.endswith("save") else None
                    return self._json(doctemplates.save(app.settings, str(b.get("id", "")), vals))
                if u.path == "/api/workflows":         # Setup > Workflows
                    from . import workflowprefs
                    from .doctor import comfy_models_dir
                    return self._json({"ok": True, **workflowprefs.entries(app.settings, app.sb,
                                                                           comfy_models_dir(app.settings))})
                if u.path in ("/api/workflows/save", "/api/workflows/reset"):
                    if app.running:
                        return self._json({"ok": False, "error": "Can't change settings during a run."})
                    from . import workflowprefs
                    prefs = b.get("prefs") if u.path.endswith("save") else None
                    return self._json(workflowprefs.save(app.settings, str(b.get("id", "")), prefs))
                if u.path == "/api/packs":             # STARTER PACKS: the list
                    from . import packs
                    return self._json({"ok": True, "packs": [{k: p[k] for k in ("id", "name", "about", "ask", "own")}
                                                             for p in packs.list_packs(app.sb)]})
                if u.path == "/api/pack":              # one pack + the person's answer -> a plan
                    from . import describe as describe_mod
                    from . import packs
                    try:
                        text = packs.build(app.sb, str(b.get("id", "")), str(b.get("for", "")))
                    except KeyError:
                        return self._json({"ok": False, "error": "That pack is gone. Pick another one."})
                    chk, text, notes = packs.plan(app, text)
                    if not chk["ok"]:
                        return self._json(chk)
                    return self._json({"ok": True, "mission": text, "summary": describe_mod.plain_summary(chk),
                                       "time": describe_mod.plain_time(chk["eta_min"])
                                       + ("" if chk.get("eta_learned") else describe_mod.ROUGH),
                                       "eta_min": chk["eta_min"], "warnings": notes + chk.get("warnings", [])})
                if u.path == "/api/assistant":         # reminders and lists (Home box or Talk)
                    from . import reminders
                    cmd, lst = str(b.get("cmd", "")), str(b.get("list", ""))[:40]
                    if cmd == "remind":
                        return self._json(reminders.add(app.sb, app.settings, str(b.get("text", ""))[:500]))
                    if cmd == "directions":
                        return self._json(reminders.directions(app.settings, str(b.get("text", ""))[:200]))
                    if cmd == "shop":
                        return self._json(reminders.shopping(app.settings, str(b.get("text", ""))[:200]))
                    if cmd == "list-add":
                        return self._json(reminders.list_add(app.sb, lst, str(b.get("items", ""))[:500]))
                    if cmd == "list-done":
                        return self._json(reminders.list_done(app.sb, lst, str(b.get("items", ""))[:500]))
                    if cmd == "list-show":
                        return self._json(reminders.list_show(app.sb, lst))
                    if cmd == "list-send":
                        return self._json(reminders.list_send(app.sb, app.settings, lst))
                    return self._json({"ok": False, "error": "unknown"})
                if u.path == "/api/park":              # "park this: <idea>" -> Ideas.md in Joe's folder
                    return self._json(app.park_idea(str(b.get("text", ""))[:4000]))
                if u.path == "/api/tonight/add":       # save a plan for the night shift
                    from .mcp import Joe
                    j = Joe(app.settings)
                    j.sb = app.sb
                    ok, msg = j.check(str(b.get("text", "")))
                    if not ok:
                        return self._json({"ok": False, "error": msg})
                    j.queue(str(b.get("text", "")), str(b.get("name", "")), tonight=True)
                    from .mcp import _mission_files
                    return self._json({"ok": True, "waiting": len(_mission_files(app.sb.missions / "Tonight")),
                                       "on": app.settings.schedule.enabled, "time": app.settings.schedule.time})
                if u.path == "/api/mcp-config":        # the lines for Claude Desktop's settings file
                    from .mcp import client_config
                    import secrets as _sec
                    if not app.settings.mcp_key:
                        app.settings.mcp_key = _sec.token_urlsafe(24)
                        app.settings.save()
                    from . import connect as connect_mod
                    entry = client_config()["mcpServers"]["joe"]
                    apps = connect_mod.status()
                    for a in apps:
                        if a["connected"] and a["id"] != "chatgpt":
                            a["current"] = connect_mod.entry_matches(a["points_to"], entry)
                    return self._json({"ok": True, "text": json.dumps(client_config(), indent=2),
                                       "url": f"http://127.0.0.1:{self.server.server_address[1]}/mcp",
                                       "key": app.settings.mcp_key, "apps": apps})
                if u.path == "/api/connect":           # CONNECT / DISCONNECT an AI app (asked first in the window)
                    return self._json(app.connect_app(str(b.get("app", "")), bool(b.get("on")),
                                                      str(b.get("how", ""))))
                if u.path == "/api/bigger":            # ASK A BIGGER AI: the paste-ready message
                    from . import bigger
                    return self._json({"ok": True, "text": bigger.message(
                        app, str(b.get("text", ""))[:4000], bool(b.get("report", True)),
                        str(b.get("mission", ""))[:8000])})
                if u.path == "/api/bigger/answer":     # the chatbot's answer pasted back
                    from . import bigger
                    return self._json(bigger.read_answer(app, str(b.get("text", ""))[:60000],
                                                         str(b.get("request", ""))[:4000]))
                if u.path == "/api/describe/held":     # the UI took the held plan (or dropped it)
                    app.held_plan = {}
                    return self._json({"ok": True})
                if u.path == "/api/session/new":       # Joe opened, or NEW CHAT: a fresh start
                    return self._json(app.new_session())
                if u.path == "/api/summary":           # plain-English summary of any mission
                    from . import describe as describe_mod
                    chk = app.check(b.get("text", ""))
                    if not chk["ok"]:
                        return self._json(chk)
                    return self._json({"ok": True, "summary": describe_mod.plain_summary(chk),
                                       "time": describe_mod.plain_time(chk["eta_min"])
                                       + ("" if chk.get("eta_learned") else describe_mod.ROUGH),
                                       "warnings": chk.get("warnings", [])})
                if u.path == "/api/mission/build":
                    from .mission import to_text
                    text = to_text(b.get("project", ""), b.get("rules", ""), b.get("tasks") or [])
                    chk = app.check(text)
                    out = {"ok": chk["ok"], "text": text, "error": chk.get("error", ""), "check": chk}
                    if chk["ok"]:
                        from . import describe as describe_mod
                        out["summary"] = describe_mod.plain_summary(chk)
                        out["time"] = describe_mod.plain_time(chk["eta_min"]) + \
                            ("" if chk.get("eta_learned") else describe_mod.ROUGH)
                    return self._json(out)
                if u.path == "/api/mission/save_as":
                    name = re.sub(r"[^A-Za-z0-9 _-]", "", b.get("name", "")).strip()[:60]
                    if not name:
                        return self._json({"ok": False, "error": "Give it a name."})
                    p = app.sb.missions / f"{name}.txt"
                    p.write_text(b.get("text", ""), encoding="utf-8")
                    return self._json({"ok": True, "path": str(p.relative_to(app.sb.root))})
                if u.path == "/api/theme/make":
                    return self._json(app.make_theme(b.get("description", "")))
                if u.path == "/api/savers":
                    from . import savers
                    return self._json({"ok": True, "savers": savers.list_savers(app.sb.themes),
                                       "kinds": savers.KINDS})
                if u.path == "/api/savers/make":
                    return self._json(app.make_saver(b.get("description", "")))
                if u.path == "/api/savers/delete":
                    from . import savers
                    ok = savers.delete(app.sb.themes, str(b.get("id", "")))
                    if ok and app.settings.comfort.screensaver == b.get("id"):
                        app.settings.comfort.screensaver = "joe"
                        app.settings.save()
                    return self._json({"ok": ok})
                if u.path == "/api/theme/delete":
                    tid = re.sub(r"[^a-z0-9-]", "", b.get("id", ""))
                    f = app.sb.themes / f"{tid}.json"
                    if tid and f.exists():
                        f.unlink()
                        if app.settings.ui.phosphor == f"custom:{tid}":
                            app.settings.ui.phosphor = "modern-auto"
                            app.settings.save()
                    return self._json({"ok": True})
                if u.path == "/api/history/delete":       # Step by step > PAST MISSIONS > DEL
                    p = app.sb.root / str(b.get("file", "")).replace("\\", "/")
                    ok = p.is_file() and p in storage_mod.past_runs(app.sb)
                    if not ok:
                        return self._json({"ok": False, "error": "That past mission isn't there any more."})
                    try:
                        storage_mod.trash(p)
                    except OSError as e:
                        return self._json({"ok": False, "error": f"Couldn't move it to the Recycle Bin: {e}"})
                    return self._json({"ok": True})
                if u.path == "/api/storage/clean":
                    kind = b.get("kind", "")
                    if kind not in storage_mod.CLEANUPS:
                        return self._json({"ok": False, "error": "unknown cleanup"}, 400)
                    if app.running and kind in ("rejected", "versions", "comfy"):
                        return self._json({"ok": False, "error": "Joe is working. Clean up when he's done."})
                    return self._json(storage_mod.clean(app.settings, app.sb, kind))
                if u.path == "/api/review":
                    p = app.rel_path(b.get("path", ""))
                    if not p.is_file():
                        return self._json({"ok": False, "error": "not a file"})
                    mark = media_mod.set_review(p.parent, p.name, b.get("mark", ""))
                    return self._json({"ok": True, "mark": mark})
                if u.path == "/api/to_mp4":
                    return self._json(app.to_mp4(b.get("path", "")))
                if u.path == "/api/open":
                    return self._json(app.open_path(b.get("path", ""), b.get("how", "default")))
                if u.path == "/api/settings":
                    return self._json(app.save_settings(b))
                if u.path == "/api/settings/reset":    # RESET THIS PAGE / RESET ALL SETTINGS (after "are you sure")
                    paths = b.get("paths")
                    if b.get("all"):
                        return self._json(app.reset_settings(None))
                    if not isinstance(paths, list) or not paths:
                        return self._json({"ok": False, "error": "Nothing to reset on this page."})
                    return self._json(app.reset_settings([str(x) for x in paths][:200]))
                if u.path == "/api/engine/check":         # Writing program just changed: is it there?
                    from copy import deepcopy
                    from . import textengines
                    cfg = deepcopy(app.settings.ollama)
                    for k in ("engine", "engine_url", "engine_key", "engine_start"):
                        if k in b:
                            setattr(cfg, k, str(b.get(k) or "").strip())
                    return self._json(textengines.engine_check(cfg))
                if u.path == "/api/engine/test":          # Setup > Writing > TEST CONNECTION
                    from copy import deepcopy
                    from . import textengines
                    cfg = deepcopy(app.settings.ollama)
                    for k in ("engine", "engine_url", "engine_key", "text_model"):
                        if k in b:
                            setattr(cfg, k, str(b.get(k) or "").strip())
                    return self._json(textengines.test_connection(cfg))
                if u.path == "/api/services/start":
                    which = b.get("which")
                    ok = app.services.ensure_ollama() if which == "ollama" else app.services.ensure_comfy()
                    app.refresh_services()
                    why = ""
                    if not ok and which == "ollama":
                        from . import textengines
                        why = textengines.start_problem(app.settings.ollama, textengines.engine_url(app.settings.ollama))
                    return self._json({"ok": ok, "error": why})
                if u.path == "/api/load_mission":
                    p = app.rel_path(b.get("path", ""))
                    if not p.is_file() or p.stat().st_size > 2_000_000:
                        return self._json({"ok": False, "error": "Not a mission file."})
                    text = p.read_text(encoding="utf-8", errors="replace")
                    if "TASK:" not in text.upper():
                        return self._json({"ok": False, "error": "No mission block in that file."})
                    app.mission_text = text = (text)
                    return self._json({"ok": True, "text": text})
                if u.path == "/api/mission/save":
                    app.mission_text = b.get("text", "")
                    (app.sb.missions / "_last_mission.txt").write_text(app.mission_text, encoding="utf-8")
                    return self._json({"ok": True})
            except (SandboxError, OSError) as e:
                return self._json({"ok": False, "error": str(e)}, 400)
            self._json({"error": "not found"}, 404)

        def _talk_stream(self, text: str):
            """Joe's reply as it's written (one JSON line per piece), so speech starts early."""
            files, app.talk_files = app.talk_files, []
            t0 = time.monotonic()
            p = chat_mod.prepare(app, app.chat_history, text, files)
            t_prep = time.monotonic() - t0
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()

            def send(obj):
                self.wfile.write((json.dumps(obj) + "\n").encode())
                self.wfile.flush()
            try:
                if "final" in p:
                    r = p["final"]
                else:
                    raw, first = "", 0.0
                    try:
                        looked = not chat_mod.web_on(app) or bool(p.get("searched"))
                        brief = chat_mod.Brief(text)     # spoken replies stay short unless asked
                        while True:
                            raw, held, asked = "", "", ""
                            thinker = p["model"] in app.leaky_models
                            stream = app.services.ollama.chat_stream(
                                p["msgs"], model=p["model"], max_tokens=3000 if thinker else 900,
                                keep_alive="20m", think=True if thinker else None)
                            leaked = False
                            for piece in stream:
                                if not first and piece.strip():
                                    first = time.monotonic() - t0
                                raw += piece
                                if not thinker and len(raw) < 90 and "\n" not in raw.strip():
                                    held += piece                 # might be "LOOKUP: ..." or the model
                                    continue                      # thinking out loud: don't say it yet
                                if not thinker and chat_mod.thinking_aloud(raw):
                                    leaked = True                 # it reasons in plain text: ask again,
                                    break                         # with its thinking kept out of the reply
                                if not looked and chat_mod.lookup_request(raw):
                                    if "\n" in raw.strip():
                                        asked = chat_mod.lookup_request(raw)
                                        break
                                    continue
                                if held:
                                    held, piece = "", held + piece
                                out = brief.feed(piece)
                                if out:
                                    send({"t": "delta", "text": out})
                            if leaked:
                                try:
                                    stream.close()
                                except Exception:                 # noqa: BLE001
                                    pass
                                app.leaky_models.add(p["model"])
                                app.log(f"Talk: {p['model']} thinks out loud; asking it again with its "
                                        "thinking kept separate (slower first words, clean answers).")
                                send({"t": "status", "text": "Thinking…"})
                                res = app.services.ollama.chat(p["msgs"], model=p["model"], max_tokens=3000,
                                                               keep_alive="20m", think=True)
                                raw, held = res.text, ""
                                if chat_mod.thinking_aloud(raw):
                                    raw = chat_mod.after_thinking(raw)
                                out = brief.feed(raw)
                                if out:
                                    send({"t": "delta", "text": out})
                                break
                            if not looked and not asked:
                                asked = chat_mod.lookup_request(raw)
                            if asked and not looked:
                                looked = True
                                send({"t": "status", "text": "Looking it up online…"})
                                p = chat_mod.prepare(app, app.chat_history, text, files,
                                                     web_results=chat_mod.look_up(app, asked) or [])
                                if "final" in p:
                                    break
                                continue
                            if held:
                                send({"t": "delta", "text": held})
                            break
                        r = p["final"] if "final" in p else chat_mod.finish(raw, p.get("sources"))
                        if "final" not in p and r.get("ok"):
                            r["say"] = brief.trim(r["say"])
                        app.debug(f"Talk timing: setup {t_prep:.1f}s, first words {first:.1f}s, "
                                f"whole reply {time.monotonic() - t0:.1f}s ({p['model']})")
                    except ConnectionError:
                        raise                                     # the window pressed STOP (or closed)
                    except Exception as e:
                        r = {"ok": False, "error": f"Joe couldn't think: {e}"}
                if r.get("ok"):
                    said = text + "".join(f"\n\n[attached {f['name']}]\n{f.get('text', '')[:3000]}" for f in files)
                    app.chat_history += [{"role": "user", "content": said},
                                         {"role": "assistant", "content": r.get("raw", r["say"])}]
                    app.chat_history = app.chat_history[-20:]
                    app.save_chat((text or "(file)") + "".join(f"  📎 {f['name']}" for f in files), r)
                r.pop("raw", None)
                send({"t": "done", **r})
            except ConnectionError:                    # STOP pressed / window closed: drop it
                app.log("Talk: stopped.")
            self.close_connection = True

        def _raw(self, p: Path):
            if not p.is_file():
                return self._json({"error": "not a file"}, 404)
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            size = p.stat().st_size
            rng = self.headers.get("Range")
            start, end = 0, size - 1
            if rng and rng.startswith("bytes="):
                a, _, z = rng[6:].partition("-")
                try:
                    start = min(max(int(a), 0), max(size - 1, 0)) if a else 0
                    end = min(int(z), size - 1) if z else min(start + 4_000_000, size - 1)
                except ValueError:
                    start, end, rng = 0, size - 1, None
                if end < start:
                    start, end, rng = 0, size - 1, None
            with open(p, "rb") as f:
                f.seek(start)
                data = f.read(end - start + 1)
            # a made or dropped-in .html/.svg must never run script on Joe's own address
            extra = {"Accept-Ranges": "bytes", "Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff"}
            if rng:
                extra["Content-Range"] = f"bytes {start}-{end}/{size}"
            self._send(206 if rng else 200, data, ctype, extra)

    return H


def serve(app: App, port: int = 0) -> ThreadingHTTPServer:
    if system.WINDOWS:          # SO_REUSEADDR on Windows lets two programs share a port: never fall into that
        class _Server(ThreadingHTTPServer):
            allow_reuse_address = False
        httpd = _Server(("127.0.0.1", port), make_handler(app))
    else:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    httpd.daemon_threads = True
    try:
        app.phone.apply()                              # Joe Phone, when it's turned on
    except Exception as e:                             # noqa: BLE001 (never stop Joe starting for it)
        app.log(f"Joe Phone: {e}")

    def background():
        while True:
            app.refresh_services()
            app.voice.idle_check()                     # free the voice models after a quiet spell
            if not app.running:
                app.tool_voice.idle_check()
            app.ping_tick()
            app.reminder_tick()
            try:
                app.watch_tick()                       # files dropped in Inbox/Watch/<tool>
            except Exception as e:                     # noqa: BLE001 (never stop the loop)
                app.log(f"Watch folders: {e}")
            app.clone.idle_check()
            app.watch_queue_folder()                   # mission files dropped in Missions/Queue
            for _ in range(10):
                time.sleep(1)
                idle = time.monotonic() - app.last_seen
                working = app.running or (not app.quit_now and app.background_work())
                if (app.quit_now or idle > IDLE_EXIT_S) and not working:
                    httpd.shutdown()
                    return
    threading.Thread(target=background, daemon=True, name="joe-bg").start()
    return httpd
