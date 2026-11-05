"""Service manager: keeps Ollama and ComfyUI alive and hands the GPU between them.

- is_up / ensure: health-check, start if down, wait until ready.
- handoff("text"|"image"): free VRAM held by the other service first.
Nothing is downloaded or installed here; we only start programs the user
already has, and never with hidden windows tricks or registry edits.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Callable

from .config import Settings
from .http import HttpError, request_json
from .ollama import OllamaClient

Log = Callable[[str], None]
COMFY_START_WAIT_S = 300      # ComfyUI Desktop can be slow to open after an update or big download


def _popen(cmd: list[str] | str, cwd: str | None = None) -> subprocess.Popen:
    from .system import popen_detached
    return popen_detached(cmd, cwd)


def find_ollama_exe(configured: str = "") -> str | None:
    from .finder import ollama_exe
    return ollama_exe(configured)


class ServiceManager:
    def __init__(self, settings: Settings, log: Log = print):
        self.s = settings
        self.log = log
        self.attention = ""          # a plain hint for the window when ComfyUI needs the person
        self.ollama = OllamaClient(settings.ollama)
        self.comfy_base = settings.comfy.url.rstrip("/")

    # -- Ollama -------------------------------------------------------------
    def ollama_up(self) -> bool:
        try:
            self.ollama.version(timeout=3)
            return True
        except HttpError:
            return False

    def start_ollama(self) -> bool:
        exe = find_ollama_exe(self.s.ollama.exe)
        if not exe:
            self.log("Ollama not found. Install it from ollama.com or set its path in Setup.")
            return False
        self.log(f"Starting Ollama: {exe}")
        _popen([exe, "serve"])
        hint = ("Ollama is taking a while to start. It may be updating, or showing a message in its "
                "own window or its icon by the clock. Have a look; Joe keeps waiting.")
        if self._wait(self.ollama_up, 90, "Ollama to start", hint_after=25, hint=hint):
            self.attention = ""
            return True
        self.attention = ("Ollama didn't start. If its window or the icon by the clock shows an update "
                          "or a question, finish that, then try again.")
        return False

    def ensure_ollama(self) -> bool:
        if self.ollama_up():
            if "Ollama" in self.attention:
                self.attention = ""
            return True
        return self.start_ollama()

    # -- ComfyUI ------------------------------------------------------------
    def _probe(self, base: str) -> bool:
        try:
            request_json("GET", f"{base}/system_stats", timeout=3)
            return True
        except HttpError:
            return False

    def comfy_up(self) -> bool:
        """Check the configured address, then the usual ports (desktop 8000, portable 8188)."""
        if self._probe(self.comfy_base):
            return True
        host = re.sub(r":\d+$", "", self.comfy_base)
        for port in (8000, 8188):
            alt = f"{host}:{port}"
            if alt != self.comfy_base and self._probe(alt):
                self.log(f"Found ComfyUI at {alt}.")
                self.comfy_base = alt
                return True
        return False

    def comfy_install(self):
        from .finder import find_comfy
        c = self.s.comfy
        return find_comfy(c.start_command, c.start_dir, c.models_dir)

    def comfy_exe(self) -> Path | None:
        """Something that starts ComfyUI (Desktop program, portable .bat, or own install)."""
        inst = self.comfy_install()
        if not inst or not inst.command:
            return None
        first = inst.command if isinstance(inst.command, str) else inst.command[0]
        return Path(first.strip().strip('"').split('" ')[0])

    def start_comfy(self) -> bool:
        inst = self.comfy_install()
        if not inst or not inst.command:
            self.log("ComfyUI not found on this PC. Install it from F10 > System check, or put its "
                     "start command in Setup > Images & video > More options.")
            return False
        shown = inst.command if isinstance(inst.command, str) else inst.command[0]
        self.log(f"Starting {inst.label}: {shown}")
        try:
            _popen(inst.command, cwd=inst.cwd or None)
        except OSError as e:
            self.log(f"Couldn't start ComfyUI: {e}")
            return False
        hint = ("ComfyUI is taking a while to open. It may be updating, or waiting for you to click "
                "something in its own window (an Update, Restart or Install button). Have a look; Joe "
                "keeps waiting."
                " If ComfyUI Desktop stops on its start screen (the list of installs, or New / GitHub / Cloud), "
                "set it to open your install by itself: ComfyUI menu (☰, top left) > Desktop Settings > "
                "Auto-launch on startup > your install.")
        if self._wait(self.comfy_up, COMFY_START_WAIT_S, "ComfyUI to open", hint_after=45, hint=hint):
            self.attention = ""
            self.log(f"ComfyUI is ready at {self.comfy_base}.")
            return True
        self.attention = ("ComfyUI didn't open. If its window shows an update or a question, finish "
                          "that, then press RUN (F5) again: Joe carries on where he stopped."
                          " If ComfyUI Desktop stops on its start screen (the list of installs, or New / GitHub / Cloud), "
                "set it to open your install by itself: ComfyUI menu (☰, top left) > Desktop Settings > "
                "Auto-launch on startup > your install.")
        self.log(f"ComfyUI didn't answer within {COMFY_START_WAIT_S // 60} minutes. If its window is "
                 "showing a question or an update, answer it and press F5 again.")
        return False

    def ensure_comfy(self) -> bool:
        if self.comfy_up():
            if "ComfyUI" in self.attention:
                self.attention = ""
            return True
        return self.start_comfy()

    def comfy_free(self) -> None:
        request_json("POST", f"{self.comfy_base}/free",
                     {"unload_models": True, "free_memory": True}, timeout=30)

    # -- GPU handoff --------------------------------------------------------
    def handoff(self, job_type: str) -> bool:
        """Make the GPU available for job_type ('text' or 'image'/'video')."""
        if job_type == "text":
            if self.comfy_up():
                try:
                    self.comfy_free()
                    self.log("Freed ComfyUI VRAM for text job.")
                except HttpError as e:
                    self.log(f"Could not free ComfyUI VRAM: {e}")
            return self.ensure_ollama()
        if self.ollama_up():
            try:
                names = self.ollama.unload_all()
                if names:
                    self.log(f"Unloaded {', '.join(names)} for {job_type} job.")
            except HttpError as e:
                self.log(f"Could not unload Ollama models: {e}")
        return self.ensure_comfy()

    def status(self) -> dict:
        st = {"ollama": self.ollama_up(), "comfyui": self.comfy_up(), "loaded": []}
        if st["ollama"]:
            try:
                st["loaded"] = [
                    {"name": m["name"],
                     "gpu_pct": round(100 * m.get("size_vram", 0) / max(m.get("size", 1), 1))}
                    for m in self.ollama.loaded_models()]
            except HttpError:
                pass
        return st

    def _wait(self, check: Callable[[], bool], seconds: float, what: str = "",
              every: float = 30, hint_after: float = 0, hint: str = "") -> bool:
        start = time.monotonic()
        next_note = start + every
        hinted = False
        while time.monotonic() - start < seconds:
            if check():
                return True
            now = time.monotonic()
            if hint and not hinted and now - start >= hint_after:
                hinted = True
                self.attention = hint
                self.log("  " + hint)
            if what and now >= next_note:
                m, s = divmod(int(now - start), 60)
                tm, ts = divmod(int(seconds), 60)
                self.log(f"  still waiting for {what} ({m}:{s:02d} of {tm}:{ts:02d})")
                next_note = now + every
            time.sleep(1)
        return False


def gpu_temperature_c() -> int | None:
    """Graphics card temperature, None if it doesn't report one (kept for older imports)."""
    from .hardware import gpu_temperature_c as _t
    return _t()
