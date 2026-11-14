"""Optional add-ons: Joe's voice (Whisper + Kokoro) and finished documents (Pandoc).

Voice runs in its OWN small Python environment made by uv (a free tool from Astral that
downloads its own Python), so nothing is installed into the user's Python and Joe itself
stays standard-library only. Everything lives in %LOCALAPPDATA%\\joe-ai\\addons\\.

Nothing here downloads or installs without approved=True, which the UI only sends after
the user says yes.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable

Log = Callable[[str], None]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

VOICE_PY = "3.12"                       # the voice libraries don't support Python 3.14 yet
VOICE_PACKAGES = ["faster-whisper", "kokoro-onnx", "soundfile"]
KOKORO_FILES = {                        # Kokoro v1.0 (Apache-2.0), int8 build: small and fast on CPU
    "kokoro-v1.0.int8.onnx":
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx",
    "voices-v1.0.bin":
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}
VOICES = {  # Kokoro voice ids (American/British English) -> friendly names
    "am_adam": "Adam (US)", "am_michael": "Michael (US)", "am_fenrir": "Fenrir (US)",
    "am_puck": "Puck (US)", "bm_george": "George (UK)", "bm_lewis": "Lewis (UK)",
    "af_heart": "Heart (US)", "af_bella": "Bella (US)", "af_sarah": "Sarah (US)",
    "bf_emma": "Emma (UK)",
}
STT_MODELS = ("tiny.en", "base.en", "small.en")


def addons_dir() -> Path:
    from .system import data_dir
    return Path(os.environ.get("JOE_ADDONS") or data_dir() / "addons")


def voice_dir() -> Path:
    return addons_dir() / "voice"


def voice_python() -> Path:
    env = voice_dir() / "env"
    return env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


# uv is a program Joe runs, so he downloads one known release and checks it byte for byte (2.3).
# A newer uv is picked on purpose: change the version, download each file from the release page and
# put its SHA-256 here (the release also publishes <file>.sha256 to compare with).
UV_VERSION = "0.13.7"
UV_RELEASE = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/"
UV_ZIP = UV_RELEASE + "uv-x86_64-pc-windows-msvc.zip"          # kept for older imports
UV_SHA256 = {
    "uv-x86_64-pc-windows-msvc.zip": "0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021",
    "uv-aarch64-pc-windows-msvc.zip": "505d9e65e7692bac3ddf98c66754aa26c5050c409c184af30a881a0a72cc85e3",
    "uv-x86_64-apple-darwin.tar.gz": "20c47e4c1f630b8abaff8c291fa9b9aa300fef92c4fbff95adf198b55287cda7",
    "uv-aarch64-apple-darwin.tar.gz": "81b811b57e4624df7ed3aac148e0359100d9962f3d9dce00aec533dc2e086731",
    "uv-x86_64-unknown-linux-gnu.tar.gz": "c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83",
    "uv-aarch64-unknown-linux-gnu.tar.gz": "71279f8d3c67241e807b9d8db872d1bf541579fb9f08b7d1eb1682196d1e57dc",
}


def sha256_ok(data: bytes, want: str) -> bool:
    import hashlib
    import hmac
    return bool(want) and hmac.compare_digest(hashlib.sha256(data).hexdigest(), want.lower())


def uv_asset(plat: str | None = None, machine: str | None = None) -> str | None:
    """The official uv download for this computer, or None if uv doesn't make one."""
    import platform as _pf
    plat = plat or sys.platform
    m = (machine or _pf.machine()).lower()
    arch = "aarch64" if m in ("arm64", "aarch64", "armv8", "armv8l") else \
        "x86_64" if m in ("x86_64", "amd64", "x64") else None
    if not arch:
        return None
    if plat == "win32":
        return f"uv-{arch}-pc-windows-msvc.zip"
    if plat == "darwin":
        return f"uv-{arch}-apple-darwin.tar.gz"
    if plat.startswith("linux"):
        return f"uv-{arch}-unknown-linux-gnu.tar.gz"
    return None


def _unpack_uv(data: bytes, name: str, dest: Path) -> None:
    """Copy uv (and uvx) out of the official zip / tar.gz into dest."""
    import io
    want = ("uv.exe", "uvx.exe", "uv", "uvx")
    dest.mkdir(parents=True, exist_ok=True)
    if name.endswith(".zip"):
        import zipfile
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in z.namelist():
                if Path(n).name.lower() in want:
                    (dest / Path(n).name).write_bytes(z.read(n))
        return
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        for member in t.getmembers():
            if member.isfile() and Path(member.name).name in want:
                f = t.extractfile(member)
                if f:
                    out = dest / Path(member.name).name
                    out.write_bytes(f.read())
                    out.chmod(0o755)


def uv_exe() -> str | None:
    """uv wherever it lives: Joe's own copy, PATH, winget, the standalone installer, pip."""
    exe = "uv.exe" if sys.platform == "win32" else "uv"
    own = addons_dir() / "bin" / exe
    if own.exists():
        return str(own)
    found = shutil.which("uv")
    if found:
        return found
    if sys.platform == "win32":
        la = Path(os.environ.get("LOCALAPPDATA", ""))
        cands = [la / "Microsoft" / "WinGet" / "Links" / exe, Path.home() / ".local" / "bin" / exe,
                 Path.home() / ".cargo" / "bin" / exe, Path(sys.executable).parent / "Scripts" / exe]
        cands += sorted((la / "Microsoft" / "WinGet" / "Packages").glob(f"astral-sh.uv*/{exe}"))
        cands += sorted((la / "Programs" / "Python").glob(f"Python3*/Scripts/{exe}"))
    else:
        cands = [Path.home() / ".local" / "bin" / exe, Path.home() / ".cargo" / "bin" / exe,
                 Path("/opt/homebrew/bin") / exe, Path("/usr/local/bin") / exe,
                 Path("/home/linuxbrew/.linuxbrew/bin") / exe]
    for p in cands:
        if p.exists():
            return str(p)
    return None


def get_uv(log: Log) -> str | None:
    """Find uv, or download Joe's own copy (official GitHub release, no admin needed)."""
    uv = uv_exe()
    if uv:
        return uv
    asset = uv_asset()
    if asset and asset not in UV_SHA256:
        asset = None                                   # no checked download for this computer: package manager
    if asset:
        import tarfile
        import zipfile
        log(f"Getting uv {UV_VERSION} from its official GitHub release (it sets up a private Python just "
            "for Joe's voice; no admin needed)...")
        try:
            with urllib.request.urlopen(UV_RELEASE + asset, timeout=120) as r:
                data = r.read()
            if not sha256_ok(data, UV_SHA256[asset]):
                raise OSError("the download didn't match the checksum Joe knows for it, so it wasn't used "
                              "(a broken download, or not the real uv)")
            _unpack_uv(data, asset, addons_dir() / "bin")
        except (OSError, zipfile.BadZipFile, tarfile.TarError) as e:
            log(f"  couldn't download uv: {e}")
        if uv_exe():
            return uv_exe()
    log("Trying the system's package manager for uv...")
    _winget("uv", log)
    uv = uv_exe()
    if not uv:
        log("Couldn't get uv. Install it from astral.sh/uv, then press SET UP again.")
    return uv


def pandoc_exe(configured: str = "") -> str | None:
    from .finder import pandoc_exe as _p
    return _p(configured)


def voice_ready() -> bool:
    return (voice_python().exists() and (voice_dir() / ".ready").exists()
            and all((voice_dir() / "models" / n).exists() for n in KOKORO_FILES))


# --------------------------------------------------------------------------- voice copy
# "Make Joe sound like me": Chatterbox (Resemble AI, MIT license) copies a voice from a short
# recording. It's big (PyTorch) and wants an NVIDIA card, so it's a separate, optional add-on
# with its own environment. The recording stays in addons\\voice\\myvoice on this PC only:
# it is never put in the workspace, a mission, an export or the app folder.
CLONE_PY = "3.11"
CLONE_PACKAGES = ["chatterbox-tts"]
TORCH_INDEX = "https://download.pytorch.org/whl/cu124"
CLONE_MIN_VRAM_GB = 6


def clone_dir() -> Path:
    return addons_dir() / "voicecopy"


def clone_python() -> Path:
    env = clone_dir() / "env"
    return env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def clone_ready() -> bool:
    return clone_python().exists() and (clone_dir() / ".ready").exists()


def my_voice_path() -> Path:
    return voice_dir() / "myvoice" / "reference.wav"


def has_my_voice() -> bool:
    p = my_voice_path()
    return p.exists() and (p.parent / "consent.txt").exists()


def save_my_voice(wav: bytes, consent: bool) -> str:
    """Store the user's own recording. Returns '' or a problem."""
    if not consent:
        return "Please confirm it's your own voice first."
    if not (wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"):
        return "That recording isn't a WAV file."
    if len(wav) < 24000 * 2 * 8:                       # ~8 s of 24 kHz 16-bit mono
        return "That was too short. Read the whole passage (about 30 seconds)."
    p = my_voice_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(wav)
    (p.parent / "consent.txt").write_text(
        "The person using this PC confirmed this recording is their own voice, "
        f"on {time.strftime('%Y-%m-%d %H:%M')}. It is used only on this PC.\n", encoding="utf-8")
    return ""


def delete_my_voice() -> None:
    d = my_voice_path().parent
    for f in (d / "reference.wav", d / "consent.txt"):
        try:
            f.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- a voice to remember
# A loved one's voice made from family recordings, for the family's own use. Kept only on this PC
# (never in Joe's folder, backups or help files), each with the three promises the person ticked.
MEMORY_PROMISES = {
    "family": "I'm family (or I have the family's OK) to use this person's voice.",
    "private": "It's only for our family's own listening: never sold, posted or shared as if it were real.",
    "honest": "It will never be used to fool, trick or pretend to be them to anyone.",
}


def memory_dir() -> Path:
    return voice_dir() / "memory"


def memory_slug(name: str) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40]


def memory_voices() -> list[dict]:
    out = []
    try:
        for d in sorted(memory_dir().iterdir()):
            ref, info = d / "reference.wav", d / "consent.json"
            if ref.exists() and info.exists():
                try:
                    meta = json.loads(info.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                out.append({"id": d.name, "name": meta.get("name", d.name), "made": meta.get("made", "")})
    except OSError:
        pass
    return out


def memory_ref(vid: str) -> Path | None:
    d = memory_dir() / memory_slug(vid)
    return d / "reference.wav" if (d / "reference.wav").exists() and (d / "consent.json").exists() else None


def save_memory_voice(name: str, wav: bytes, promises: set[str]) -> str:
    """Store a prepared 24 kHz WAV sample. Returns '' or a problem in plain words."""
    missing = [k for k in MEMORY_PROMISES if k not in promises]
    if missing:
        return "Please tick all three promises first."
    vid = memory_slug(name)
    if not vid:
        return "Type the person's name (or what you call them)."
    if not (wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"):
        return "That recording couldn't be read."
    if len(wav) < 24000 * 2 * 6:
        return "There's too little clear speech in that recording (Joe needs at least 6 seconds of their voice talking)."
    d = memory_dir() / vid
    d.mkdir(parents=True, exist_ok=True)
    (d / "reference.wav").write_bytes(wav)
    (d / "consent.json").write_text(json.dumps({"name": name.strip()[:60], "made": time.strftime("%Y-%m-%d %H:%M"),
                                                "promised": [MEMORY_PROMISES[k] for k in MEMORY_PROMISES]}, indent=1),
                                    encoding="utf-8")
    return ""


def delete_memory_voice(vid: str) -> None:
    import shutil as _sh
    d = memory_dir() / memory_slug(vid)
    if d.is_dir() and d.parent == memory_dir():
        _sh.rmtree(d, ignore_errors=True)


def install_clone(log: Log, approved: bool = False) -> bool:
    if not approved:
        raise PermissionError("needs the user's approval")
    uv = get_uv(log)
    if not uv:
        return False
    cd = clone_dir()
    cd.mkdir(parents=True, exist_ok=True)
    if not clone_python().exists():
        log(f"Making the voice-copy environment (Python {CLONE_PY})...")
        if not _run([uv, "venv", "--python", CLONE_PY, str(cd / "env")], log):
            return False
    log("Installing Chatterbox and PyTorch for NVIDIA cards (about 3 GB, this takes a while)...")
    if not _run([uv, "pip", "install", "--python", str(clone_python()), *CLONE_PACKAGES,
                 "--extra-index-url", TORCH_INDEX, "--index-strategy", "unsafe-best-match"], log, 7200):
        return False
    log("Downloading the voice-copy model (first run)...")
    w = VoiceWorker(log, python=str(clone_python()), script=Path(__file__).with_name("clone_worker.py"))
    try:
        r = w.call({"cmd": "warmup"}, timeout=3600)
    finally:
        w.close()
    if not r.get("ok"):
        log(f"  voice copy test failed: {r.get('error')}")
        return False
    (cd / ".ready").write_text(time.strftime("%Y-%m-%d %H:%M"), encoding="utf-8")
    log("Voice copy is ready. In Setup > Voice & Talk, press MAKE JOE SOUND LIKE ME.")
    return True


def status() -> dict:
    return {"voice": voice_ready(), "uv": bool(uv_exe()), "pandoc": bool(pandoc_exe()),
            "voices": VOICES, "clone": clone_ready(), "my_voice": has_my_voice()}


# --------------------------------------------------------------------------- install
def install_log(log: Log) -> Log:
    """Also write add-on setup steps to addons\\install.log, so a failed setup can be read later."""
    path = addons_dir() / "install.log"
    from .storage import cap_log
    cap_log(path)

    def both(msg: str) -> None:
        log(msg)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except OSError:
            pass
    return both


def _run(cmd: list[str], log: Log, timeout: int = 3600, cwd: str | None = None) -> bool:
    log("  > " + " ".join(Path(cmd[0]).name if i == 0 else c for i, c in enumerate(cmd))[:160])
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=NO_WINDOW,
                           cwd=cwd)
    except (OSError, subprocess.SubprocessError) as e:
        log(f"  failed to run: {e}")
        return False
    if p.returncode != 0:
        log(f"  (exit code {p.returncode})")
        for ln in (p.stderr or p.stdout or "").strip().splitlines()[-12:]:
            log("  " + ln[:300])
    return p.returncode == 0


def _winget(tool: str, log: Log) -> bool:
    """Install uv or Pandoc with this system's package manager (winget, Homebrew, apt, ...)."""
    from .doctor import run_install
    ok = run_install(tool, tool, "", log)
    return ok or bool(uv_exe() if tool == "uv" else pandoc_exe())   # "already installed" counts


def install_pandoc(log: Log, approved: bool = False) -> bool:
    if not approved:
        raise PermissionError("needs the user's approval")
    if pandoc_exe():
        return True
    log("Installing Pandoc (makes Word, PDF and EPUB files)...")
    ok = _winget("pandoc", log) and bool(pandoc_exe())
    log("Pandoc ready." if ok else "Pandoc install failed. You can get it from pandoc.org.")
    return ok


def _download(url: str, dest: Path, log: Log, progress=None) -> bool:
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
            total, got, last = int(r.headers.get("Content-Length") or 0), 0, -25.0
            from .system import room_problem
            room = room_problem(dest.parent, total)
            if room:                                  # say so now, not after the download fills the drive
                raise OSError(room)
            while chunk := r.read(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if total:
                    pct = 100 * got / total
                    if progress:
                        progress(pct)
                    if pct - last >= 25:
                        log(f"  {dest.name}: {pct:.0f}%")
                        last = pct
            if total and got != total:          # the connection dropped: never keep a cut-short file
                raise OSError(f"the download stopped early ({got // 1_000_000} of {total // 1_000_000} MB); try again")
        part.replace(dest)
        return True
    except OSError as e:
        log(f"  download failed: {e}")
        try:
            part.unlink()
        except OSError:
            pass
        return False


def install_voice(log: Log, approved: bool = False, stt_model: str = "base.en", progress=None) -> bool:
    """uv -> private Python 3.12 -> faster-whisper + kokoro-onnx -> Kokoro voice files -> Whisper model."""
    if not approved:
        raise PermissionError("needs the user's approval")
    vd = voice_dir()
    (vd / "models").mkdir(parents=True, exist_ok=True)
    uv = get_uv(log)
    if not uv:
        return False
    log(f"  using uv: {uv}")
    if not voice_python().exists():
        log(f"Making Joe's voice environment (Python {VOICE_PY})...")
        if not _run([uv, "venv", "--python", VOICE_PY, str(vd / "env")], log):
            return False
    log("Installing the speech libraries (faster-whisper, kokoro-onnx)...")
    if not _run([uv, "pip", "install", "--python", str(voice_python()), *VOICE_PACKAGES], log):
        return False
    for name, url in KOKORO_FILES.items():
        dest = vd / "models" / name
        if not dest.exists():
            log(f"Downloading Joe's voice: {name}...")
            if not _download(url, dest, log, progress):
                return False
    log(f"Getting the speech-to-text model ({stt_model})...")
    w = VoiceWorker(log)
    try:
        r = w.call({"cmd": "warmup", "stt_model": stt_model}, timeout=1800)
    finally:
        w.close()
    if not r.get("ok"):
        log(f"  voice test failed: {r.get('error')}")
        return False
    (vd / ".ready").write_text(time.strftime("%Y-%m-%d %H:%M"), encoding="utf-8")
    log("Joe's voice is ready. Press F4 and just talk to him.")
    return True


# --------------------------------------------------------------------------- worker
class VoiceWorker:
    """One long-lived helper process (the voice environment's Python) so models load once.
    Talks JSON lines over stdin/stdout. Closed after a few idle minutes to free memory."""

    IDLE_S = 600

    def __init__(self, log: Log = print, python: str | None = None, script: Path | None = None):
        self.log = log
        self.python = python or str(voice_python())
        self.script = str(script or Path(__file__).with_name("voice_worker.py"))
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.last = 0.0

    def _start(self) -> None:
        env = dict(os.environ, HF_HUB_DISABLE_TELEMETRY="1", PYTHONIOENCODING="utf-8",
                   JOE_VOICE_MODELS=str(voice_dir() / "models"),
                   HF_HOME=str(clone_dir() / "models"))
        errlog = addons_dir() / f"{Path(self.script).stem}.log"     # the libraries' own chatter
        from .storage import cap_log
        cap_log(errlog)
        try:
            errlog.parent.mkdir(parents=True, exist_ok=True)
            self._err = open(errlog, "a", encoding="utf-8", errors="replace")
        except OSError:
            self._err = subprocess.DEVNULL
        # -I: isolated, so Joe's own modules (e.g. joeai/http.py) can't shadow the standard library.
        self.proc = subprocess.Popen([self.python, "-I", "-u", self.script], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self._err, text=True,
                                     encoding="utf-8", errors="replace", env=env, creationflags=NO_WINDOW)

    def call(self, req: dict, timeout: float = 300) -> dict:
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                try:
                    self._start()
                except OSError as e:
                    return {"ok": False, "error": f"voice helper won't start: {e}"}
            self.last = time.monotonic()
            try:
                self.proc.stdin.write(json.dumps(req) + "\n")
                self.proc.stdin.flush()
            except OSError as e:
                self.close_locked()
                return {"ok": False, "error": f"voice helper stopped: {e}"}
            out: list[str] = []

            def read():                  # skip anything that isn't our reply
                while True:
                    ln = self.proc.stdout.readline()
                    if not ln:
                        out.append("")
                        return
                    if ln.startswith("@@JOE@@"):
                        out.append(ln[7:])
                        return
                    if ln.strip().startswith("{"):          # older helper without the marker
                        try:
                            json.loads(ln)
                            out.append(ln)
                            return
                        except ValueError:
                            pass
            t = threading.Thread(target=read, daemon=True)
            t.start()
            t.join(timeout)
            if t.is_alive() or not out or not out[0]:
                self.close_locked()
                return {"ok": False, "error": "voice helper stopped (details in addons\\voice_worker.log)"}
            self.last = time.monotonic()
            try:
                return json.loads(out[0])
            except ValueError:
                return {"ok": False, "error": "voice helper sent a bad reply"}

    def idle_check(self) -> None:
        if self.proc and time.monotonic() - self.last > self.IDLE_S:
            with self.lock:
                self.close_locked()

    def close_locked(self) -> None:
        if self.proc:
            try:
                self.proc.kill()
            except OSError:
                pass
            self.proc = None

    def close(self) -> None:
        with self.lock:
            self.close_locked()


# --------------------------------------------------------------------------- documents
GENERIC_TITLE = re.compile(r"^\s*(?:(?:a|my|the)\s+)?(?:kids'?|children'?s?|childrens|picture|bedtime|short|"
                           r"illustrated|story|book|ebook|e-book|novel|draft|manuscript|\s)+\s*$", re.I)


def add_pictures(text: str, pictures: list[str]) -> str:
    """One picture under each '## ' heading, in order (a picture book: picture, then the words).
    Headings without a picture (more pages than pictures) are left as they are."""
    if not pictures:
        return text
    out, n = [], 0
    for line in text.split("\n"):
        out.append(line)
        if line.startswith("## ") and n < len(pictures):
            out += ["", f"![]({pictures[n]})", ""]
            n += 1
    return "\n".join(out)


# Pandoc reads Joe's documents with raw HTML, raw TeX, raw blocks and "---" settings blocks turned
# off: text a model wrote must never become a <script>, an <iframe>, or a "css:" line that makes
# Pandoc copy a file from somewhere else on the PC into the finished document.
SAFE_MARKDOWN = "markdown-raw_html-raw_tex-raw_attribute-yaml_metadata_block"
_PICTURE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*(<[^>]*>|[^)\s]*)[^)]*\)")
_MD_IMAGE_REF = re.compile(r"!\[([^\]]*)\](?:\[[^\]]*\])?(?!\()")
_MD_LINK_DEF = re.compile(r"(?m)^[ ]{0,3}\[[^\]]+\]:[ \t]*<?([^\s>]*)>?.*$")


def _own_picture(target: str, base: Path) -> bool:
    """A picture link Joe may keep: a plain relative path to a picture file inside `base`."""
    import os
    from urllib.parse import unquote
    t = unquote((target or "").strip().strip("<>").strip())
    if not t or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", t) or t.startswith(("/", "\\", "~")):
        return False                               # a web address, file:, C:\..., /etc/..., \\server\...
    try:
        root = Path(os.path.realpath(base))
        real = Path(os.path.realpath(root / t))
        real.relative_to(root)
    except (ValueError, OSError):
        return False
    return real.is_file() and real.suffix.lower() in _PICTURE_EXT


def safe_export_text(text: str, base: Path) -> str:
    """Markdown that's safe to hand to Pandoc: picture links are kept only when they point at a
    picture inside the document's own folder (anything else becomes its caption), and link
    definitions that point at local files are dropped. Web links stay: Pandoc doesn't fetch links."""
    def image(m):
        return m.group(0) if _own_picture(m.group(2), base) else m.group(1)
    text = _MD_IMAGE.sub(image, text)
    text = _MD_IMAGE_REF.sub(lambda m: m.group(1), text)        # ![caption][ref] / ![ref]: never fetched
    def link_def(m):
        return m.group(0) if re.match(r"(?i)^(https?://|mailto:|#)", m.group(1)) else ""
    return _MD_LINK_DEF.sub(link_def, text)


def export_document(md: Path, formats: list[str], pandoc: str, log: Log, settings=None,
                    template: str = "", cache: Path | None = None, heading: str = "",
                    pictures: list[Path] | None = None) -> list[Path]:
    """Markdown -> .docx / .epub / .odt / .html with Pandoc; .pdf by printing Pandoc's HTML with
    Edge or Chrome, so no LaTeX is needed. Each copy follows a writing template (doctemplates.py):
    `template` (a task's TEMPLATE:) or Setup's default for that kind of file."""
    from . import doctemplates as dt
    made: list[Path] = []
    title = md.stem.replace("_", " ").replace("-", " ").title()
    cache = cache or (md.parent / ".joe-templates")
    # Joe's documents start with "# <task name>" (`heading`). In a finished copy that line is the
    # title, not a chapter: printed as a heading it gave books an empty first chapter page. So it
    # becomes the title and is taken out of the copy - also when it's the only "# " heading.
    import re as _re
    try:
        lines = md.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    body = None
    first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if first is not None and _re.match(r"^#\s+\S", lines[first]):
        rest = "\n".join(lines[first + 1:]).lstrip("\n")
        top = lines[first][1:].strip()
        if (heading and top == heading.strip()) or not _re.search(r"(?m)^#\s+\S", rest):
            title = top or title
            body = rest + "\n"
    # A task named like "Kids picture book" isn't the book's title: the first page heading is
    # (QC 2026-11-09: the PDF's title was the task name).
    if GENERIC_TITLE.match(title or ""):
        first_h2 = next((ln[3:].strip() for ln in lines if ln.startswith("## ") and ln[3:].strip()), "")
        if first_h2 and not _re.match(r"(?i)(?:chapter|part|page|section)\b", first_h2):
            title = first_h2
    # The words came from a model (and maybe from another AI's plan): take out anything that could
    # pull in a file from outside this folder or run script, BEFORE Joe adds his own pictures.
    body = safe_export_text(body if body is not None else "\n".join(lines) + "\n", md.parent)
    if pictures:
        import os
        rel = [os.path.relpath(p, md.parent).replace("\\", "/") for p in pictures]
        body = add_pictures(body, rel)

    def tpl(fmt: str) -> dict:
        template_ = dt.resolve(settings, template) if template else ""
        tid = template_ if template_ and dt.exists(settings, template_, "doc") else \
            (dt.default_for(settings, fmt) if settings is not None else dt.DEFAULTS.get(fmt, "standard"))
        return dt.get(settings, tid)

    def source(t: dict) -> tuple[list[str] | None, Path | None]:
        """Pandoc's input: the .md itself, or a screenplay-marked copy; plus title / line-break options."""
        args = ["--metadata", f"title={title}"] if t.get("show_title", True) else ["--metadata", f"pagetitle={title}"]
        args = ["-f", SAFE_MARKDOWN + ("+hard_line_breaks" if t.get("line_breaks") else "")] + args
        text = body
        if t.get("screenplay"):
            tmp = md.with_name(md.stem + ".script.md")
            try:
                tmp.write_text(dt.screenplay_md(text), encoding="utf-8")
                return [str(tmp)] + args, tmp
            except OSError:
                pass
        tmp = md.with_name(md.stem + ".export.md")
        try:
            tmp.write_text(text, encoding="utf-8")
            return [str(tmp)] + args, tmp
        except OSError:
            pass
        try:                                   # the folder can't be written: use the temp folder
            import tempfile                    # (pictures still resolve: Pandoc runs in md's folder)
            fd, name = tempfile.mkstemp(prefix="joe-export-", suffix=".md")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            return [name] + args, Path(name)
        except OSError:
            log(f"  couldn't make a safe copy of {md.name} to export; skipped.")
            return None, None                  # never hand Pandoc the unchecked file

    def tidy(tmp: Path | None) -> None:
        if tmp:
            try:
                tmp.unlink()
            except OSError:
                pass

    for fmt in formats:
        fmt = fmt.strip().lower().lstrip(".")
        if fmt in ("docx", "epub", "odt", "html", "pptx"):
            t = tpl(fmt)
            out = md.with_suffix("." + fmt)
            src_args, tmp_md = source(t)
            if src_args is None:
                continue
            cmd = [pandoc, *src_args, "-s", "-o", str(out)]
            css = None
            if fmt == "docx":
                ref = dt.reference_docx(pandoc, t, cache, log, title=title)
                if ref:
                    cmd += ["--reference-doc", str(ref)]
            elif fmt in ("epub", "html"):
                css = md.with_suffix(f".{fmt}.css")
                css.write_text(dt.css(t, epub=fmt == "epub", title=title), encoding="utf-8")
                cmd += ["--css", css.name if fmt == "html" else str(css)]
                if fmt == "html":
                    cmd += ["--embed-resources"] if _pandoc_embeds(pandoc) else []
                if fmt == "epub" and t.get("chapter_break"):
                    cmd += ["--split-level=1"] if _pandoc_split_level(pandoc) else []
            ok = _run(cmd, log, 300, cwd=str(md.parent)) and out.exists()
            tidy(tmp_md)
            if css and (fmt == "epub" or _pandoc_embeds(pandoc)):
                try:
                    css.unlink()
                except OSError:
                    pass
            if ok:
                made.append(out)
                log(f"  {out.name}: template '{t['label']}'")
        elif fmt == "pdf":
            t = tpl("pdf")
            html = md.with_suffix(".print.html")
            out = md.with_suffix(".pdf")
            css = md.with_suffix(".print.css")
            css.write_text(dt.css(t, title=title), encoding="utf-8")
            src_args, tmp_md = source(t)
            if src_args is None:
                continue
            ok = _run([pandoc, *src_args, "-s", "-o", str(html), "--css", css.name], log, 300, cwd=str(md.parent))
            tidy(tmp_md)
            edge = _edge()
            if ok and edge:
                ok = _print_pdf(edge, html, out, log)
            elif ok:
                log("  PDF needs Microsoft Edge or Google Chrome; saved HTML instead.")
            for tmp in (html, css):
                if out.exists() or not ok:
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            if out.exists():
                made.append(out)
                log(f"  {out.name}: template '{t['label']}'")
        elif fmt == "xlsx":
            src = md if md.suffix.lower() == ".csv" else None
            if not src:
                log("  xlsx: only a spreadsheet (.csv) result can become an .xlsx.")
                continue
            template_ = dt.resolve(settings, template) if template else ""
            tid = template_ if template_ and dt.exists(settings, template_, "sheet") else \
                (dt.default_for(settings, "xlsx") if settings is not None else "sheet")
            t = dt.get(settings, tid)
            try:
                made.append(dt.csv_to_xlsx(src, t))
            except OSError as e:
                log(f"  xlsx: {e}")
        else:
            log(f"  unknown export format: {fmt}")
    return made


_PANDOC_INFO: dict = {}


def _pandoc_version(pandoc: str) -> tuple[int, ...]:
    if pandoc not in _PANDOC_INFO:
        try:
            p = subprocess.run([pandoc, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                               creationflags=NO_WINDOW)
            m = re.search(r"pandoc\S*\s+(\d+(?:\.\d+)*)", p.stdout or "")
            _PANDOC_INFO[pandoc] = tuple(int(x) for x in m.group(1).split(".")) if m else (0,)
        except (OSError, subprocess.SubprocessError):
            _PANDOC_INFO[pandoc] = (0,)
    return _PANDOC_INFO[pandoc]


def _pandoc_embeds(pandoc: str) -> bool:
    return _pandoc_version(pandoc) >= (2, 19)


def _pandoc_split_level(pandoc: str) -> bool:
    return _pandoc_version(pandoc) >= (3, 0)


def _kill_tree(p: subprocess.Popen) -> None:
    """Stop a program and everything it started (Edge starts several helper processes)."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True,
                           timeout=30, creationflags=NO_WINDOW)
        else:
            p.kill()
    except (OSError, subprocess.SubprocessError):
        pass


def _print_pdf(edge: str, html: Path, out: Path, log: Log, timeout: int = 180) -> bool:
    """Print an HTML file to PDF with headless Edge/Chrome, without ever hanging the run.

    Edge's helper processes can keep an output pipe open forever, so Joe never captures its
    output; it gets its own throwaway profile (so it never hands the job to an Edge window
    that's already open, like Joe's own), and Joe waits for the PDF, not for Edge to exit."""
    import tempfile
    prof = Path(tempfile.mkdtemp(prefix="joe-pdf-"))
    cmd = [edge, "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
           f"--user-data-dir={prof}", "--no-pdf-header-footer", f"--print-to-pdf={out}",
           html.resolve().as_uri()]
    log("  > " + Path(edge).name + " (printing the PDF)")
    try:
        out.unlink(missing_ok=True)
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except OSError as e:
        log(f"  couldn't start the PDF printer: {e}")
        shutil.rmtree(prof, ignore_errors=True)
        return False
    end = time.monotonic() + timeout
    size = -1
    while time.monotonic() < end:
        done = p.poll() is not None
        if out.exists():
            now = out.stat().st_size
            if now > 0 and (now == size or done):       # finished writing
                break
            size = now
        elif done:
            break
        time.sleep(1)
    ok = out.exists() and out.stat().st_size > 0
    if p.poll() is None:
        _kill_tree(p)
    if not ok:
        log(f"  The PDF didn't come out within {timeout // 60} min; skipped it (the Word copy and "
            "the .md are fine).")
    shutil.rmtree(prof, ignore_errors=True)
    return ok


def _edge() -> str | None:
    """A Chromium-type browser to print the PDF with (Edge on every Windows PC)."""
    from .system import app_browser
    return app_browser()
