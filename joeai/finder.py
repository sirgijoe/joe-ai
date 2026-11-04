"""Find the programs Joe works with, wherever this PC keeps them.

Nothing is hard-coded to one machine: every path is built from the usual install spots
(per-user and all-users program folders, winget, Scoop, Chocolatey, Homebrew), the Windows
"installed apps" list, and the program's own config files. A path typed in Setup always wins;
if that path no longer exists, Joe falls back to searching again.

Read-only: this module never starts, installs or changes anything.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"


def _env(name: str) -> Path | None:
    v = os.environ.get(name, "")
    return Path(v) if v else None


def _home() -> Path:
    return Path.home()


def _exists(p: Path | None) -> bool:
    try:
        return bool(p) and p.exists()
    except OSError:
        return False


def _is_dir(p: Path | None) -> bool:
    try:
        return bool(p) and p.is_dir()
    except OSError:
        return False


def _children(p: Path) -> list[Path]:
    try:
        return [c for c in p.iterdir()]
    except OSError:
        return []


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _drives() -> list[Path]:
    """Fixed drive roots on Windows (C:\\, D:\\ ...); / elsewhere is too big to search."""
    if not WINDOWS:
        return []
    out = []
    for letter in "CDEFGH":
        p = Path(f"{letter}:\\")
        if _is_dir(p):
            out.append(p)
    return out


def _installed_apps(pattern: str) -> list[Path]:
    """Install folders from Windows' installed-apps list whose name matches pattern."""
    if not WINDOWS:
        return []
    try:
        import winreg
    except ImportError:
        return []
    rx = re.compile(pattern, re.I)
    found: list[Path] = []
    roots = [(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, path in roots:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with key:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(key, sub) as k:
                        name = str(winreg.QueryValueEx(k, "DisplayName")[0])
                        if not rx.search(name):
                            continue
                        for val in ("InstallLocation", "DisplayIcon"):
                            try:
                                raw = str(winreg.QueryValueEx(k, val)[0]).strip().strip('"')
                            except OSError:
                                continue
                            raw = raw.split(",")[0].strip().strip('"')   # "x.exe,0" icons
                            if raw:
                                p = Path(raw)
                                found.append(p.parent if p.suffix.lower() == ".exe" else p)
                except OSError:
                    continue
    return found


# --------------------------------------------------------------------------- simple tools
def _tool_dirs(tool: str, program_dirs: tuple[str, ...]) -> list[Path]:
    """Every usual folder a command-line tool lands in, for this OS."""
    dirs: list[Path] = []
    if WINDOWS:
        la, pf, pf86 = _env("LOCALAPPDATA"), _env("ProgramFiles"), _env("ProgramFiles(x86)")
        for base in (la / "Programs" if la else None, la, pf, pf86):
            if not base:
                continue
            for d in program_dirs:
                dirs += [base / d, base / d / "bin"]
        if la:
            dirs.append(la / "Microsoft" / "WinGet" / "Links")
            pk = la / "Microsoft" / "WinGet" / "Packages"
            for p in _children(pk):                         # e.g. Gyan.FFmpeg_xxx\ffmpeg-7.1-full\bin
                if tool.lower() in p.name.lower():
                    dirs += [p, p / "bin"] + [c / "bin" for c in _children(p)]
        dirs += [_home() / "scoop" / "shims", Path(r"C:\ProgramData\chocolatey\bin")]
        for drive in _drives():
            for d in program_dirs:
                dirs += [drive / d / "bin", drive / d]
    else:
        dirs += [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/usr/bin"),
                 _home() / ".local" / "bin"]
    return dirs


def find_tool(tool: str, configured: str = "", program_dirs: tuple[str, ...] = ()) -> str | None:
    """configured path -> PATH -> the usual install folders (newest copy wins)."""
    if configured and _exists(Path(configured)):
        return configured
    found = shutil.which(tool)
    if found:
        return found
    exe = tool + (".exe" if WINDOWS else "")
    hits = [d / exe for d in _tool_dirs(tool, program_dirs or (tool,)) if _exists(d / exe)]
    return str(max(hits, key=_mtime)) if hits else None


def ollama_exe(configured: str = "") -> str | None:
    if MAC:
        app = Path("/Applications/Ollama.app/Contents/Resources/ollama")
        if not configured and not shutil.which("ollama") and _exists(app):
            return str(app)
    hit = find_tool("ollama", configured, ("Ollama",))
    if hit or not WINDOWS:
        return hit
    for d in _installed_apps(r"^ollama"):
        if _exists(d / "ollama.exe"):
            return str(d / "ollama.exe")
    return None


def ffmpeg_exe(configured: str = "") -> str | None:
    return find_tool("ffmpeg", configured, ("ffmpeg", "FFmpeg"))


def pandoc_exe(configured: str = "") -> str | None:
    return find_tool("pandoc", configured, ("Pandoc",))


# --------------------------------------------------------------------------- ComfyUI
@dataclass
class ComfyInstall:
    kind: str                       # desktop | portable | manual | custom
    command: list[str] | str        # what to run to start it
    cwd: str
    base: str = ""                  # folder holding models\ and output\
    port: int = 8000
    notes: list[str] = field(default_factory=list)
    models_override: str = ""       # Setup's "Models folder", when set and present

    @property
    def models_dir(self) -> Path | None:
        if self.models_override:
            return Path(self.models_override)
        p = Path(self.base) / "models" if self.base else None
        return p if _is_dir(p) else None

    @property
    def output_dir(self) -> Path | None:
        p = Path(self.base) / "output" if self.base else None
        return p if _is_dir(p) else None

    @property
    def label(self) -> str:
        return {"desktop": "ComfyUI Desktop", "portable": "ComfyUI (portable)",
                "manual": "ComfyUI (own install)", "custom": "ComfyUI (your start command)"}[self.kind]

    def as_dict(self) -> dict:
        cmd = self.command if isinstance(self.command, str) else " ".join(
            f'"{c}"' if " " in c else c for c in self.command)
        return {"kind": self.kind, "label": self.label, "command": cmd, "cwd": self.cwd,
                "base": self.base, "models_dir": str(self.models_dir or ""), "port": self.port}


def _desktop_app_dirs() -> list[Path]:
    dirs: list[Path] = []
    if WINDOWS:
        la, pf = _env("LOCALAPPDATA"), _env("ProgramFiles")
        for base in (la / "Programs" if la else None, pf):
            if base:
                dirs += [c for c in _children(base) if "comfy" in c.name.lower()]
        dirs += _installed_apps(r"comfy")
    elif MAC:
        dirs += [p for p in (Path("/Applications"), _home() / "Applications")
                 for p in _children(p) if "comfy" in p.name.lower() and p.suffix == ".app"]
    seen, out = set(), []
    for d in dirs:
        k = str(d).lower()
        if k not in seen and _is_dir(d):
            seen.add(k)
            out.append(d)
    return out


def desktop_exe() -> Path | None:
    """The ComfyUI Desktop program. The app was renamed (ComfyUI.exe -> Comfy Desktop.exe) and an
    update can leave the old file behind, so take the NEWEST Comfy program, never an uninstaller."""
    cands: list[Path] = []
    for d in _desktop_app_dirs():
        if MAC and d.suffix == ".app":
            cands += [c for c in _children(d / "Contents" / "MacOS")]
            continue
        for f in _children(d):
            n = f.name.lower()
            if f.suffix.lower() == ".exe" and "comfy" in n and not n.startswith("uninstall"):
                cands.append(f)
    return max(cands, key=_mtime) if cands else None


def _desktop_config_dirs() -> list[Path]:
    if WINDOWS:
        ad = _env("APPDATA")
        return [c for c in _children(ad) if "comfy" in c.name.lower()] if ad else []
    if MAC:
        sup = _home() / "Library" / "Application Support"
        return [c for c in _children(sup) if "comfy" in c.name.lower()]
    cfg = _home() / ".config"
    return [c for c in _children(cfg) if "comfy" in c.name.lower()]


def _yaml_base_paths(text: str) -> list[str]:
    """base_path lines from ComfyUI's extra_models_config.yaml (no YAML library needed)."""
    out = []
    for m in re.finditer(r"(?m)^\s*base_path\s*:\s*(.+?)\s*$", text):
        v = m.group(1).strip().strip("'\"")
        if v:
            out.append(v)
    return out


def desktop_base_path() -> Path | None:
    """ComfyUI Desktop's data folder (models\\, output\\, user\\), from its own config files."""
    cands: list[Path] = []
    for d in _desktop_config_dirs():
        try:
            base = json.loads((d / "config.json").read_text(encoding="utf-8")).get("basePath")
            if base:
                cands.append(Path(base))
        except (OSError, ValueError, AttributeError):
            pass
        try:
            cands += [Path(b) for b in _yaml_base_paths(
                (d / "extra_models_config.yaml").read_text(encoding="utf-8"))]
        except OSError:
            pass
    cands.append(_home() / "Documents" / "ComfyUI")       # the app's default spot
    for c in cands:
        if _is_dir(c / "models"):
            return c
    return None


def _venv_python(folder: Path) -> Path | None:
    for v in ("venv", ".venv", "env"):
        for rel in (("Scripts", "python.exe"), ("bin", "python")):
            p = folder.joinpath(v, *rel)
            if _exists(p):
                return p
    return None


def _inspect(folder: Path) -> ComfyInstall | None:
    """Is this folder a portable or hand-made ComfyUI install?"""
    for bat in ("run_nvidia_gpu.bat", "run_nvidia_gpu_fast_fp16_accumulation.bat", "run_amd_gpu.bat",
                "run_cpu.bat"):
        if _exists(folder / bat):
            base = folder / "ComfyUI" if _is_dir(folder / "ComfyUI") else folder
            return ComfyInstall("portable", f'"{folder / bat}"', str(folder), str(base), 8188)
    if _exists(folder / "main.py") and _is_dir(folder / "comfy"):
        py = _venv_python(folder) or _venv_python(folder.parent)
        if py:
            return ComfyInstall("manual", [str(py), "main.py"], str(folder), str(folder), 8188)
    return None


def _search_roots() -> list[Path]:
    h = _home()
    roots = [h, h / "Desktop", h / "Documents", h / "Downloads", h / "AI", h / "source",
             *_drives()]
    for d in (h / "Desktop", h / "Documents", h / "Downloads", h / "AI"):
        roots += [c for c in _children(d) if _is_dir(c) and re.search(r"\bai\b|stable|diffusion|tools",
                                                                      c.name, re.I)]
    if WINDOWS:
        ad = _env("APPDATA")
        if ad:
            roots.append(ad / "StabilityMatrix" / "Packages")
        roots += [d / "StabilityMatrix" / "Data" / "Packages" for d in _drives()]
        pin = h / "pinokio" / "api"
        roots.append(pin)
    return roots


def portable_installs() -> list[ComfyInstall]:
    """Portable / own-install ComfyUI folders in the usual places (two levels deep, only
    folders with 'comfy' in the name, so the search stays quick)."""
    found: list[ComfyInstall] = []
    seen: set[str] = set()
    for root in _search_roots():
        for c in _children(root):
            if not ("comfy" in c.name.lower() and _is_dir(c)):
                continue
            for cand in (c, *[g for g in _children(c) if _is_dir(g) and "comfy" in g.name.lower()]):
                key = str(cand.resolve()).lower() if _exists(cand) else str(cand).lower()
                if key in seen:
                    continue
                seen.add(key)
                hit = _inspect(cand)
                if hit:
                    found.append(hit)
    found.sort(key=lambda i: (i.kind != "portable", -_mtime(Path(i.cwd))))
    return found


def find_comfy(start_command: str = "", start_dir: str = "", models_dir: str = "") -> ComfyInstall | None:
    """Best ComfyUI on this PC. Setup's start command wins; then ComfyUI Desktop; then a
    portable or own install. models_dir (from Setup) overrides where the models are."""
    inst: ComfyInstall | None = None
    first = re.match(r'\s*"([^"]+)"|\s*(\S+)', start_command or "")
    first_path = (first.group(1) or first.group(2)) if first else ""
    if first_path and re.search(r"[\\/]", first_path) and not _exists(Path(first_path)):
        start_command = ""          # Setup points at a file that's gone (moved/updated): search again
    if start_command.strip():
        cmd = start_command.strip()
        cwd = start_dir or str(Path(cmd.strip('"')).parent)
        inst = ComfyInstall("custom", cmd, cwd, "", 8000)
        guess = _inspect(Path(cwd))
        if guess:
            inst.base, inst.port = guess.base, guess.port
    else:
        exe = desktop_exe()
        base = desktop_base_path()
        if exe:
            inst = ComfyInstall("desktop", [str(exe)], str(exe.parent), str(base or ""), 8000)
        else:
            ports = portable_installs()
            if ports:
                inst = ports[0]
            elif base:          # data folder but no program: models still usable for scanning
                inst = ComfyInstall("desktop", [], "", str(base), 8000,
                                    ["ComfyUI Desktop's data folder was found, but not the program."])
    if models_dir and _is_dir(Path(models_dir)):
        inst = inst or ComfyInstall("custom", [], "", "", 8000)
        inst.models_override = models_dir
        if not inst.base:
            inst.base = str(Path(models_dir).parent)
    return inst


def comfy_models_dir(inst: ComfyInstall | None) -> Path | None:
    return inst.models_dir if inst else None


def summary(settings) -> dict:
    """What Joe found, for System check and the setup helper."""
    c = settings.comfy
    inst = find_comfy(c.start_command, c.start_dir, c.models_dir)
    return {
        "ollama": ollama_exe(settings.ollama.exe) or "",
        "comfyui": inst.as_dict() if inst else None,
        "comfy_models": str(comfy_models_dir(inst) or ""),
        "ffmpeg": ffmpeg_exe(c.ffmpeg) or "",
        "pandoc": pandoc_exe(getattr(settings, "pandoc", "")) or "",
    }
