"""Settings: stored per-user (never inside the repo or the .exe).

Windows: %APPDATA%\\joe-ai\\settings.json
Mac:     ~/Library/Application Support/joe-ai/settings.json
Linux:   ~/.config/joe-ai/settings.json
Override with the JOE_CONFIG environment variable (used by tests).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .fsutil import atomic_write_text


def config_dir() -> Path:
    from .system import config_dir as _cd
    return _cd()


def config_path() -> Path:
    override = os.environ.get("JOE_CONFIG")
    return Path(override) if override else config_dir() / "settings.json"


def default_workspace() -> Path:
    from .system import default_workspace as _dw
    return _dw()


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
    phosphor: str = "modern-auto"    # modern-auto | modern-night | modern-day | futuristic |
                                     # green | amber | white (retro) | custom:<theme id in Themes/>
    crt: int = 2                     # 0 off, 1 subtle, 2 normal, 3 heavy
    text_size: int = 22              # px
    easy_read: bool = False          # Atkinson Hyperlegible everywhere (low vision, dyslexia)
    sounds: bool = False             # a soft chime when a run finishes or something fails
    check_updates: bool = True       # look for a newer release on GitHub when Joe starts
    welcomed: bool = False           # the first-start welcome (setup helper) has been seen
    intro: bool = True               # show the opening "01000001 01001001 / JOE" screen
    startup_sound: str = "both"      # when Joe opens: off | jingle | voice (Joe says hello) | both
    jingle: str = "theme"            # theme = Joe's 8-bit intro (ui/sounds/intro.wav) | chime = short tones
    hello_text: str = "Joe is now reporting for duty."


@dataclass
class VoiceSettings:
    voice: str = "am_adam"        # Kokoro voice (Setup > Voice & Talk)
    speed: float = 1.0
    stt_model: str = "base.en"       # tiny.en (fastest) | base.en | small.en (most accurate)
    speak_replies: bool = True       # Joe answers out loud in Talk (F6)
    talk_mode: str = "open"          # open: mic listens while Talk (F6) is open | push: hold a key
    ptt_key: str = "F6"              # push-to-talk key (any key; set in Setup > Voice & Talk)
    talk_model: str = ""             # a small, quick model just for Talk (blank = the writing model)
    chat_keep_days: int = 30         # past Talk chats older than this are deleted (0 = keep them)


@dataclass
class ComfortSettings:
    screensaver_min: int = 10        # dim screen + slow-moving status after this many idle minutes (0 = off)
    quiet_start: str = ""            # "22:00": no sounds or phone pings from here...
    quiet_end: str = ""              # ..."07:00" (a ping waits until quiet hours end)
    ntfy_topic: str = ""             # phone ping when a run is done (ntfy app); blank = off
    ntfy_server: str = "https://ntfy.sh"


@dataclass
class StatsSettings:
    # Edit these to match current cloud prices and your power bill.
    cloud_price_in_per_mtok: float = 3.0
    cloud_price_out_per_mtok: float = 15.0
    gpu_watts: int = 0               # 0 = read from the GPU while it works
    kwh_price: float = 0.17


@dataclass
class WebSettings:
    enabled: bool = False            # Talk may look things up online (Setup > Voice & Talk)
    ollama_key: str = ""             # free key from ollama.com/settings/keys; blank = Wikipedia only
    max_results: int = 5


@dataclass
class QualitySettings:
    # Setup > Writing / Images & video: low = fastest, rougher | medium = balanced | high = best, slowest
    writing: str = "medium"
    pictures: str = "medium"
    video: str = "medium"


@dataclass
class Settings:
    workspace: str = ""
    ollama: OllamaSettings = field(default_factory=OllamaSettings)
    comfy: ComfySettings = field(default_factory=ComfySettings)
    engine: EngineSettings = field(default_factory=EngineSettings)
    ui: UISettings = field(default_factory=UISettings)
    stats: StatsSettings = field(default_factory=StatsSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    comfort: ComfortSettings = field(default_factory=ComfortSettings)
    quality: QualitySettings = field(default_factory=QualitySettings)
    web: WebSettings = field(default_factory=WebSettings)
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
        if s.ui.hello_text == "Hello! Joe here, reporting for duty.":   # old default ran together when spoken
            s.ui.hello_text = UISettings.hello_text
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
