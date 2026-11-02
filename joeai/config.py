"""Settings: stored per-user (never inside the repo or the .exe).

Windows: %APPDATA%\\joe-ai\\settings.json
Other:   ~/.config/joe-ai/settings.json
Override with the JOE_CONFIG environment variable (used by tests).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .fsutil import atomic_write_text


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "joe-ai"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "joe-ai"


def config_path() -> Path:
    override = os.environ.get("JOE_CONFIG")
    return Path(override) if override else config_dir() / "settings.json"


def default_workspace() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.exists() else Path.home()) / "Joe-ai"


@dataclass
class OllamaSettings:
    url: str = "http://127.0.0.1:11434"
    exe: str = ""                # blank = auto-detect
    text_model: str = ""         # blank = best installed model for this PC's GPU
    num_ctx: int = 0             # 0 = automatic from GPU memory
    think: bool = False
    temperature: float = 0.7
    request_timeout_s: int = 600


@dataclass
class ComfySettings:
    url: str = "http://127.0.0.1:8000"   # desktop app; 8188 (portable) is tried too
    start_command: str = ""      # blank = auto-find ComfyUI Desktop; or e.g. C:\\ComfyUI\\run_nvidia_gpu.bat
    start_dir: str = ""
    models_dir: str = ""         # blank = auto (desktop app's data folder \\models)
    ffmpeg: str = ""             # blank = auto-detect
    timeout_s: int = 900         # per image/video
    default_workflow: str = ""   # file in Workflows/ used when a task has no WORKFLOW
    negative: str = "blurry, low quality, watermark, text, logo, deformed"
    output_dir: str = ""         # blank = auto (ComfyUI's own output folder)
    delete_copies: bool = True   # remove ComfyUI's copy of a picture once Joe has saved his


@dataclass
class EngineSettings:
    max_retries: int = 3
    short_item_retries: int = 2
    retry_backoff_s: float = 5.0
    keep_awake: bool = True
    when_finished: str = "nothing"   # nothing | sleep | shutdown
    gpu_temp_pause_c: int = 85       # pause between parts above this (0 = off)


@dataclass
class UISettings:
    phosphor: str = "green"          # green | amber | white | custom:<theme id in Themes/>
    crt: int = 2                     # 0 off, 1 subtle, 2 normal, 3 heavy
    text_size: int = 22              # px
    sounds: bool = False
    check_updates: bool = True       # look for a newer release on GitHub when Joe starts


@dataclass
class VoiceSettings:
    voice: str = "am_adam"        # Kokoro voice (F10 > Voice)
    speed: float = 1.0
    stt_model: str = "base.en"       # tiny.en (fastest) | base.en | small.en (most accurate)
    speak_replies: bool = True       # Joe answers out loud in Talk (F6)
    talk_mode: str = "open"          # open: mic listens while Talk (F6) is open | push: hold a key
    ptt_key: str = "F6"              # push-to-talk key (any key; set in F10 > Voice)


@dataclass
class StatsSettings:
    # Edit these to match current cloud prices and your power bill.
    cloud_price_in_per_mtok: float = 3.0
    cloud_price_out_per_mtok: float = 15.0
    gpu_watts: int = 0               # 0 = read from the GPU while it works
    kwh_price: float = 0.17


@dataclass
class Settings:
    workspace: str = ""
    ollama: OllamaSettings = field(default_factory=OllamaSettings)
    comfy: ComfySettings = field(default_factory=ComfySettings)
    engine: EngineSettings = field(default_factory=EngineSettings)
    ui: UISettings = field(default_factory=UISettings)
    stats: StatsSettings = field(default_factory=StatsSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    pandoc: str = ""                 # blank = auto-detect

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace) if self.workspace else default_workspace()

    # -- persistence -------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or config_path()
        s = cls()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            _merge(s, data)
        return s

    def save(self, path: Path | None = None) -> Path:
        path = path or config_path()
        atomic_write_text(path, json.dumps(asdict(self), indent=2))
        return path


def _merge(obj, data: dict) -> None:
    """Copy known keys only, so old/foreign settings files can't break us."""
    for f in fields(obj):
        if f.name not in data:
            continue
        cur = getattr(obj, f.name)
        val = data[f.name]
        if hasattr(cur, "__dataclass_fields__") and isinstance(val, dict):
            _merge(cur, val)
        elif isinstance(val, type(cur)) or (isinstance(cur, float) and isinstance(val, int)):
            setattr(obj, f.name, val)
