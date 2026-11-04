"""Everything that differs between Windows, Mac and Linux, in one place.

New code asks this module instead of checking sys.platform itself, so every tool works on all
three systems. Standard library only.

- folders: config_dir(), data_dir(), default_workspace()
- opening things: app_browser(), open_window(url), open_path(p), reveal(p), open_in_editor(p)
- power: keep_awake(), when_finished(action)
- memory: ram_total_gb()
- installing programs: package_manager(), install_plan(tool)
- starting programs in the background: popen_detached(cmd)
"""
from __future__ import annotations

import contextlib
import ctypes
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Callable

Log = Callable[[str], None]

WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"
LINUX = not WINDOWS and not MAC


def name() -> str:
    """'windows', 'mac' or 'linux' (anything else Unix-like counts as linux)."""
    return "windows" if WINDOWS else "mac" if MAC else "linux"


def pretty_name() -> str:
    return {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[name()]


# --------------------------------------------------------------------------- folders
def config_dir() -> Path:
    """Settings, chats index, window profile. Small files."""
    if WINDOWS:
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "joe-ai"


def data_dir() -> Path:
    """Add-ons, voice environment, logs. Can be big (gigabytes)."""
    if WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "joe-ai"


def documents_dir() -> Path:
    docs = Path.home() / "Documents"
    if LINUX:                                   # respect a renamed Documents folder
        try:
            out = subprocess.run(["xdg-user-dir", "DOCUMENTS"], capture_output=True, text=True,
                                 timeout=3).stdout.strip()
            if out and Path(out).is_dir() and Path(out) != Path.home():
                docs = Path(out)
        except (OSError, subprocess.SubprocessError):
            pass
    return docs if docs.is_dir() else Path.home()


def default_workspace() -> Path:
    return documents_dir() / "Joe-ai"


# --------------------------------------------------------------------------- opening things
_WIN_BROWSERS = (("Microsoft", "Edge", "Application", "msedge.exe"),
                 ("Google", "Chrome", "Application", "chrome.exe"),
                 ("BraveSoftware", "Brave-Browser", "Application", "brave.exe"))
_MAC_BROWSERS = ("Microsoft Edge", "Google Chrome", "Chromium", "Brave Browser")
_LINUX_BROWSERS = ("microsoft-edge", "microsoft-edge-stable", "google-chrome", "google-chrome-stable",
                   "chromium", "chromium-browser", "brave-browser")


def app_browser() -> str | None:
    """A Chromium-type browser that can open Joe as its own app window (no tabs or address bar).
    Edge ships with Windows; on Mac and Linux we use whichever of Edge/Chrome/Chromium/Brave is
    there. None = open in the normal default browser instead."""
    if WINDOWS:
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                     os.environ.get("LOCALAPPDATA")):
            for parts in _WIN_BROWSERS:
                if base and (Path(base).joinpath(*parts)).exists():
                    return str(Path(base).joinpath(*parts))
        return shutil.which("msedge") or shutil.which("chrome")
    if MAC:
        for app in _MAC_BROWSERS:
            for root in (Path("/Applications"), Path.home() / "Applications"):
                exe = root / f"{app}.app" / "Contents" / "MacOS" / app
                if exe.exists():
                    return str(exe)
        return None
    for b in _LINUX_BROWSERS:
        found = shutil.which(b)
        if found:
            return found
    return None


def open_window(url: str, profile: Path) -> None:
    """Open Joe's window. App mode when we can, else the default browser."""
    exe = app_browser()
    if not exe:
        webbrowser.open(url)
        return
    popen_detached([exe, f"--app={url}", f"--user-data-dir={profile}",
                    "--no-first-run", "--no-default-browser-check",
                    # Joe's own window may play his hello and chimes without a click first
                    "--autoplay-policy=no-user-gesture-required",
                    "--window-size=1280,860"])


def open_path(p: Path) -> None:
    """Open a file or folder with whatever program the system uses for it."""
    if WINDOWS:
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif MAC:
        popen_detached(["open", str(p)])
    else:
        popen_detached(["xdg-open", str(p)])


def reveal(p: Path) -> None:
    """Show a file in its folder (selected where the system can), or open a folder."""
    if p.is_dir():
        open_path(p)
    elif WINDOWS:
        subprocess.Popen(["explorer", f"/select,{p}"])
    elif MAC:
        popen_detached(["open", "-R", str(p)])
    else:
        open_path(p.parent)                    # Linux file managers differ; open the folder


def open_in_editor(p: Path) -> None:
    """Open a text file in a plain text editor."""
    if WINDOWS:
        subprocess.Popen(["notepad.exe", str(p)])
    elif MAC:
        popen_detached(["open", "-t", str(p)])
    else:
        editor = next((e for e in ("gnome-text-editor", "gedit", "kate", "mousepad", "xed")
                       if shutil.which(e)), None)
        popen_detached([editor, str(p)] if editor else ["xdg-open", str(p)])


def popen_detached(cmd: list[str] | str, cwd: str | None = None) -> subprocess.Popen:
    """Start a program in the background with no console window; it outlives Joe."""
    kwargs: dict = {"cwd": cwd or None, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if WINDOWS:
        kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW            # type: ignore[attr-defined]
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, shell=isinstance(cmd, str), **kwargs)


def no_window_flags() -> int:
    """creationflags for a short command whose output we read (no console flash on Windows)."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if WINDOWS else 0


# --------------------------------------------------------------------------- power
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


@contextlib.contextmanager
def keep_awake(enabled: bool = True, log: Log | None = None):
    """Stop the computer from sleeping while the block runs (the screen may still turn off)."""
    if not enabled:
        yield
        return
    if WINDOWS:
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        k32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
        try:
            yield
        finally:
            k32.SetThreadExecutionState(_ES_CONTINUOUS)
        return
    if MAC:
        cmd = ["caffeinate", "-i", "-w", str(os.getpid())]
    else:
        cmd = ["systemd-inhibit", "--what=idle:sleep", "--who=Joe", "--why=Joe is working",
               "--mode=block", "sleep", "infinity"]
    proc = None
    if shutil.which(cmd[0]):
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    stdin=subprocess.DEVNULL)
        except OSError:
            proc = None
    if proc is None and log:
        log(f"Couldn't keep the computer awake ({cmd[0]} not available). Turn off sleep in your "
            "system settings for long runs.")
    try:
        yield
    finally:
        if proc is not None:
            proc.terminate()


def when_finished(action: str, log: Log = print) -> None:
    """'sleep' or 'shutdown' after a run. Shutdown waits 2 minutes and can be cancelled."""
    if action not in ("sleep", "shutdown"):
        return
    if WINDOWS:
        if action == "shutdown":
            log("Shutting down in 120 s (run 'shutdown /a' to cancel).")
            cmd = ["shutdown", "/s", "/t", "120", "/c", "Joe finished."]
        else:
            log("Putting the PC to sleep.")
            cmd = ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]
    elif MAC:
        if action == "shutdown":
            log("Shutting down. macOS may ask you to confirm.")
            cmd = ["osascript", "-e", 'tell application "System Events" to shut down']
        else:
            log("Putting the Mac to sleep.")
            cmd = ["pmset", "sleepnow"]
    else:
        if action == "shutdown":
            log("Shutting down in 2 minutes (run 'shutdown -c' to cancel).")
            cmd = ["shutdown", "-h", "+2", "Joe finished."]
        else:
            log("Putting the computer to sleep.")
            cmd = ["systemctl", "suspend"]
    try:
        subprocess.run(cmd, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        log(f"Couldn't {action}: {e}")


# --------------------------------------------------------------------------- memory
def ram_total_gb() -> float:
    if WINDOWS:
        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):  # type: ignore[attr-defined]
            return round(m.ullTotalPhys / 2**30, 1)
        return 0.0
    if MAC:
        try:
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
                                 timeout=5).stdout.strip()
            return round(int(out) / 2**30, 1)
        except (OSError, subprocess.SubprocessError, ValueError):
            return 0.0
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except (ValueError, OSError, AttributeError):
        return 0.0


# --------------------------------------------------------------------------- installing programs
# Package ids per package manager. A missing id means: open the official download page instead.
PACKAGES: dict[str, dict[str, str]] = {
    "ollama":  {"winget": "Ollama.Ollama", "brew": "ollama", "pacman": "ollama"},
    "comfyui": {"winget": "Comfy.ComfyUI-Desktop"},
    "ffmpeg":  {"winget": "Gyan.FFmpeg", "brew": "ffmpeg", "apt": "ffmpeg", "dnf": "ffmpeg",
                "pacman": "ffmpeg"},
    "pandoc":  {"winget": "JohnMacFarlane.Pandoc", "brew": "pandoc", "apt": "pandoc",
                "dnf": "pandoc", "pacman": "pandoc"},
    "uv":      {"winget": "astral-sh.uv", "brew": "uv", "pacman": "uv"},
}
_MAC_CASKS = {"ollama"}            # Homebrew installs these as apps (--cask)


def package_manager() -> str | None:
    """winget on Windows, Homebrew on Mac, apt/dnf/pacman on Linux, or None."""
    if WINDOWS:
        return "winget" if shutil.which("winget") else None
    if MAC:
        return "brew" if (shutil.which("brew") or Path("/opt/homebrew/bin/brew").exists()
                          or Path("/usr/local/bin/brew").exists()) else None
    for pm in ("apt", "dnf", "pacman"):
        if shutil.which(pm if pm != "apt" else "apt-get"):
            return pm
    return None


def _brew() -> str:
    return shutil.which("brew") or next(
        (p for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew") if Path(p).exists()), "brew")


def install_plan(tool: str) -> dict:
    """How Joe would install `tool` here.

    kind 'run'     -> Joe runs `cmd` himself (after the user said yes)
    kind 'command' -> needs an admin password, so Joe shows `cmd` for the user to paste in a
                      terminal (Linux apt/dnf/pacman); Joe never asks for or types passwords
    kind 'page'    -> no package here; open the official download page
    """
    ids = PACKAGES.get(tool, {})
    pm = package_manager()
    pid = ids.get(pm or "")
    if not pm or not pid:
        return {"kind": "page", "manager": pm}
    if pm == "winget":
        return {"kind": "run", "manager": pm,
                "cmd": [shutil.which("winget") or "winget", "install", "-e", "--id", pid,
                        "--accept-package-agreements", "--accept-source-agreements",
                        "--disable-interactivity"]}
    if pm == "brew":
        return {"kind": "run", "manager": pm,
                "cmd": [_brew(), "install"] + (["--cask"] if tool in _MAC_CASKS else []) + [pid]}
    cmd = {"apt": ["sudo", "apt-get", "install", "-y", pid],
           "dnf": ["sudo", "dnf", "install", "-y", pid],
           "pacman": ["sudo", "pacman", "-S", "--needed", pid]}[pm]
    return {"kind": "command", "manager": pm, "cmd": cmd}


def manager_label(pm: str | None) -> str:
    return {"winget": "winget", "brew": "Homebrew", "apt": "apt", "dnf": "dnf",
            "pacman": "pacman"}.get(pm or "", "your package manager")
