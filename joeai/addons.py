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


UV_ZIP = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"


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
        for p in cands:
            if p.exists():
                return str(p)
    return None


def get_uv(log: Log) -> str | None:
    """Find uv, or download Joe's own copy (official GitHub release, no admin needed)."""
    uv = uv_exe()
    if uv:
        return uv
    if sys.platform == "win32":
        import io
        import zipfile
        log("Getting uv (it sets up a private Python just for Joe's voice)...")
        dest = addons_dir() / "bin"
        dest.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(UV_ZIP, timeout=120) as r:
                data = r.read()
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for name in z.namelist():
                    if name.lower().endswith(("uv.exe", "uvx.exe")):
                        (dest / Path(name).name).write_bytes(z.read(name))
        except (OSError, zipfile.BadZipFile) as e:
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


def _run(cmd: list[str], log: Log, timeout: int = 3600) -> bool:
    log("  > " + " ".join(Path(cmd[0]).name if i == 0 else c for i, c in enumerate(cmd))[:160])
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
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
    log("Joe's voice is ready. Press F6 and just talk to him.")
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
def export_document(md: Path, formats: list[str], pandoc: str, log: Log) -> list[Path]:
    """Markdown -> .docx / .epub with Pandoc; .pdf by printing Pandoc's HTML with Edge
    (built into Windows), so no LaTeX is needed."""
    made: list[Path] = []
    title = md.stem.replace("_", " ").replace("-", " ").title()
    for fmt in formats:
        fmt = fmt.strip().lower().lstrip(".")
        if fmt in ("docx", "epub", "odt", "html"):
            out = md.with_suffix("." + fmt)
            cmd = [pandoc, str(md), "-s", "-o", str(out), "--metadata", f"title={title}"]
            if _run(cmd, log, 300) and out.exists():
                made.append(out)
        elif fmt == "pdf":
            html = md.with_suffix(".print.html")
            out = md.with_suffix(".pdf")
            css = md.with_suffix(".print.css")
            css.write_text("body{font-family:Georgia,serif;max-width:46em;margin:2em auto;line-height:1.5}"
                           "h1,h2,h3{font-family:Segoe UI,Arial,sans-serif}table{border-collapse:collapse}"
                           "td,th{border:1px solid #999;padding:3px 6px}", encoding="utf-8")
            ok = _run([pandoc, str(md), "-s", "-o", str(html), "--metadata", f"title={title}",
                       "--css", css.name], log, 300)
            edge = _edge()
            if ok and edge:
                ok = _run([edge, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                           f"--print-to-pdf={out}", html.resolve().as_uri()], log, 300)
            elif ok:
                log("  PDF needs Microsoft Edge (built into Windows); saved HTML instead.")
            for tmp in (html, css):
                if out.exists() or not ok:
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            if out.exists():
                made.append(out)
        else:
            log(f"  unknown export format: {fmt}")
    return made


def _edge() -> str | None:
    from .app import _edge as find
    return find()
