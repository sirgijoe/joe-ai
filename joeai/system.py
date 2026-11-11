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
    """Settings, chats index, window profile. Small files. (Portable Joe: on the drive.)"""
    from . import portable
    if portable.active():
        return portable.config_dir()
    if WINDOWS:
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "joe-ai"


def data_dir() -> Path:
    """Add-ons, voice environment, logs. Can be big (gigabytes). (Portable Joe: on the drive.)"""
    from . import portable
    if portable.active():
        return portable.data_dir()
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
            out = subprocess.run(["xdg-user-dir", "DOCUMENTS"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=3).stdout.strip()
            if out and Path(out).is_dir() and Path(out) != Path.home():
                docs = Path(out)
        except (OSError, subprocess.SubprocessError):
            pass
    return docs if docs.is_dir() else Path.home()


def default_workspace() -> Path:
    from . import portable
    if portable.active():
        return portable.workspace()
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
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, encoding="utf-8", errors="replace",
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
    "qpdf":    {"winget": "QPDF.QPDF", "brew": "qpdf", "apt": "qpdf", "dnf": "qpdf", "pacman": "qpdf"},
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
    from . import portable
    if portable.active() and tool in ("ollama", "comfyui"):   # portable: onto the drive, not the PC
        return {"kind": "joe", "manager": "joe"}
    ids = PACKAGES.get(tool, {})
    pm = package_manager()
    pid = ids.get(pm or "")
    if not pm or not pid:
        if tool == "comfyui" and not WINDOWS:          # Joe sets up his own copy (uv + GitHub)
            return {"kind": "joe", "manager": "joe"}
        if tool == "ollama" and MAC:                    # the official app, no Homebrew needed
            return {"kind": "joe", "manager": "joe"}
        if tool == "ollama" and LINUX:                  # Ollama's official install script (needs sudo)
            return {"kind": "command", "manager": "ollama",
                    "cmd": ["curl -fsSL https://ollama.com/install.sh | sh"]}
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
            "pacman": "pacman", "joe": "Joe", "ollama": "Ollama's install script"}.get(pm or "", "your package manager")


# --------------------------------------------------------------------------- fonts
def font_file() -> Path | None:
    """A plain sans-serif font file that ships with the system (for watermarks)."""
    import os
    if WINDOWS:
        root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        names = ["arialbd.ttf", "arial.ttf", "segoeuib.ttf", "segoeui.ttf", "verdana.ttf"]
        spots = [root / n for n in names]
    elif MAC:
        spots = [Path(p) for p in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                                   "/System/Library/Fonts/Supplemental/Arial.ttf",
                                   "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc")]
    else:
        spots = [Path(p) for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                                   "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                                   "/usr/share/fonts/TTF/DejaVuSans.ttf",
                                   "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                                   "/usr/share/fonts/noto/NotoSans-Regular.ttf")]
        for base in (Path("/usr/share/fonts"), Path.home() / ".local/share/fonts"):
            try:
                spots += sorted(base.rglob("*Sans*.ttf"))[:5]
            except OSError:
                pass
    return next((p for p in spots if p.is_file()), None)


# --------------------------------------------------------------------------- priority
# "Keep my PC usable" (Setup > General): the programs that do the heavy work run at below-normal
# priority, so the mouse, browser and games stay smooth. They still use the whole graphics card
# when nothing else wants it; a run only takes a little longer.
_BELOW_NORMAL = 0x00004000            # Windows BELOW_NORMAL_PRIORITY_CLASS
_NICE = 10                            # Mac/Linux: 0 = normal, 19 = lowest


def pids_on_port(port: int) -> list[int]:
    """Process ids listening on a local TCP port (the Ollama or ComfyUI server). [] if unknown."""
    import re as _re
    try:
        if WINDOWS:
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=15, creationflags=no_window_flags()).stdout
            pids = {int(m.group(1)) for m in _re.finditer(rf"[:.]{port}\s+\S+\s+LISTENING\s+(\d+)", out)}
        elif shutil.which("lsof"):
            out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15).stdout
            pids = {int(x) for x in out.split() if x.isdigit()}
        elif shutil.which("ss"):
            out = subprocess.run(["ss", "-ltnpH", f"sport = :{port}"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=15).stdout
            pids = {int(x) for x in _re.findall(r"pid=(\d+)", out)}
        else:
            return []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return sorted(p for p in pids if p > 4)


def pids_named(prefix: str) -> list[int]:
    """Running programs whose name starts with prefix (e.g. 'ollama': its model runners too)."""
    try:
        if WINDOWS:
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=15, creationflags=no_window_flags()).stdout
            pids = []
            for line in out.splitlines():
                cells = [c.strip('"') for c in line.split('","')]
                if len(cells) > 1 and cells[0].lower().startswith(prefix.lower()) and cells[1].isdigit():
                    pids.append(int(cells[1]))
            return pids
        if shutil.which("pgrep"):
            out = subprocess.run(["pgrep", "-i", f"^{prefix}"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=15).stdout
            return [int(x) for x in out.split() if x.isdigit()]
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return []


def lower_priority(pid: int) -> bool:
    """Below-normal priority for one running program. Programs it starts later inherit it."""
    if pid <= 4:
        return False
    if WINDOWS:
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        h = k32.OpenProcess(0x0200 | 0x0400, False, pid)   # SET_INFORMATION | QUERY_INFORMATION
        if not h:
            return False
        try:
            return bool(k32.SetPriorityClass(h, _BELOW_NORMAL))
        finally:
            k32.CloseHandle(h)
    try:
        if os.getpriority(os.PRIO_PROCESS, pid) >= _NICE:
            return True
        os.setpriority(os.PRIO_PROCESS, pid, _NICE)
        return True
    except (OSError, AttributeError):
        return False


def joe_command(sub: str, console: bool = True) -> list[str]:
    """How another program starts Joe with a command (mcp, tonight): the AppImage itself on
    Linux (its inside path changes every start), else this Python with Joe.pyw. console=False
    picks pythonw on Windows, so nothing flashes up at night."""
    appimage = os.environ.get("APPIMAGE")
    if appimage and Path(appimage).is_file():
        return [appimage, sub]
    exe = Path(sys.executable)
    if WINDOWS:
        want = "python.exe" if console else "pythonw.exe"
        if (exe.parent / want).exists():
            exe = exe.parent / want
    pyw = Path(__file__).resolve().parent.parent / "Joe.pyw"
    if pyw.exists():
        return [str(exe), str(pyw), sub]
    return [str(exe), "-m", "joeai", sub]


# --------------------------------------------------------------------------- disk space
def free_bytes(path: Path) -> int:
    """Free space on the drive holding path (or its nearest existing parent); -1 = unknown."""
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return -1


def gb(n: float) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{max(n, 0) / 1e6:.0f} MB"


def room_problem(path: Path, need: int, spare: int = 1_000_000_000) -> str:
    """'' when there's room for `need` bytes (plus a spare GB so the PC keeps working), else a plain
    sentence saying how much is needed and free."""
    free = free_bytes(path)
    if free < 0 or need <= 0 or free >= need + spare:
        return ""
    return (f"Not enough room on the drive: this needs about {gb(need + spare)} "
            f"(with a little left over so the computer keeps working), and {gb(free)} is free. "
            "Free some space (F9 > Storage can help), then try again.")


# --------------------------------------------------------------------------- choose a folder / file
_PICK_TK = r"""
import sys, tkinter as tk
from tkinter import filedialog
r = tk.Tk(); r.withdraw()
try:
    r.attributes("-topmost", True)
except Exception:
    pass
kind, title, start = sys.argv[1], sys.argv[2], sys.argv[3] or None
p = filedialog.askdirectory(title=title, initialdir=start, mustexist=False) if kind == "folder" \
    else filedialog.askopenfilename(title=title, initialdir=start)
sys.stdout.write(p or "")
"""


def _pick_cmds(kind: str, title: str, start: str) -> list[list[str]]:
    """Ways to show the system's own folder/file chooser, best first."""
    cmds: list[list[str]] = [[sys.executable, "-c", _PICK_TK, kind, title, start]]
    if WINDOWS:
        if kind == "folder":
            # title and start come in through the environment (JOE_PICK_T / JOE_PICK_S), never
            # pasted into the command, so no quote in a folder name can break or change it
            ps = ("Add-Type -AssemblyName System.Windows.Forms; $d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                  "$d.Description = $env:JOE_PICK_T; $d.ShowNewFolderButton = $true; "
                  "$d.SelectedPath = $env:JOE_PICK_S; "
                  "if ($d.ShowDialog() -eq 'OK') { [Console]::Write($d.SelectedPath) }")
        else:
            ps = ("Add-Type -AssemblyName System.Windows.Forms; $d = New-Object System.Windows.Forms.OpenFileDialog; "
                  "$d.Title = $env:JOE_PICK_T; "
                  "if ($d.ShowDialog() -eq 'OK') { [Console]::Write($d.FileName) }")
        cmds.append(["powershell", "-NoProfile", "-STA", "-Command", ps])
    elif MAC:
        what = "folder" if kind == "folder" else "file"
        t = title.replace('"', "")
        cmds.append(["osascript", "-e", f'POSIX path of (choose {what} with prompt "{t}")'])
    else:
        if shutil.which("zenity"):
            cmds.append(["zenity", "--file-selection", f"--title={title}"]
                        + (["--directory"] if kind == "folder" else []) + ([f"--filename={start}/"] if start else []))
        if shutil.which("kdialog"):
            cmds.append(["kdialog", "--getexistingdirectory" if kind == "folder" else "--getopenfilename",
                         start or str(Path.home()), "--title", title])
    return cmds


def pick_path(kind: str = "folder", title: str = "Choose a folder", start: str = "") -> dict:
    """Show the system's folder (or file) chooser on this PC. {"path": ...}; path '' = cancelled;
    {"error": ...} when this system has no chooser Joe can open."""
    kind = "file" if kind == "file" else "folder"
    if start and not Path(start).exists():
        start = str(Path(start).parent) if Path(start).parent.exists() else ""
    env = dict(os.environ, JOE_PICK_T=title, JOE_PICK_S=start)
    for cmd in _pick_cmds(kind, title, start):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                               creationflags=no_window_flags(), env=env)
        except (OSError, subprocess.SubprocessError):
            continue
        if p.returncode == 0 or (p.stdout or "").strip():
            out = (p.stdout or "").strip().splitlines()
            path = out[-1].strip() if out else ""
            if kind == "folder" and MAC:
                path = path.rstrip("/") or path
            return {"path": path}
        err = (p.stderr or "")
        if "No module named" in err or "TclError" in err or "no display" in err.lower():
            continue                     # this way doesn't work here: try the next one
        return {"path": ""}               # the person pressed Cancel
    return {"error": "This computer has no folder chooser Joe can open. Type the path in the box instead."}
