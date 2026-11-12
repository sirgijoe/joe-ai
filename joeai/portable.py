"""Portable Joe: run Joe from a USB drive (or any folder you carry around).

A portable Joe is a folder with a marker file (portable.txt) next to his program folder:

    Joe/                      <- the folder on the drive
      portable.txt            <- marker: "this Joe is portable" (and what that means)
      Start Joe.bat           <- Windows   | Start Joe.command <- Mac | start-joe.sh <- Linux
      app/                    <- Joe's program (+ a private Python when there is one)
      Joe-ai/                 <- Joe's folder: missions, inbox, everything he makes
      JoeData/settings/       <- settings, chats index, the window's profile
      JoeData/data/           <- add-ons: voice, Joe's own ComfyUI (+ its models), Ollama
      JoeData/data/ollama-models/   <- writing models, when Ollama lives on the drive

Level 1 is Joe himself on the drive (no %APPDATA%, no Documents folder used). Level 2 is
Ollama, ComfyUI and their models on the drive too: Joe puts them there from System check.
The computer still needs its own graphics drivers, and Windows may still remember that a
program ran (prefetch, the page file, the browser's cache): portable is not invisible.

Paths saved in the settings that point inside the drive are stored as {JOE}/..., so a
different drive letter (E: today, F: on another PC) doesn't break anything. Private Python
environments made on the drive are pointed at the new place when the drive letter changes.
Standard library only; nothing here runs unless the marker is there.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tarfile
import threading
import zipfile
from pathlib import Path
from typing import Callable

Log = Callable[[str], None]

MARKER = "portable.txt"
MARK_WORD = "Joe portable"            # the marker's first line must contain this
TOKEN = "{JOE}"                        # stands for the portable folder inside saved settings
OLLAMA_PORT = 11435                    # the drive's Ollama, so it never fights the PC's own (11434)
WIN = sys.platform == "win32"
MAC = sys.platform == "darwin"

MARKER_TEXT = f"""{MARK_WORD} - this folder is a portable copy of Joe (01000001 01001001).

Start Joe with "Start Joe.bat" (Windows), "Start Joe.command" (Mac) or start-joe.sh (Linux).
Everything Joe keeps stays in this folder: his settings (JoeData/settings), your work
(Joe-ai), and anything he sets up for you (JoeData/data: voice, Ollama, ComfyUI, models).

Good to know:
- Each computer still needs its own graphics driver. Joe uses the computer's Edge or Chrome
  for his window (its profile is kept in this folder too).
- Windows may still remember that a program ran (prefetch, the page file). Portable means
  "carried with you", not "leaves no trace".
- Use a fast USB 3 drive (an SSD is best) for Ollama, ComfyUI and models. A drive formatted
  as FAT32 can't hold files over 4 GB, which most models are: use exFAT or NTFS.
- Delete this file and Joe goes back to using the computer's own folders.
"""

_ROOT: dict = {}


# --------------------------------------------------------------------------- where things are
def program_root() -> Path:
    """The folder with Joe.pyw (and joeai/)."""
    return Path(__file__).resolve().parent.parent


def _has_marker(folder: Path) -> bool:
    try:
        with open(folder / MARKER, encoding="utf-8", errors="replace") as f:
            return MARK_WORD.lower() in f.readline().lower()
    except OSError:
        return False


def root() -> Path | None:
    """The portable folder, or None when Joe runs normally. JOE_PORTABLE=<folder> forces one
    (tests, or a hand-made layout); JOE_PORTABLE=0 turns it off."""
    env = os.environ.get("JOE_PORTABLE")
    if env is not None:
        if env.strip() in ("", "0"):
            return None
        return Path(env).expanduser().resolve()
    if "r" not in _ROOT:
        pr = program_root()
        _ROOT["r"] = next((d for d in (pr, pr.parent) if _has_marker(d)), None)
    return _ROOT["r"]


def active() -> bool:
    return root() is not None


def forget() -> None:
    """Look for the marker again next time (tests)."""
    _ROOT.clear()


def data_root() -> Path:
    return root() / "JoeData"            # type: ignore[operator]


def config_dir() -> Path:
    return data_root() / "settings"


def data_dir() -> Path:
    return data_root() / "data"


def workspace() -> Path:
    return root() / "Joe-ai"             # type: ignore[operator]


def ollama_models_dir() -> Path:
    return data_dir() / "ollama-models"


def ollama_dir() -> Path:
    return data_dir() / "addons" / "ollama"


def own_comfy_dir() -> Path:
    return data_dir() / "addons" / "comfyui" / "ComfyUI"


def drive_ollama() -> Path | None:
    """Ollama's program on the drive (put there by install_ollama), or None."""
    if not active():
        return None
    d = ollama_dir()
    for p in (d / "ollama.exe", d / "bin" / "ollama", d / "ollama",
              d / "Ollama.app" / "Contents" / "Resources" / "ollama"):
        if p.is_file():
            return p
    return None


def drive_comfy() -> bool:
    return active() and (own_comfy_dir() / "main.py").is_file()


def ollama_url() -> str:
    return f"http://127.0.0.1:{OLLAMA_PORT}"


# --------------------------------------------------------------------------- start-up
ENV_DIRS = {"UV_CACHE_DIR": "uv-cache", "UV_PYTHON_INSTALL_DIR": "uv-python", "UV_TOOL_DIR": "uv-tools",
            "HF_HOME": "huggingface", "TORCH_HOME": "torch", "PIP_CACHE_DIR": "pip-cache"}


def apply_env() -> None:
    """Point every helper's downloads and caches at the drive, so nothing big lands on the PC.
    Programs Joe starts inherit these. Safe to call more than once."""
    if not active():
        return
    for k, sub in ENV_DIRS.items():
        os.environ[k] = str(data_dir() / sub)
    os.environ["UV_PYTHON_PREFERENCE"] = "only-managed"     # never tie a drive Python to this PC's
    tmp = data_dir() / "tmp"                                # scratch files stay on the drive too
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        for k in ("TMP", "TEMP", "TMPDIR"):
            os.environ[k] = str(tmp)
        import tempfile
        tempfile.tempdir = None                             # look again
    except OSError:
        pass
    if drive_ollama():
        os.environ["OLLAMA_MODELS"] = str(ollama_models_dir())
        os.environ["OLLAMA_HOST"] = f"127.0.0.1:{OLLAMA_PORT}"


def _same(a: str, b: str) -> bool:
    return a.lower() == b.lower() if WIN else a == b


def relink(log: Log | None = None) -> int:
    """When the drive's letter (or mount point) changed since last time, point the private
    Python environments on the drive at the new place. Returns how many files changed."""
    if not active():
        return 0
    here = str(root())
    mark = data_root() / "last_place.txt"
    try:
        old = mark.read_text(encoding="utf-8").strip()
    except OSError:
        old = ""
    changed = 0
    if old and not _same(old, here):
        changed = _rewrite_venvs(data_dir(), old, here)
        if log and changed:
            log(f"The drive moved ({old} -> {here}); pointed {changed} helper environment(s) at the new place.")
    if old != here:
        try:
            data_root().mkdir(parents=True, exist_ok=True)
            mark.write_text(here, encoding="utf-8")
        except OSError:
            pass
    return changed


def start(log: Log | None = None) -> None:
    """Called first thing when Joe starts: caches on the drive, environments relinked."""
    if active():
        apply_env()
        try:
            relink(log)
        except OSError:
            pass


_SKIP_WALK = {"models", "lib", "site-packages", "node_modules", "output", "input", "user",
              "ollama-models", "huggingface", "uv-cache", "pip-cache", "torch", "custom_nodes"}


def _rewrite_venvs(top: Path, old: str, new: str, depth: int = 5) -> int:
    pat = re.compile(re.escape(old), re.I if WIN else 0)
    n = 0
    for dirpath, dirs, files in os.walk(top):
        rel = Path(dirpath).relative_to(top)
        if len(rel.parts) >= depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d.lower() not in _SKIP_WALK]
        if "pyvenv.cfg" not in files:
            continue
        cfg = Path(dirpath) / "pyvenv.cfg"
        try:
            txt = cfg.read_text(encoding="utf-8")
            new_txt = pat.sub(lambda _m: new, txt)
            if new_txt != txt:
                cfg.write_text(new_txt, encoding="utf-8")
                n += 1
        except OSError:
            continue
        if not WIN:                                   # Mac/Linux: bin/python* are links to the base Python
            for link in (Path(dirpath) / "bin").glob("python*"):
                try:
                    if link.is_symlink():
                        target = os.readlink(link)
                        if pat.search(target):
                            link.unlink()
                            link.symlink_to(pat.sub(lambda _m: new, target))
                            n += 1
                except OSError:
                    continue
    return n


# --------------------------------------------------------------------------- settings paths
def _walk(obj, fn):
    if isinstance(obj, dict):
        return {k: _walk(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(v, fn) for v in obj]
    if isinstance(obj, str):
        return fn(obj)
    return obj


def pack(data: dict) -> dict:
    """Before saving: paths inside the portable folder become {JOE}/..."""
    if not active():
        return data
    here = str(root())
    pat = re.compile(re.escape(here), re.I if WIN else 0)
    return _walk(data, lambda s: pat.sub(lambda _m: TOKEN, s) if pat.search(s) else s)


def unpack(data: dict) -> dict:
    """After loading: {JOE}/... becomes this drive's real folder."""
    here = str(root()) if active() else ""
    if not here:
        return data
    return _walk(data, lambda s: s.replace(TOKEN, here) if TOKEN in s else s)


def adjust_settings(s) -> None:
    """Addresses that follow what's on the drive: the drive's own Ollama (port 11435) and
    Joe's own ComfyUI (8188), instead of the PC's."""
    if not active():
        return
    if drive_ollama():
        if s.ollama.url.rstrip("/") in ("http://127.0.0.1:11434", "http://localhost:11434"):
            s.ollama.url = ollama_url()
    elif s.ollama.url.rstrip("/") == ollama_url():
        s.ollama.url = "http://127.0.0.1:11434"
    if drive_comfy() and s.comfy.url.rstrip("/") in ("http://127.0.0.1:8000", "http://localhost:8000"):
        s.comfy.url = "http://127.0.0.1:8188"


# --------------------------------------------------------------------------- what's on the drive
def filesystem(path: Path) -> str:
    """'NTFS', 'exFAT', 'FAT32', 'ext4', 'apfs'... or '' when it can't be told."""
    try:
        if WIN:
            import ctypes
            drive = os.path.splitdrive(str(Path(path).resolve()))[0] + "\\"
            buf = ctypes.create_unicode_buffer(64)
            ok = ctypes.windll.kernel32.GetVolumeInformationW(          # type: ignore[attr-defined]
                ctypes.c_wchar_p(drive), None, 0, None, None, None, buf, 64)
            return buf.value if ok else ""
        if MAC:
            import subprocess
            out = subprocess.run(["stat", "-f", "%T", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=5).stdout.strip()
            return out
        best, kind = "", ""
        real = str(Path(path).resolve())
        with open("/proc/mounts", encoding="utf-8") as f:
            for ln in f:
                parts = ln.split()
                if len(parts) > 2 and real.startswith(parts[1]) and len(parts[1]) > len(best):
                    best, kind = parts[1], parts[2]
        return {"vfat": "FAT32", "exfat": "exFAT", "ntfs": "NTFS", "ntfs3": "NTFS",
                "fuseblk": "NTFS"}.get(kind, kind)
    except Exception:          # noqa: BLE001 (just unknown)
        return ""


def free_gb(path: Path) -> float:
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(p).free / 1e9
    except OSError:
        return 0.0


def folder_size(p: Path | None, skip: tuple[str, ...] = ()) -> int:
    if not p or not Path(p).is_dir():
        return 0
    total = 0
    for dirpath, dirs, files in os.walk(p):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def info(settings=None) -> dict:
    """For Setup > General: is this portable, and what lives where."""
    if not active():
        return {"active": False}
    fs = filesystem(root())
    return {"active": True, "root": str(root()), "filesystem": fs,
            "fat32": fs.upper() in ("FAT32", "FAT", "VFAT", "MSDOS"),
            "free_gb": round(free_gb(root()), 1),
            "ollama_on_drive": bool(drive_ollama()), "comfy_on_drive": drive_comfy()}


# --------------------------------------------------------------------------- Ollama on the drive
OLLAMA_ASSETS = {
    ("windows", "x64"): ("ollama-windows-amd64.zip",),
    ("windows", "arm64"): ("ollama-windows-arm64.zip",),
    ("linux", "x64"): ("ollama-linux-amd64.tgz", "ollama-linux-amd64.tar.zst"),
    ("linux", "arm64"): ("ollama-linux-arm64.tgz", "ollama-linux-arm64.tar.zst"),
    ("mac", "x64"): ("ollama-darwin.tgz", "Ollama-darwin.zip"),
    ("mac", "arm64"): ("ollama-darwin.tgz", "Ollama-darwin.zip"),
}


def _plat() -> tuple[str, str]:
    import platform
    m = platform.machine().lower()
    return ("windows" if WIN else "mac" if MAC else "linux",
            "arm64" if m in ("arm64", "aarch64") else "x64")


def _safe_members(names: list[str]) -> None:
    for n in names:
        if n.startswith(("/", "\\")) or ".." in Path(n.replace("\\", "/")).parts:
            raise ValueError("unsafe path in download: " + n)


def unpack_archive(arc: Path, dest: Path) -> None:
    """zip, .tgz or .tar.zst (the last needs Python 3.14's zstd) into dest."""
    dest.mkdir(parents=True, exist_ok=True)
    name = arc.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(arc) as z:
            _safe_members(z.namelist())
            z.extractall(dest)
        return
    if name.endswith((".tgz", ".tar.gz")):
        mode, fobj = "r:gz", None
    elif name.endswith(".tar.zst"):
        try:
            from compression import zstd          # type: ignore[import-not-found]  # Python 3.14+
        except ImportError as e:
            raise ValueError("this Ollama download is .tar.zst, which needs a newer Python") from e
        fobj = zstd.open(arc, "rb")
        mode = "r|"
    else:
        raise ValueError("unknown download type: " + arc.name)
    with (tarfile.open(arc, mode) if fobj is None else tarfile.open(fileobj=fobj, mode=mode)) as t:
        members = t.getmembers() if fobj is None else None
        if members is not None:
            _safe_members([m.name for m in members])
        t.extractall(dest, filter="data")          # Python 3.11.4+: no links or paths outside dest
    if fobj is not None:
        fobj.close()


def install_ollama(log: Log, fetch=None, download=None) -> bool:
    """Ollama's official release from GitHub into JoeData/data/addons/ollama. It runs on its own
    port (11435) with its models in JoeData/data/ollama-models, so it never touches the PC's Ollama."""
    if not active():
        log("Joe isn't running from a portable folder.")
        return False
    from .http import HttpError, request_json
    from .upkeep import OLLAMA_REPO, latest_release
    try:
        rel = latest_release(OLLAMA_REPO, fetch or request_json)
    except HttpError as e:
        log(f"Couldn't reach Ollama's GitHub page: {e}")
        return False
    assets = {a.get("name"): a for a in rel.get("assets") or []}
    want = OLLAMA_ASSETS.get(_plat(), ())
    pick = next((assets[n] for n in want if n in assets), None)
    if not pick:
        log("Ollama's newest release has no download Joe can unpack for this computer. "
            "Joe keeps using the PC's own Ollama (if it has one).")
        return False
    if pick["name"].endswith(".tar.zst"):
        try:
            from compression import zstd  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            log("Ollama now ships for Linux as .tar.zst, which this Python can't unpack. "
                "Joe keeps using the PC's own Ollama.")
            return False
    size = int(pick.get("size") or 0) / 1e9
    if size and free_gb(root()) < size * 2.2:
        log(f"Not enough room on the drive for Ollama (needs about {size * 2.2:.1f} GB while unpacking).")
        return False
    tmp = data_dir() / "addons" / pick["name"]
    tmp.parent.mkdir(parents=True, exist_ok=True)
    log(f"Downloading Ollama {rel.get('tag_name', '')} onto the drive"
        + (f" (about {size:.1f} GB)" if size else "") + "...")
    from .doctor import _download
    if not (download or _download)(pick["browser_download_url"], tmp, log):
        return False
    target = ollama_dir()
    new = target.with_name("ollama.new")
    try:                                     # unpack beside the old one; swap only when it worked
        shutil.rmtree(new, ignore_errors=True)
        unpack_archive(tmp, new)
        if target.exists():
            old = target.with_name("ollama.old")
            shutil.rmtree(old, ignore_errors=True)
            target.rename(old)
            shutil.rmtree(old, ignore_errors=True)
        new.rename(target)
    except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError) as e:
        log(f"Couldn't unpack Ollama: {e}. If it's running, close it and try again.")
        shutil.rmtree(new, ignore_errors=True)
        return False
    finally:
        tmp.unlink(missing_ok=True)
    exe = drive_ollama()
    if not exe:
        log("Ollama was unpacked, but Joe couldn't find its program inside. Nothing else was changed.")
        return False
    if not WIN:
        try:
            exe.chmod(0o755)
        except OSError:
            pass
    ollama_models_dir().mkdir(parents=True, exist_ok=True)
    apply_env()
    log(f"Ollama is on the drive. Joe starts it on port {OLLAMA_PORT}, with its models kept on the drive. "
        "Restart Joe, then get a writing model from System check.")
    return True


# --------------------------------------------------------------------------- MAKE A PORTABLE JOE
PROGRAM_SKIP = {"__pycache__", ".git", ".github", "tests", "build", "dist", "pbs", ".pytest_cache",
                ".venv", "installer", "NEXT_STEPS.md", "NOTES_HISTORY.md", "STYLE_NOTES.md", "IDEAS.md",
                "_install.json", "workspace", "settings.json", "python",    # python/ is copied on its own
                "unins000.exe", "unins000.dat", "unins000.msg"}
PY_SKIP = {"site-packages", "Doc", "Tools", "include", "__pycache__", "test", "tests", "idlelib",
           "Scripts", "libs"}
PATH_FIELDS = (("ollama", "exe"), ("comfy", "start_command"), ("comfy", "start_dir"),
               ("comfy", "models_dir"), ("comfy", "ffmpeg"), ("comfy", "output_dir"))


def bundled_python() -> Path | None:
    """A private Python that comes with this Joe (installer / app), copied along."""
    for d in (program_root() / "python", program_root().parent / "python"):
        if (d / ("pythonw.exe" if WIN else "bin/python3")).exists():
            return d
    return None


def _host_python() -> Path | None:
    """Windows from source: the python.org Python Joe runs on (copied without its add-ons)."""
    if not WIN:
        return None
    base = Path(sys.base_prefix)
    return base if (base / "pythonw.exe").exists() else None


def host_ollama_models() -> Path | None:
    env = os.environ.get("OLLAMA_MODELS")
    for p in ([Path(env)] if env else []) + [Path.home() / ".ollama" / "models",
                                               Path("/usr/share/ollama/.ollama/models")]:
        if (p / "manifests").is_dir():
            return p
    return None


def host_comfy_models(settings) -> Path | None:
    try:
        from .doctor import comfy_models_dir
        p = comfy_models_dir(settings)
        return p if p and p.is_dir() else None
    except Exception:          # noqa: BLE001
        return None


def plan(settings) -> dict:
    """What MAKE A PORTABLE JOE can copy, with sizes in GB."""
    from .config import config_path
    gb = lambda n: round(n / 1e9, 2)                  # noqa: E731
    py = bundled_python() or _host_python()
    prog = folder_size(program_root(), tuple(PROGRAM_SKIP)) + (
        folder_size(py, tuple(PY_SKIP)) if py else 0)
    om, cm = host_ollama_models(), host_comfy_models(settings)
    return {
        "program_gb": gb(prog), "python": bool(py),
        "python_note": "" if py else ("The drive copy will use the Python on each computer "
                                      "(3.11.4 or newer; python.org)."),
        "work": str(settings.workspace_path), "work_gb": gb(folder_size(settings.workspace_path)),
        "settings": config_path().exists(),
        "ollama_models_gb": gb(folder_size(om)) if om else 0, "ollama_models": str(om or ""),
        "comfy_models_gb": gb(folder_size(cm)) if cm else 0, "comfy_models": str(cm or ""),
    }


class Job:
    """One copy at a time, in the background; the window polls status()."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state: dict = {"running": False}
        self.stop = False

    def status(self) -> dict:
        with self.lock:
            return dict(self.state)

    def _set(self, **kw) -> None:
        with self.lock:
            self.state.update(kw)

    def start(self, settings, dest: str, opts: dict, log: Log) -> dict:
        if self.state.get("running"):
            return {"ok": False, "error": "A copy is already going."}
        err, target = check_dest(dest)
        if err:
            return {"ok": False, "error": err}
        p = plan(settings)
        need = p["program_gb"] + (p["work_gb"] if opts.get("work") else 0) + \
            (p["ollama_models_gb"] if opts.get("ollama_models") else 0) + \
            (p["comfy_models_gb"] if opts.get("comfy_models") else 0)
        have = free_gb(target)
        if have and need > have * 0.98:
            return {"ok": False, "error": f"Not enough room there: needs about {need:.1f} GB, "
                                          f"{have:.1f} GB free."}
        fs = filesystem(target)
        if fs.upper() in ("FAT32", "FAT", "VFAT", "MSDOS") and (opts.get("ollama_models") or opts.get("comfy_models")):
            return {"ok": False, "error": "That drive is FAT32, which can't hold files over 4 GB (most models). "
                                          "Format it as exFAT or NTFS first, or leave the models out."}
        self.stop = False
        self._set(running=True, done=0, total=int(need * 1e9), dest=str(target), msg="Starting…",
                  error="", finished=False)

        def go():
            try:
                make(settings, target, opts, log, self)
                self._set(msg="Done.", finished=True)
            except _Stopped:
                self._set(error="Stopped. What was copied so far is still there.")
            except Exception as e:          # noqa: BLE001 (show it, keep Joe going)
                self._set(error=f"The copy failed: {e}")
                log(f"MAKE A PORTABLE JOE failed: {e}")
            finally:
                self._set(running=False)
        self.thread = threading.Thread(target=go, daemon=True)
        self.thread.start()
        return {"ok": True, "dest": str(target)}

    def add(self, n: int) -> None:
        if self.stop:
            raise _Stopped()
        with self.lock:
            self.state["done"] = self.state.get("done", 0) + n


class _Stopped(Exception):
    pass


def check_dest(dest: str) -> tuple[str, Path]:
    """Where the portable Joe goes: <chosen folder>/Joe (unless it's already named Joe...)."""
    if not (dest or "").strip():
        return "Choose a drive or folder first.", Path()
    d = Path(dest.strip().strip('"')).expanduser()
    if not d.is_absolute():
        return "Use a full folder path, like E:\\ or /Volumes/MYDRIVE.", d
    if not d.exists():
        return "That folder doesn't exist.", d
    if _has_marker(d):                                # making it again: carry on in the same place
        target = d
    else:
        target = d if d.name.lower().startswith("joe") and not any(d.iterdir()) else d / "Joe"
    try:
        here = program_root().resolve()
        t = target.resolve()
        if t == here or here in t.parents or t in here.parents:
            return "Pick a place outside Joe's own program folder.", target
    except OSError:
        pass
    try:                                              # never inside what's being copied (it'd copy itself)
        from .config import Settings
        st = Settings.load()
        for src in (st.workspace_path, host_ollama_models(), host_comfy_models(st)):
            if src and (t == Path(src).resolve() or Path(src).resolve() in t.parents):
                return "Pick a place outside Joe's folder and the model folders.", target
    except Exception:                                 # noqa: BLE001
        pass
    if (target / "app").exists() and not _has_marker(target):
        return f"{target} already has an 'app' folder that isn't a portable Joe. Pick another place.", target
    return "", target


def _copy_tree(src: Path, dst: Path, job: Job | None, skip: set[str] = frozenset()) -> None:
    for dirpath, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in skip]
        rel = Path(dirpath).relative_to(src)
        out = dst / rel
        out.mkdir(parents=True, exist_ok=True)
        for f in files:
            if f in skip or f.endswith(".pyc"):
                continue
            s, t = Path(dirpath) / f, out / f
            try:
                if t.exists() and t.stat().st_size == s.stat().st_size and t.stat().st_mtime >= s.stat().st_mtime:
                    if job:
                        job.add(t.stat().st_size)
                    continue                         # already copied (a second run carries on)
                shutil.copy2(s, t)
                if job:
                    job.add(s.stat().st_size)
            except OSError as e:
                if e.errno == 27 or "too large" in str(e).lower():   # EFBIG on FAT32
                    raise OSError(f"{f} is too big for this drive (FAT32 stops at 4 GB)") from e
                raise


def start_files(target: Path) -> None:
    bat = ('@echo off\r\ncd /d "%~dp0app"\r\n'
           'if exist "python\\pythonw.exe" (\r\n  start "" "python\\pythonw.exe" "Joe.pyw"\r\n'
           ') else (\r\n  where pythonw >nul 2>nul && (start "" pythonw "Joe.pyw") || (start "" pyw -3 "Joe.pyw")\r\n)\r\n')
    sh = ('#!/bin/sh\n# Start the portable Joe from this folder.\ncd "$(dirname "$0")/app" || exit 1\n'
          '# Joe\'s own Python when it runs on this computer (it may have been made on another kind)\n'
          'if python/bin/python3 -c "" 2>/dev/null; then exec python/bin/python3 Joe.pyw; fi\n'
          'exec python3 Joe.pyw\n')
    (target / "Start Joe.bat").write_text(bat, encoding="utf-8", newline="")
    for name in ("Start Joe.command", "start-joe.sh"):
        p = target / name
        p.write_text(sh, encoding="utf-8", newline="\n")
        try:
            p.chmod(0o755)
        except OSError:
            pass
    (target / MARKER).write_text(MARKER_TEXT, encoding="utf-8")


def portable_settings(settings) -> dict:
    """This PC's settings for the drive: no program paths from this PC, Joe's folder = the drive's."""
    from dataclasses import asdict
    d = asdict(settings)
    d["workspace"] = ""
    for head, key in PATH_FIELDS:
        d[head][key] = ""
    d["pandoc"] = ""
    d["schedule"]["enabled"] = False
    d["mcp_key"] = ""                        # keys and the phone-ping topic stay off a drive that's easy to lose
    d["web"]["ollama_key"] = ""
    d["comfort"]["ntfy_topic"] = ""
    if d["ollama"]["url"].rstrip("/") == ollama_url():
        d["ollama"]["url"] = "http://127.0.0.1:11434"
    d["ui"]["welcomed"] = True
    return d


def make(settings, target: Path, opts: dict, log: Log, job: Job | None = None) -> Path:
    """Copy Joe (and whatever was ticked) to target. Safe to run again: carries on."""
    target.mkdir(parents=True, exist_ok=True)
    app = target / "app"
    st = (lambda m: job._set(msg=m)) if job else (lambda m: None)      # noqa: E731
    st("Copying Joe's program…")
    log(f"MAKE A PORTABLE JOE: copying Joe to {target}")
    _copy_tree(program_root(), app, job, PROGRAM_SKIP)
    py = bundled_python() or _host_python()
    if py and not (app / "python").exists():
        st("Copying Joe's Python…")
        _copy_tree(py, app / "python", job, PY_SKIP)
    start_files(target)
    data = target / "JoeData"
    (data / "settings").mkdir(parents=True, exist_ok=True)
    (target / "Joe-ai").mkdir(exist_ok=True)
    if opts.get("settings", True):
        dst = data / "settings" / "settings.json"
        if not dst.exists():
            dst.write_text(json.dumps(portable_settings(settings), indent=2), encoding="utf-8")
    if opts.get("work"):
        st("Copying your work…")
        log("Copying Joe's folder (your work)…")
        _copy_tree(settings.workspace_path, target / "Joe-ai", job)
    if opts.get("ollama_models"):
        src = host_ollama_models()
        if src:
            st("Copying writing models…")
            log("Copying the writing models (Ollama)…")
            _copy_tree(src, data / "data" / "ollama-models", job)
    if opts.get("comfy_models"):
        src = host_comfy_models(settings)
        if src:
            st("Copying picture models…")
            log("Copying the picture and video models (ComfyUI)…")
            _copy_tree(src, data / "data" / "addons" / "comfyui" / "ComfyUI" / "models", job)
    log(f"Portable Joe is ready in {target}. Start him there with 'Start Joe' "
        "(on another computer: put Ollama and ComfyUI on the drive from System check).")
    return target
