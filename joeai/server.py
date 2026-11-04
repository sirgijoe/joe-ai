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
import os
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .config import Settings, _merge
from .engine import Engine
from .fsutil import atomic_write_text
from .mission import MissionError, parse
from .sandbox import Sandbox, SandboxError
from .services import ServiceManager
from . import stats as stats_mod
from . import doctor, hardware
from . import media as media_mod
from . import storage as storage_mod
from . import themes as themes_mod
from . import addons as addons_mod
from . import chat as chat_mod
from .chats import Chats
from . import notify as notify_mod

UI_DIR = Path(__file__).parent / "ui"
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
        self.lock = threading.RLock()
        self.logs: collections.deque[str] = collections.deque(maxlen=400)
        self.engine: Engine | None = None
        self.thread: threading.Thread | None = None
        self.stop = threading.Event()
        self.mission_text = ""
        self.run_started = 0.0
        self.parts_at_start = 0
        self.last_seen = time.monotonic()
        self.quit_now = False
        self.services_status = {"ollama": False, "comfyui": False, "loaded": []}
        self.services = ServiceManager(self.settings, log=self.log)
        self.fix_result: dict = {}           # how the last System-check fix went (for the UI)
        self.busy = ""                       # a system-check fix running in the background
        self.busy_pct: float | None = None
        self.voice = addons_mod.VoiceWorker(self.log)
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
        # The mission box always opens empty ("What can I help you with?"). Past missions
        # stay in Missions/ (F3, L loads one); _last_mission.txt is kept only as a backup.

    # -- helpers ---------------------------------------------------------------
    def log(self, line: str) -> None:
        self.logs.append(line)

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def rel_path(self, rel: str) -> Path:
        rel = (rel or "").replace("\\", "/").strip("/")
        if any(p == ".." for p in rel.split("/")):
            raise SandboxError("'..' not allowed")
        return self.sb.check(self.sb.root / rel) if rel else self.sb.root

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
        parts = sum(j.parts for j in m.jobs if not j.media)
        sp = stats_mod.speeds(self.sb)                # learned on this PC; rough defaults at first
        secs = parts * sp["part"]
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
                          "workflow": j.workflow,
                          "project": j.project or m.project}
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
                     "tasks": [j.name for j in mission.jobs], "unfinished": [j.name for j in mission.jobs]}
            (self.sb.missions / "_last_mission.txt").write_text(text, encoding="utf-8")
            if self.running:
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
            self.run_started = time.time()
            self.parts_at_start = 0
            self.thread = threading.Thread(target=self._work, daemon=False, name="joe-run")
            self.thread.start()
        time.sleep(0.2)                       # count parts already done (resume)
        if self.engine:
            self.parts_at_start = sum(s.parts_done for s in self.engine.live)
        return {"ok": True, "queued": 0}

    def run(self, text: str) -> dict:
        if self.running:
            return {"ok": False, "error": "Joe is busy. Use ADD TO QUEUE, or stop the run first (F5)."}
        return self.enqueue(text)

    def _work(self) -> None:
        while True:
            with self.lock:
                if not self.queue or self.stop.is_set():
                    break
                text, mission, entry = self.queue.pop(0)
                self.mission_text = text
                self.engine = Engine(self.settings, self.sb, services=self.services,
                                     log=self.log, stop=self.stop)
                last = not self.queue
            try:
                states = self.engine.run_mission(mission, earlier=self.chain, finish=False)
            except Exception as e:
                self.log(f"!! Run crashed: {e!r}")
                break
            self.chain.append((mission, states))
            entry["unfinished"] = [s.name for s in states if s.status != "done"]
            self._write_last_run()
        self.queue_finished = datetime.now().isoformat(timespec="seconds")
        self._write_last_run()
        stopped = self.stop.is_set()
        if self.queue and stopped:
            self.log(f"Run stopped; {len(self.queue)} queued mission(s) were not started.")
        self.queue = []
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
            for st in eng.live:
                media += [f"Output/{m}" for m in st.media_files]
        for _, states in self.chain:
            for st in states:
                media += [f"Output/{m}" for m in st.media_files if f"Output/{m}" not in media]
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
                "jobs": jobs, "eta_s": eta, "log": list(self.logs)[-120:],
                "services": self.services_status, "workspace": str(self.sb.root),
                "model": (getattr(eng, "text_model", "") if eng else "") or s.ollama.text_model or "auto",
                "ui": asdict(s.ui),
                "report": (self.sb.output / "_REPORT.md").exists(),
                "theme": self.theme_vars(), "hw": hardware.gpu(), "pause_c": s.engine.gpu_temp_pause_c,
                "busy": self.busy, "busy_pct": self.busy_pct, "fix_result": self.fix_result,
                "queued": [e["label"] for _, _, e in self.queue],
                "media": media[-12:][::-1],
                "chain": len(self.chain),
                "quiet": self.quiet(), "finished": self.finished,
                "comfort": {"screensaver_min": s.comfort.screensaver_min}}

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
        p = self.rel_path(rel)
        if sys.platform != "win32":
            return {"ok": False, "error": "Opening files is only wired up on Windows."}
        if how == "folder":
            if p.is_dir():
                subprocess.Popen(["explorer", str(p)])
            else:
                subprocess.Popen(["explorer", f"/select,{p}"])
        elif how == "editor" and p.is_file():
            subprocess.Popen(["notepad.exe", str(p)])
        elif p.exists():
            os.startfile(str(p))  # type: ignore[attr-defined]
        return {"ok": True}

    def doctor_fix(self, b: dict) -> dict:
        """Run a System-check fix. The UI only sends approved=True after the user said yes."""
        if not b.get("approved"):
            return {"ok": False, "error": "Needs your OK first."}
        if self.busy:
            return {"ok": False, "error": f"Busy: {self.busy}"}
        action, tool, model = b.get("action"), b.get("tool", ""), b.get("model", "")
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
                    if ok and tool in ("ollama", "comfyui"):
                        (self.services.ensure_ollama if tool == "ollama" else self.services.ensure_comfy)()
                elif action == "start":
                    (self.services.ensure_ollama if tool == "ollama" else self.services.ensure_comfy)()
                elif action == "pull":
                    if doctor.pull_ollama_model(self.services, model, self.log, approved=True, progress=prog):
                        if (not self.running and self.settings.ollama.text_model
                                and not b.get("id") == "pull-vision"):
                            self.settings.ollama.text_model = model
                            self.settings.save()
                elif action == "download-image-model":
                    ok = doctor.download_image_model(self.settings, self.log, approved=True, progress=prog)
                elif action == "download-video-model":
                    ok = doctor.download_video_model(self.settings, self.log, approved=True, progress=prog)
                elif action == "install-voice":
                    self.voice.close()
                    ok = addons_mod.install_voice(addons_mod.install_log(self.log), approved=True,
                                             stt_model=self.settings.voice.stt_model, progress=prog)
                elif action == "install-clone":
                    self.clone.close()
                    ok = addons_mod.install_clone(addons_mod.install_log(self.log), approved=True)
                elif action == "install-pandoc":
                    ok = addons_mod.install_pandoc(addons_mod.install_log(self.log), approved=True)
                self.refresh_services()
            except Exception as e:      # report, never crash the server
                ok = False
                addons_mod.install_log(self.log)(f"!! {action} failed: {e!r}")
            finally:
                self.fix_result = {"action": action, "ok": bool(ok), "n": self.fix_result.get("n", 0) + 1}
                self.busy, self.busy_pct = "", None
        labels = {"install": f"installing {tool}", "start": f"starting {tool}",
                  "pull": f"downloading {model}", "download-image-model": "downloading image model",
                  "download-video-model": "downloading video model",
                  "install-voice": "setting up Joe's voice", "install-pandoc": "installing Pandoc",
                  "install-clone": "setting up voice copy"}
        if action not in labels:
            return {"ok": False, "error": "unknown fix"}
        self.busy = labels[action]
        doctor.run_in_thread(work)
        return {"ok": True, "started": self.busy}

    def theme_vars(self) -> dict | None:
        ph = self.settings.ui.phosphor
        if not ph.startswith("custom:"):
            return None
        for t in themes_mod.list_themes(self.sb.themes):
            if t["id"] == ph[7:]:
                return t["vars"]
        return None

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
            self.chats.add(you, r.get("say", ""), r.get("mission", ""))
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
            self.log(f"Talk timing: hearing {time.monotonic() - t0:.1f}s ({self.settings.voice.stt_model})")
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
            self.log(f"Talk timing: speaking {time.monotonic() - t0:.1f}s for {len(text)} letters")
        try:
            if not r.get("ok"):
                return b"", r.get("error", "Joe lost his voice")
            return out.read_bytes(), ""
        finally:
            try:
                out.unlink()
            except OSError:
                pass

    def export(self, rel: str, formats: list[str]) -> dict:
        p = self.rel_path(rel)
        if not p.is_file() or p.suffix.lower() not in (".md", ".txt"):
            return {"ok": False, "error": "Pick a .md or .txt file to turn into a document."}
        pandoc = addons_mod.pandoc_exe(self.settings.pandoc)
        if not pandoc:
            return {"ok": False, "error": "Pandoc isn't installed (F10 > System check)."}
        made = addons_mod.export_document(p, formats, pandoc, self.log)
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
        old_ws = self.settings.workspace_path
        _merge(self.settings, data)
        self.settings.save()
        if self.settings.workspace_path != old_ws:
            self.sb = Sandbox(self.settings.workspace_path).ensure()
        self.services = ServiceManager(self.settings, log=self.log)
        return {"ok": True}


# ---------------------------------------------------------------------------
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
                return self._send(200, html.replace("__TOKEN__", app.token).encode(),
                                  "text/html; charset=utf-8",
                                  {"Content-Security-Policy":
                                   "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; "
                                   "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
                                   "font-src 'self' https://fonts.gstatic.com; script-src 'self'"})
            if u.path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if u.path in ("/app.css", "/app.js"):
                f = UI_DIR / u.path.lstrip("/")
                ctype = "text/css" if f.suffix == ".css" else "text/javascript"
                return self._send(200, f.read_bytes(), ctype + "; charset=utf-8")
            if not self._authed(q):
                return self._json({"error": "bad token"}, 401)
            arg = (q.get("path") or [""])[0]
            try:
                if u.path == "/api/ping":
                    return self._json({"ok": True, "version": __version__, "running": app.running})
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
                    return self._json(stats_mod.collect(app.settings, app.sb))
                if u.path == "/api/chats":
                    return self._json({"chats": app.chats.list((q.get("q") or [""])[0]), "bytes": app.chats.size(),
                                       "current": (app.chats.current or {}).get("id", ""),
                                       "keep_days": app.settings.voice.chat_keep_days})
                if u.path == "/api/history":
                    return self._json(app.history())
                if u.path == "/api/lists":
                    return self._json(app.lists())
                if u.path == "/api/resume":
                    return self._json(app.resume_offer())
                if u.path == "/api/voice/status":
                    return self._json({**addons_mod.status(), "settings": asdict(app.settings.voice)})
                if u.path == "/api/themes":
                    return self._json({"themes": themes_mod.list_themes(app.sb.themes)})
                if u.path == "/api/update":
                    from . import update as update_mod
                    if q.get("auto") and not app.settings.ui.check_updates:
                        return self._json({"ok": False, "off": True})
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

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            u = urlparse(self.path)
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
                if u.path == "/api/export":
                    return self._json(app.export(b.get("path", ""), b.get("formats") or ["docx", "pdf"]))
                if u.path == "/api/check":
                    return self._json(app.check(b.get("text", "")))
                if u.path == "/api/run":
                    return self._json(app.run(b.get("text", "")))
                if u.path == "/api/quit":
                    if app.running:
                        return self._json({"ok": False, "error": "a run is going"})
                    app.last_seen = 0.0                    # idle check exits within ~1 s
                    app.quit_now = True
                    return self._json({"ok": True})
                if u.path == "/api/stop":
                    app.stop.set()
                    app.log("Stop requested: finishing the current step...")
                    return self._json({"ok": True})
                if u.path == "/api/doctor/fix":
                    return self._json(app.doctor_fix(b))
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
                if u.path == "/api/describe":          # plain words in, a mission + summary out
                    from . import describe as describe_mod
                    return self._json(describe_mod.draft(app, b.get("text", "")))
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
                if u.path == "/api/theme/delete":
                    tid = re.sub(r"[^a-z0-9-]", "", b.get("id", ""))
                    f = app.sb.themes / f"{tid}.json"
                    if tid and f.exists():
                        f.unlink()
                        if app.settings.ui.phosphor == f"custom:{tid}":
                            app.settings.ui.phosphor = "modern-auto"
                            app.settings.save()
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
                if u.path == "/api/services/start":
                    which = b.get("which")
                    ok = app.services.ensure_ollama() if which == "ollama" else app.services.ensure_comfy()
                    app.refresh_services()
                    return self._json({"ok": ok})
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
                        for piece in app.services.ollama.chat_stream(p["msgs"], model=p["model"],
                                                                      max_tokens=900, keep_alive="20m"):
                            if not first and piece.strip():
                                first = time.monotonic() - t0
                            raw += piece
                            send({"t": "delta", "text": piece})
                        r = chat_mod.finish(raw)
                        app.log(f"Talk timing: setup {t_prep:.1f}s, first words {first:.1f}s, "
                                f"whole reply {time.monotonic() - t0:.1f}s ({p['model']})")
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
            except (BrokenPipeError, ConnectionResetError):
                pass
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
                start = int(a) if a else 0
                end = min(int(z), size - 1) if z else min(start + 4_000_000, size - 1)
            with open(p, "rb") as f:
                f.seek(start)
                data = f.read(end - start + 1)
            extra = {"Accept-Ranges": "bytes"}
            if rng:
                extra["Content-Range"] = f"bytes {start}-{end}/{size}"
            self._send(206 if rng else 200, data, ctype, extra)

    return H


def serve(app: App, port: int = 0) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    httpd.daemon_threads = True

    def background():
        while True:
            app.refresh_services()
            app.voice.idle_check()                     # free the voice models after a quiet spell
            app.ping_tick()
            app.clone.idle_check()
            for _ in range(10):
                time.sleep(1)
                idle = time.monotonic() - app.last_seen
                if (app.quit_now or idle > IDLE_EXIT_S) and not app.running:
                    httpd.shutdown()
                    return
    threading.Thread(target=background, daemon=True, name="joe-bg").start()
    return httpd
