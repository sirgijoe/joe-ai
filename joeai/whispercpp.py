"""Whisper.cpp: a faster way to turn speech into text on Macs and on PCs without a big graphics card.

Joe's usual transcriber is faster-whisper inside the voice add-on. whisper.cpp does the same
job as one small program (MIT license, github.com/ggml-org/whisper.cpp). On a Mac it uses the
Apple graphics chip, so long recordings finish several times faster.

- Windows: Joe downloads the small CPU build (whisper-bin-x64.zip, ~4 MB) into his add-ons folder.
- Mac: Homebrew's whisper-cpp.
- Linux: there is no ready-made download; if you have whisper-cli (built yourself or from your
  package manager) Joe finds it and uses it.
Models are the ggml files from huggingface.co/ggerganov/whisper.cpp (same Whisper models, MIT).
Only the program and the model are downloaded, never your recordings.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .system import LINUX, MAC, WINDOWS

RELEASE = "https://github.com/ggml-org/whisper.cpp/releases/latest/download/"
WIN_ZIP = "whisper-bin-x64.zip"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
MODEL_MB = {"tiny": 75, "tiny.en": 75, "base": 142, "base.en": 142, "small": 466, "small.en": 466,
            "medium": 1500, "medium.en": 1500, "large-v3": 3100, "large-v3-turbo": 1600}


def home() -> Path:
    from .addons import addons_dir
    return addons_dir() / "whispercpp"


def exe() -> str | None:
    """whisper-cli: Joe's own copy, then PATH / the usual folders (brew, winget...)."""
    name = "whisper-cli.exe" if WINDOWS else "whisper-cli"
    try:
        own = [p for p in home().rglob(name) if p.is_file()]
    except OSError:
        own = []
    if own:
        return str(own[0])
    from .finder import find_tool
    return find_tool("whisper-cli", "", ("whisper.cpp", "whisper-cpp")) or shutil.which("whisper-cpp")


def can_install() -> bool:
    return WINDOWS or (MAC and bool(shutil.which("brew") or Path("/opt/homebrew/bin/brew").exists()))


def model_name(stt_model: str) -> str:
    """Joe's hearing model name (faster-whisper style) -> the ggml file name part."""
    n = (stt_model or "base.en").strip()
    n = re.sub(r"^distil-", "", n)
    if n in ("large", "large-v2"):
        n = "large-v3"
    if n == "turbo":
        n = "large-v3-turbo"
    return n if n in MODEL_MB else "base.en"


def model_file(stt_model: str) -> Path:
    return home() / "models" / f"ggml-{model_name(stt_model)}.bin"


def ready(stt_model: str = "") -> bool:
    return bool(exe()) and (not stt_model or model_file(stt_model).exists())


def install(log, approved: bool = False, progress=None) -> bool:
    """Get the whisper-cli program (the person said yes in the window)."""
    if not approved:
        raise PermissionError("install needs the user's approval")
    if exe():
        return True
    if WINDOWS:
        import zipfile
        from .addons import _download
        d = home()
        d.mkdir(parents=True, exist_ok=True)
        z = d / WIN_ZIP
        log(f"Downloading whisper.cpp ({WIN_ZIP}, about 4 MB, MIT license)...")
        if not _download(RELEASE + WIN_ZIP, z, log, progress):
            return False
        try:
            with zipfile.ZipFile(z) as f:
                f.extractall(d / "bin")
        except (OSError, zipfile.BadZipFile) as e:
            log(f"Couldn't unpack whisper.cpp: {e}")
            return False
        finally:
            try:
                z.unlink()
            except OSError:
                pass
    elif MAC:
        brew = shutil.which("brew") or "/opt/homebrew/bin/brew"
        log("Installing whisper.cpp with Homebrew (brew install whisper-cpp)...")
        try:
            p = subprocess.run([brew, "install", "whisper-cpp"], capture_output=True, text=True, timeout=1800)
        except (OSError, subprocess.SubprocessError) as e:
            log(f"Homebrew couldn't install it: {e}")
            return False
        if p.returncode != 0:
            log((p.stderr or p.stdout or "Homebrew couldn't install it.")[-400:])
    elif LINUX:
        log("There's no ready-made whisper.cpp download for Linux. If your package manager has it "
            "(or you build it from github.com/ggml-org/whisper.cpp), Joe finds whisper-cli by himself.")
        return False
    ok = bool(exe())
    log("whisper.cpp is ready." if ok else "whisper.cpp didn't install.")
    return ok


def get_model(stt_model: str, log, progress=None) -> Path | None:
    """The ggml model file, downloaded once (asked for when the tool first needs it)."""
    f = model_file(stt_model)
    if f.exists():
        return f
    from .addons import _download
    f.parent.mkdir(parents=True, exist_ok=True)
    n = model_name(stt_model)
    log(f"Downloading the Whisper model for whisper.cpp ({n}, about {MODEL_MB[n]} MB, MIT license; "
        "only the model, never your recording)...")
    return f if _download(MODEL_URL.format(name=n), f, log, progress) else None


def _threads() -> int:
    import os
    return max(1, min(8, (os.cpu_count() or 4) - 1))


def parse_json(data: dict, words: bool = False) -> dict:
    """whisper-cli -oj output -> the voice helper's shape: segments [{s, e, t}] + language."""
    segs = []
    for row in data.get("transcription") or []:
        off = row.get("offsets") or {}
        t = (row.get("text") or "").strip()
        if not t:
            continue
        segs.append({"s": round(off.get("from", 0) / 1000, 2), "e": round(off.get("to", 0) / 1000, 2), "t": t})
    lang = ((data.get("result") or {}).get("language") or "").strip()
    out = {"ok": True, "language": lang}
    if words:
        out["words"] = segs
        out["segments"] = join_words(segs)
    else:
        out["segments"] = segs
    out["seconds"] = segs[-1]["e"] if segs else 0.0
    return out


def join_words(words: list[dict], max_gap: float = 0.8, max_len: float = 8.0) -> list[dict]:
    """Word-by-word times -> sentence-sized segments (for transcripts made with word times)."""
    out: list[dict] = []
    for w in words:
        if out and w["s"] - out[-1]["e"] <= max_gap and w["e"] - out[-1]["s"] <= max_len \
                and not re.search(r"[.!?]$", out[-1]["t"]):
            out[-1]["e"] = w["e"]
            out[-1]["t"] = (out[-1]["t"] + " " + w["t"]).strip()
        else:
            out.append(dict(w))
    return out


def transcribe(wav: Path, stt_model: str, language: str = "", words: bool = False,
               log=print, timeout: float = 7200) -> dict:
    """One 16 kHz WAV -> {"ok", "segments", "seconds", "language"[, "words"]} (like the voice helper)."""
    cli = exe()
    if not cli:
        return {"ok": False, "error": "whisper.cpp isn't installed"}
    model = get_model(stt_model, log)
    if not model:
        return {"ok": False, "error": "couldn't download the whisper.cpp model"}
    lang = "en" if model_name(stt_model).endswith(".en") else (language or "auto")
    base = wav.with_suffix("")
    cmd = [cli, "-m", str(model), "-f", str(wav), "-l", lang, "-t", str(_threads()), "-oj", "-of", str(base),
           "-np"]
    if words:
        cmd += ["-ml", "1", "-sow"]
    from .system import no_window_flags
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=no_window_flags())
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "whisper.cpp took too long"}
    except OSError as e:
        return {"ok": False, "error": f"couldn't start whisper.cpp: {e}"}
    out = base.with_suffix(".json")
    try:
        data = json.loads(out.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        tail = (p.stderr or "").strip().splitlines()[-1:] or ["no result"]
        return {"ok": False, "error": f"whisper.cpp: {tail[0]}"[:200]}
    finally:
        try:
            out.unlink()
        except OSError:
            pass
    return parse_json(data, words)
