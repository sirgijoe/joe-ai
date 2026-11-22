"""Small preview copies of pictures for the lists in Joe's window (2.3).

A triple-monitor wallpaper is tens of megabytes; the picture strip on Home and the Files list used
to load every one in full, so twenty wallpapers were finished before the first one showed. Now the
lists ask for /thumb, a 320-pixel JPEG that FFmpeg makes once and Joe keeps in his own temporary
folder (named by the file's path, size and date, so a changed picture gets a new one). The full
picture is only loaded when it is the one being looked at, or in the BIG WINDOW.

No FFmpeg, a picture FFmpeg can't read, or anything else going wrong: the caller sends the full
picture, exactly as before. Nothing is written into the Joe folder and the original is never changed.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

SIZE = 320                 # longest side, pixels
MIN_BYTES = 150_000        # a picture smaller than this is sent as it is (no point making a copy)
KEEP_DAYS = 14             # preview copies not looked at for this long are deleted
MAX_FILES = 4000
TYPES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}       # not .gif: its thumbnail would stop moving
_lock = threading.Lock()
_busy: dict[str, threading.Lock] = {}
_swept = 0.0


def folder() -> Path:
    d = Path(tempfile.gettempdir()) / "joe-ai-previews"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def name_for(p: Path) -> str:
    st = p.stat()
    key = f"{p.resolve()}|{st.st_size}|{st.st_mtime_ns}|{SIZE}"
    return hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()[:32] + ".jpg"


def wanted(p: Path) -> bool:
    """Is a preview copy worth making for this file?"""
    try:
        return p.suffix.lower() in TYPES and p.stat().st_size >= MIN_BYTES
    except OSError:
        return False


def make(p: Path, ffmpeg: str | None, timeout: float = 20.0) -> Path | None:
    """The preview copy of picture `p` (made now if there is none yet), or None to send the original."""
    if not ffmpeg or not wanted(p):
        return None
    try:
        out = folder() / name_for(p)
    except OSError:
        return None
    if out.is_file() and out.stat().st_size > 0:
        try:
            os.utime(out, None)                      # looked at: keep it
        except OSError:
            pass
        return out
    with _lock:
        mine = _busy.setdefault(out.name, threading.Lock())
    with mine:                                        # two lists asking for the same picture: one FFmpeg run
        if out.is_file() and out.stat().st_size > 0:
            return out
        tmp = out.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp.jpg")
        cmd = [ffmpeg, "-v", "error", "-y", "-i", str(p), "-frames:v", "1",
               "-vf", f"scale='min({SIZE},iw)':'min({SIZE},ih)':force_original_aspect_ratio=decrease",
               "-q:v", "5", "-f", "image2", str(tmp)]
        try:
            kw = {"creationflags": 0x08000000} if os.name == "nt" else {}       # no console window flashing
            r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=timeout, **kw)
            if r.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 0:
                os.replace(tmp, out)
                return out
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
            with _lock:
                _busy.pop(out.name, None)
    return None


def sweep(now: float | None = None) -> int:
    """Delete old preview copies (at most once an hour). Returns how many went."""
    global _swept
    now = time.time() if now is None else now
    if now - _swept < 3600:
        return 0
    _swept = now
    gone = 0
    try:
        files = sorted((f for f in folder().glob("*.jpg")), key=lambda f: f.stat().st_mtime)
    except OSError:
        return 0
    extra = max(0, len(files) - MAX_FILES)
    for i, f in enumerate(files):
        try:
            if i < extra or now - f.stat().st_mtime > KEEP_DAYS * 86400:
                f.unlink()
                gone += 1
        except OSError:
            pass
    return gone
