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
    engine: str = "ollama"       # ollama | lmstudio | llamacpp | localai | openai (textengines.ENGINES)
    engine_url: str = ""         # blank = that engine's usual address
    engine_start: str = ""       # blank = auto (LM Studio: lms server start); llama.cpp/LocalAI: your start line
    engine_key: str = ""         # optional key some local servers ask for (vLLM --api-key, KoboldCpp password)


@dataclass
class ComfySettings:
    url: str = "http://127.0.0.1:8000"   # desktop app; 8188 (portable) is tried too
    start_command: str = ""      # blank = auto-find ComfyUI Desktop; or e.g. C:\\ComfyUI\\run_nvidia_gpu.bat
    start_dir: str = ""
    models_dir: str = ""         # blank = auto (desktop app's data folder \\models)
    ffmpeg: str = ""             # blank = auto-detect
    timeout_s: int = 900         # per image/video
    default_workflow: str = ""   # file in Workflows/ used when a task has no WORKFLOW
    negative: str = ""                 # empty = Joe's default list (comfy.IMAGE_NEGATIVE)
    output_dir: str = ""         # blank = auto (ComfyUI's own output folder)
    delete_copies: bool = True   # remove ComfyUI's copy of a picture once Joe has saved his
    always_my_model: bool = False    # Setup > Workflows: never switch a picked model to FLUX.2 for the hard cases


@dataclass
class EngineSettings:
    max_retries: int = 3
    short_item_retries: int = 2
    retry_backoff_s: float = 5.0
    keep_awake: bool = True
    when_finished: str = "nothing"   # nothing | sleep | shutdown
    gpu_temp_pause_c: int = 85       # pause between parts above this (0 = off)
    keep_pc_usable: bool = False     # Ollama/ComfyUI at below-normal priority + smaller videos
    daily_restart: bool = True       # Joe closes and opens again once a day (dailyrestart.py), never mid-job
    restart_time: str = ""           # 24-hour clock; blank = 06:00


@dataclass
class UISettings:
    phosphor: str = "modern-auto"    # modern-auto | modern-night | modern-day | futuristic |
                                     # green | amber | white (retro) | custom:<theme id in Themes/>
    crt: int = 2                     # 0 off, 1 subtle, 2 normal, 3 heavy
    text_size: int = 22              # px
    easy_read: bool = False          # Atkinson Hyperlegible everywhere (low vision, dyslexia)
    large_text: str = "normal"       # normal | large (x1.3) | larger (x1.6): everything grows, buttons too (2.3)
    announce: str = "progress"       # screen readers: progress (milestones + finished/failed) | finish | off
    sounds: bool = False             # a soft chime when a run finishes or something fails
    check_updates: bool = True       # look for a newer release on GitHub when Joe starts
    welcomed: bool = False           # the first-start welcome (setup helper) has been seen
    intro: bool = True               # show the opening "01000001 01001001 / JOE" screen
    startup_sound: str = "both"      # when Joe opens: off | jingle | voice (Joe says hello) | both
    jingle: str = "theme"            # theme = Joe's 8-bit intro (ui/sounds/intro.wav) | chime = short tones
    hello_text: str = "Joe is now reporting for duty."
    language: str = "en"             # Joe's own screens (i18n.LANGUAGES); English when a line isn't translated
    favorite_tools: list = field(default_factory=list)   # tool ids starred on the Tools page (kept at the top)


@dataclass
class VoiceSettings:
    voice: str = "am_adam"        # Kokoro voice (Setup > Voice and Talk)
    speed: float = 1.0
    stt_model: str = "base.en"       # tiny.en (fastest) | base.en | small.en (most accurate)
    speak_replies: bool = True       # Joe answers out loud in Talk (F4)
    talk_mode: str = "open"          # open: mic listens while Talk (F4) is open | push: hold a key
    turn_pause: str = "quick"        # open mic: quiet allowed inside your question: quick (0.85 s) | normal (1.2 s) | patient (2 s)
    ptt_key: str = "F4"              # push-to-talk key (any key; set in Setup > Voice and Talk)
    talk_model: str = ""             # a small, quick model just for Talk (blank = the writing model)
    chat_keep_days: int = 30         # past Talk chats older than this are deleted (0 = keep them)
    transcriber: str = "auto"        # auto (whisper.cpp when installed) | faster-whisper | whisper.cpp
    face: str = "on"                 # Joe's face in Talk: on (moving) | still (no blinking/flapping) | off
    wake: bool = False               # wake word: with the open mic, Joe listens on every screen and answers to
                                     # "Hey Joe" (off until ticked: the mic then stays open while Joe's window is)
    wake_words: str = "hey joe"      # what to say first (2-4 plain words)


@dataclass
class ComfortSettings:
    screensaver_min: int = 10        # dim screen + slow-moving status after this many idle minutes (0 = off)
    screensaver: str = "joe"         # which one (savers.BUILTIN id, or custom:<file> from Themes/savers)
    quiet_start: str = ""            # "22:00": no sounds or phone pings from here...
    quiet_end: str = ""              # ..."07:00" (a ping waits until quiet hours end)
    ntfy_topic: str = ""             # phone ping when a run is done (ntfy app); blank = off
    ntfy_server: str = "https://ntfy.sh"
    maps: str = "google"             # "directions to...": google | osm | apple | bing (opens in your browser)
    shop: str = "google"             # "where can I buy...": google | duckduckgo | bing


@dataclass
class StatsSettings:
    # Edit these to match current cloud prices and your power bill.
    cloud_price_in_per_mtok: float = 3.0
    cloud_price_out_per_mtok: float = 15.0
    cloud_price_image: float = 0.035          # one standard cloud picture (2026 median of the main services)
    cloud_price_video_second: float = 0.10    # one second of cloud video (cheap production tier)
    gpu_watts: int = 0               # 0 = read from the GPU while it works
    kwh_price: float = 0.17


@dataclass
class WebSettings:
    enabled: bool = False            # Talk may look things up online (Setup > Privacy and internet)
    ollama_key: str = ""             # key from ollama.com/settings/keys (Ollama now charges credits for web search); blank = Wikipedia only
    max_results: int = 5
    providers: str = "wikipedia"     # search sources that are on, in order (websearch.py). Wikipedia alone out
                                     # of the box; the others (Ollama web search too) are off until ticked
    max_searches: int = 10           # searches one task may make (a Talk question, one overnight task)
    searxng_url: str = ""            # the person's own SearXNG (the "searxng" search source), e.g. http://192.168.1.20:8888
    read_pages: bool = False         # RESEARCH tasks may read whole result pages (only addresses a search returned)
    langsearch_key: str = ""         # key from langsearch.com (the "langsearch" search source); blank = skipped
    # "Your own search source" (the "custom" search source, websearch.py): any search address the person types.
    custom_name: str = ""            # what Joe calls it ("Found with ...")
    custom_url: str = ""             # its address, {query} where the search words go ({key} too, if it wants the key there)
    custom_key: str = ""             # optional key, sent only to that address
    custom_key_header: str = "Authorization"   # how the key is sent: "Authorization" sends "Bearer <key>", any other name sends the key as it is
    custom_body: str = ""            # blank = Joe asks with GET; JSON with {query} in it = Joe posts that
    custom_list: str = "results"     # where the list of results is in its JSON answer ("data.webPages.value")
    custom_title: str = "title"      # ... and in each result: its title,
    custom_link: str = "url"         # its link,
    custom_text: str = "content"     # and its text


@dataclass
class ScheduleSettings:
    # Night shift: plans put in Missions/Tonight start at this time (Setup > Night shift and alerts). The
    # computer's own scheduler (Task Scheduler, launchd, cron) starts Joe; Joe keeps nothing running.
    enabled: bool = False
    time: str = "23:00"              # 24-hour clock, the PC's own time zone
    stop: str = ""                   # optional "stop by" time (24-hour); blank = run until done
    watch: bool = False              # watch folders: files dropped in Inbox/Watch/<tool> are done by themselves


@dataclass
class PhoneSettings:
    # Joe Phone (Setup > Phone): a small web app for phones on the home Wi-Fi. Off until turned on.
    enabled: bool = False
    port: int = 8770


@dataclass
class QualitySettings:
    # Setup > Quality and speed: low = fastest, rougher | medium = balanced | high = best, slowest
    # High by default: Joe mostly works overnight, so best results beat speed (change it in Setup).
    writing: str = "high"
    pictures: str = "high"
    video: str = "high"


@dataclass
class MemorySettings:
    # Memory (memory.py): notes the person asks Joe to remember. Off until they turn it on.
    enabled: bool = False
    phone: bool = False              # Joe Phone may use them
    connector: bool = False          # other AI apps (the connector) may read them


@dataclass
class FilingSettings:
    # How Joe files what he makes (filing.py): date = one dated folder per mission (2026-11-10 Showcase video),
    # project = the same inside a folder per PROJECT:, flat = straight into Output like before 2.3.
    how: str = "date"


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
    schedule: ScheduleSettings = field(default_factory=ScheduleSettings)
    phone: PhoneSettings = field(default_factory=PhoneSettings)
    filing: FilingSettings = field(default_factory=FilingSettings)
    memory: MemorySettings = field(default_factory=MemorySettings)
    templates: dict = field(default_factory=dict)   # Setup > Templates: {edits: {id: {...}}, defaults: {fmt: id}}
    workflows: dict = field(default_factory=dict)   # Setup > Workflows: id -> {model, add, avoid, steps}
    mcp_key: str = ""                # password for Joe's local connector address (made on first use)
    mcp_apps: list = field(default_factory=list)   # AI apps the person connected Joe to (System check watches them)
    mcp_folders: bool = False        # connected apps may read Inbox, Projects, Missions, Workflows, Themes (Output always)
    dev_tools: bool = False          # Setup > Other AI apps > Dev tools: connected apps may use the projects below, and see this PC's status
    dev_projects: list = field(default_factory=list)   # [{name, folder, commands: [{name, run, minutes}]}], typed by the person (devprojects.py)
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
                data = None
            if not isinstance(data, dict):        # broken file: keep a copy before it's ever saved over
                try:
                    import shutil
                    shutil.copy2(path, path.with_name("settings.broken.json"))
                except OSError:
                    pass
                data = {}
            from . import portable
            _merge(s, portable.unpack(data))
            from . import vault                    # keys live in the computer's own vault (vault.py)
            if vault.after_load(s, data, path):    # keys still in the file: move them over now
                try:
                    s.save(path)
                except OSError:
                    pass
        if s.ui.hello_text == "Hello! Joe here, reporting for duty.":   # old default ran together when spoken
            s.ui.hello_text = UISettings.hello_text
        s.engine.max_retries = max(1, min(int(s.engine.max_retries or 3), 10))   # 0 would never ask the model
        clean_favorites(s)
        clean_web(s)
        clean_voice(s)
        from . import devprojects, portable
        devprojects.clean_settings(s)
        portable.adjust_settings(s)
        return s

    def save(self, path: Path | None = None) -> Path:
        path = path or config_path()
        from . import portable, vault
        data = vault.before_save(self, portable.pack(asdict(self)), path)   # keys -> the computer's vault
        atomic_write_text(path, json.dumps(data, indent=2))
        vault.after_write(path, data)
        return path


def clean_favorites(s: "Settings") -> None:
    """Starred tools are a short list of tool ids: drop anything else, repeats, and a runaway list."""
    seen: list[str] = []
    for x in getattr(s.ui, "favorite_tools", []) or []:
        if isinstance(x, str) and 0 < len(x) <= 64 and x not in seen:
            seen.append(x)
    s.ui.favorite_tools = seen[:100]


def clean_voice(s: "Settings") -> None:
    """The pause before Joe's turn is one of the three choices."""
    if s.voice.turn_pause not in ("quick", "normal", "patient"):
        s.voice.turn_pause = "quick"
    s.voice.wake = s.voice.wake is True
    s.voice.wake_words = clean_wake_words(s.voice.wake_words)


def clean_wake_words(text) -> str:
    """The wake words: 2 to 4 plain words in small letters ("hey joe" when what was typed doesn't fit).
    One word alone would fire on everyday talk; more than four is never heard whole."""
    import re
    words = re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower().replace("'", "").replace("\u2019", "")).split()
    words = [w for w in words if len(w) <= 16][:4]
    return " ".join(words) if len(words) >= 2 and len(words[-1]) >= 2 else "hey joe"


def clean_web(s: "Settings") -> None:
    """Search sources are known ids only (websearch.py); the per-task cap stays between 1 and 50."""
    from .websearch import clean_custom, clean_order, searxng_base
    s.web.providers = clean_order(s.web.providers)
    clean_custom(s.web)
    s.web.searxng_url = searxng_base(s.web.searxng_url) if s.web.searxng_url else ""
    try:
        s.web.max_searches = max(1, min(int(s.web.max_searches or 10), 50))
    except (TypeError, ValueError):
        s.web.max_searches = 10


def _merge(obj, data: dict) -> None:
    """Copy known keys only, so old/foreign settings files can't break us."""
    for f in fields(obj):
        if f.name not in data:
            continue
        cur = getattr(obj, f.name)
        val = data[f.name]
        if hasattr(cur, "__dataclass_fields__") and isinstance(val, dict):
            _merge(cur, val)
        elif isinstance(val, bool) and not isinstance(cur, bool):
            continue                                # true/false is never a number setting
        elif isinstance(cur, int) and not isinstance(cur, bool) and isinstance(val, float):
            if val.is_integer():                    # 22.0 for a whole-number setting is 22
                setattr(obj, f.name, int(val))
        elif isinstance(val, type(cur)) or (isinstance(cur, float) and isinstance(val, int)):
            setattr(obj, f.name, val)


# Setup > Reset: these stay as they are (where your files live, keys you typed, first-start state, starred tools).
KEEP_ON_RESET = ("workspace", "web.ollama_key", "web.langsearch_key", "web.custom_key", "ui.welcomed", "mcp_key", "workflows", "templates", "ui.favorite_tools",
                 "dev_projects")      # the list is the person's own typing; Reset turns Dev tools off (dev_tools) and keeps the list


def reset_paths(s: "Settings", paths: list[str] | None = None) -> list[str]:
    """Put settings back to how Joe came. paths = dotted names ("engine.keep_awake"); None = all.
    Returns the paths that changed."""
    fresh = Settings()
    if paths is None:
        paths = []
        for f in fields(Settings):
            sub = getattr(fresh, f.name)
            if hasattr(sub, "__dataclass_fields__"):
                paths += [f"{f.name}.{g.name}" for g in fields(sub)]
            else:
                paths.append(f.name)
    changed = []
    for p in paths:
        if p in KEEP_ON_RESET:
            continue
        head, _, tail = p.partition(".")
        try:
            if tail:
                new = getattr(getattr(fresh, head), tail)
                if getattr(getattr(s, head), tail) != new:
                    setattr(getattr(s, head), tail, new)
                    changed.append(p)
            elif hasattr(fresh, head) and not hasattr(getattr(fresh, head), "__dataclass_fields__"):
                if getattr(s, head) != getattr(fresh, head):
                    setattr(s, head, getattr(fresh, head))
                    changed.append(p)
        except AttributeError:
            continue
    return changed
