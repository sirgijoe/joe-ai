"""Service manager: keeps Ollama and ComfyUI alive and hands the GPU between them.

- is_up / ensure: health-check, start if down, wait until ready.
- handoff("text"|"image"): free VRAM held by the other service first.
Nothing is downloaded or installed here; we only start programs the user
already has, and never with hidden windows tricks or registry edits.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from .config import Settings
from .http import HttpError, request_json
from .ollama import OllamaClient

Log = Callable[[str], None]


def _popen(cmd: list[str] | str, cwd: str | None = None) -> subprocess.Popen:
    kwargs: dict = {"cwd": cwd or None, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        # No console window; own process group so it outlives Joe.
        kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, shell=isinstance(cmd, str), **kwargs)


def find_ollama_exe(configured: str = "") -> str | None:
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("ollama")
    if found:
        return found
    if sys.platform == "win32":
        guess = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if guess.exists():
            return str(guess)
    return None


class ServiceManager:
    def __init__(self, settings: Settings, log: Log = print):
        self.s = settings
        self.log = log
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
        self.log("Starting Ollama...")
        _popen([exe, "serve"])
        return self._wait(self.ollama_up, 60)

    def ensure_ollama(self) -> bool:
        return self.ollama_up() or self.start_ollama()

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

    def comfy_exe(self) -> Path | None:
        from .comfy import desktop_exe
        return desktop_exe()

    def start_comfy(self) -> bool:
        cmd = self.s.comfy.start_command.strip()
        if cmd:
            self.log("Starting ComfyUI...")
            _popen(cmd, cwd=self.s.comfy.start_dir or str(Path(cmd).parent))
        else:
            exe = self.comfy_exe()
            if not exe:
                self.log("ComfyUI not found. Install it from F10 > System check, or set its start command.")
                return False
            self.log("Starting ComfyUI Desktop...")
            _popen([str(exe)], cwd=str(exe.parent))
        return self._wait(self.comfy_up, 240)

    def ensure_comfy(self) -> bool:
        return self.comfy_up() or self.start_comfy()

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

    @staticmethod
    def _wait(check: Callable[[], bool], seconds: float) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if check():
                return True
            time.sleep(1)
        return False


def gpu_temperature_c() -> int | None:
    """NVIDIA GPU temperature (kept here for older imports)."""
    from .hardware import gpu_temperature_c as _t
    return _t()
