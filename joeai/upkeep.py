"""Keeping Joe's helpers ready: which models to suggest, whether Ollama / ComfyUI / the
installed models have newer versions, and installing Ollama or ComfyUI where no package
manager can (Mac without Homebrew, Linux).

Nothing here installs or downloads on its own. Checks only read public pages (GitHub's
release list, the Ollama model registry, this project's model list) at most once a week;
fixes run only after the person says yes in System check.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Callable

from . import REPO
from .http import HttpError, request_json

Log = Callable[[str], None]

PICKS_FILE = Path(__file__).parent / "model_picks.json"
PICKS_URL = f"https://raw.githubusercontent.com/{REPO}/main/joeai/model_picks.json"
WEEK_S = 7 * 24 * 3600
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*(:[a-z0-9._-]+)?$")

OLLAMA_REPO = "ollama/ollama"
COMFY_REPO = "comfyanonymous/ComfyUI"
OLLAMA_LINUX_CMD = ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"]
TORCH_INDEX = {"nvidia": "https://download.pytorch.org/whl/cu128",
               "amd": "https://download.pytorch.org/whl/rocm6.4",
               "cpu": "https://download.pytorch.org/whl/cpu"}


def _cache_dir() -> Path:
    from .system import config_dir
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- model picks
def valid_picks(d) -> bool:
    """A picks file Joe can trust: only plain model names and sensible sizes."""
    try:
        rows = d["writing"]
        if not rows or not isinstance(rows, list):
            return False
        for r in rows:
            if not _NAME.match(str(r["name"])) or not 0 <= float(r["min_vram"]) <= 512 \
                    or not 0 < float(r["size_gb"]) <= 400:
                return False
        t = d.get("talk")
        return t is None or (bool(_NAME.match(str(t["name"]))) and 0 < float(t["size_gb"]) <= 400)
    except (KeyError, TypeError, ValueError):
        return False


def _builtin() -> dict:
    return json.loads(PICKS_FILE.read_text(encoding="utf-8"))


def online() -> bool:
    """Joe may read public pages for picks and update checks (Setup > Privacy, JOE_OFFLINE=1)."""
    import os
    if os.environ.get("JOE_OFFLINE"):
        return False
    try:
        from .config import Settings
        return bool(Settings.load().ui.check_updates)
    except Exception:
        return True


def picks(fetch=request_json, now: float | None = None, net: bool | None = None) -> dict:
    """The model list: GitHub's copy (checked weekly, cached), else the one built into Joe."""
    now = time.time() if now is None else now
    net = online() if net is None else net
    cache = _cache_dir() / "model_picks.json"
    try:
        c = json.loads(cache.read_text(encoding="utf-8"))
        if valid_picks(c.get("picks")) and now - float(c.get("t", 0)) < WEEK_S:
            return c["picks"]
    except (OSError, ValueError, AttributeError):
        c = None
    try:
        if not net:
            raise HttpError("offline")
        d = fetch("GET", PICKS_URL, timeout=6)
        if valid_picks(d):
            cache.write_text(json.dumps({"t": now, "picks": d}), encoding="utf-8")
            return d
    except (HttpError, ValueError, OSError):
        pass
    if c and valid_picks(c.get("picks")):          # stale but still better than nothing
        return c["picks"]
    return _builtin()


def writing_picks(fetch=request_json) -> list[tuple[float, str, float]]:
    rows = sorted(picks(fetch)["writing"], key=lambda r: -float(r["min_vram"]))
    return [(float(r["min_vram"]), str(r["name"]), float(r["size_gb"])) for r in rows]


def talk_pick(fetch=request_json) -> dict:
    return picks(fetch).get("talk") or _builtin()["talk"]


# --------------------------------------------------------------------------- versions
def parse_version(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:4])


def latest_release(repo: str, fetch=request_json) -> dict:
    return fetch("GET", f"https://api.github.com/repos/{repo}/releases/latest", timeout=8,
                 headers={"User-Agent": "joe-ai", "Accept": "application/vnd.github+json"})


def ollama_version(base: str, fetch=request_json) -> str:
    try:
        return str(fetch("GET", f"{base}/api/version", timeout=4).get("version", ""))
    except HttpError:
        return ""


def manifest_digest(name: str, opener=None) -> str:
    """sha256 of the model's manifest in the Ollama registry (what /api/tags calls digest)."""
    import urllib.request
    model, _, tag = name.partition(":")
    if "/" not in model:
        model = "library/" + model
    req = urllib.request.Request(
        f"https://registry.ollama.ai/v2/{model}/manifests/{tag or 'latest'}",
        headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json",
                 "User-Agent": "joe-ai"})
    with (opener or urllib.request.urlopen)(req, timeout=8) as r:
        return hashlib.sha256(r.read()).hexdigest()


def own_comfy_dir() -> Path:
    from .addons import addons_dir
    return addons_dir() / "comfyui" / "ComfyUI"


def own_comfy_version() -> str:
    try:
        return json.loads((own_comfy_dir() / "joe_install.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return ""


_UPD: dict = {}


def check_updates(ollama_base: str, local_models: list[dict], force: bool = False,
                  fetch=request_json, digest=manifest_digest) -> list[dict]:
    """Doctor issues for things that have something newer. Cached for a week."""
    key = _cache_dir() / "updates.json"
    now = time.time()
    if not force:
        if _UPD.get("t", 0) > now - WEEK_S:
            return _UPD["r"]
        try:
            c = json.loads(key.read_text(encoding="utf-8"))
            if float(c.get("t", 0)) > now - WEEK_S:
                _UPD.update(c)
                return c["r"]
        except (OSError, ValueError):
            pass
    out: list[dict] = []
    have = ollama_version(ollama_base, fetch)
    if have:
        try:
            tag = str(latest_release(OLLAMA_REPO, fetch).get("tag_name", ""))
            if parse_version(tag) > parse_version(have):
                out.append({"id": "update-ollama", "group": "updates", "optional": True,
                            "text": f"Ollama {tag.lstrip('v')} is out (you have {have}). Newer versions "
                                    "run new models and fix problems.",
                            "action": "update", "tool": "ollama"})
        except HttpError:
            pass
    mine = own_comfy_version()
    if mine:
        try:
            tag = str(latest_release(COMFY_REPO, fetch).get("tag_name", ""))
            if parse_version(tag) > parse_version(mine):
                out.append({"id": "update-comfyui", "group": "updates", "optional": True,
                            "text": f"ComfyUI {tag.lstrip('v')} is out (Joe set up {mine}).",
                            "action": "update", "tool": "comfyui"})
        except HttpError:
            pass
    for m in local_models[:12]:
        d = str(m.get("digest", ""))
        if not d:
            continue
        try:
            if digest(m["name"]) != d:
                out.append({"id": "refresh-" + m["name"], "group": "updates", "optional": True,
                            "text": f"A newer copy of the model {m['name']} is out. Getting it only "
                                    "downloads the parts that changed.",
                            "action": "pull", "model": m["name"], "keep": True})
        except Exception:      # registry down, private model, odd name: just skip it
            continue
    c = {"t": now, "r": out}
    _UPD.update(c)
    try:
        key.write_text(json.dumps(c), encoding="utf-8")
    except OSError:
        pass
    return out


def known_updates() -> list[dict]:
    """What the last check found (no network)."""
    if "r" in _UPD:
        return _UPD["r"]
    try:
        c = json.loads((_cache_dir() / "updates.json").read_text(encoding="utf-8"))
        _UPD.update(c)
        return c["r"]
    except (OSError, ValueError, KeyError):
        return []


def stale() -> bool:
    if _UPD.get("t", 0) > time.time() - WEEK_S:
        return False
    try:
        c = json.loads((_cache_dir() / "updates.json").read_text(encoding="utf-8"))
        return float(c.get("t", 0)) <= time.time() - WEEK_S
    except (OSError, ValueError):
        return True


_RUNNING = {"on": False}


def check_in_background(ollama_base: str, local_models: list[dict], force: bool = False) -> bool:
    """Start a check unless one ran this week (or one is running). True = started."""
    import threading
    if _RUNNING["on"] or not online() or (not force and not stale()):
        return False
    _RUNNING["on"] = True

    def go():
        try:
            check_updates(ollama_base, local_models, force=True)
        finally:
            _RUNNING["on"] = False
    threading.Thread(target=go, daemon=True).start()
    return True


def checking() -> bool:
    return _RUNNING["on"]


def forget_updates() -> None:
    _UPD.clear()
    try:
        (_cache_dir() / "updates.json").unlink()
    except OSError:
        pass


# --------------------------------------------------------------------------- installs Joe does himself
def _pick_asset(rel: dict, names: tuple[str, ...]) -> dict | None:
    assets = {a.get("name"): a for a in rel.get("assets") or []}
    return next((assets[n] for n in names if n in assets), None)


def install_ollama_mac(log: Log, fetch=request_json, download=None) -> bool:
    """Ollama's official Mac app from its GitHub release, into ~/Applications."""
    from .doctor import _download
    rel = latest_release(OLLAMA_REPO, fetch)
    a = _pick_asset(rel, ("Ollama-darwin.zip", "Ollama.zip"))
    if not a:
        dmg = _pick_asset(rel, ("Ollama.dmg",))
        if dmg:
            log("Opening Ollama's installer: drag Ollama into Applications, open it once, "
                "then press CHECK AGAIN.")
            import webbrowser
            webbrowser.open(dmg["browser_download_url"])
        return False
    tmp = _cache_dir() / "Ollama-darwin.zip"
    log(f"Downloading Ollama {rel.get('tag_name', '')} for Mac...")
    if not (download or _download)(a["browser_download_url"], tmp, log):
        return False
    apps = Path.home() / "Applications"
    apps.mkdir(exist_ok=True)
    import subprocess
    p = subprocess.run(["ditto", "-x", "-k", str(tmp), str(apps)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    tmp.unlink(missing_ok=True)
    if p.returncode != 0:
        log("Couldn't unpack Ollama: " + (p.stderr or "").strip()[:200])
        return False
    subprocess.Popen(["open", str(apps / "Ollama.app")])
    log("Ollama is in your Applications folder and starting. If macOS asks, click Open.")
    return True


def torch_index(vendor: str, mac: bool) -> str | None:
    """Where PyTorch for this card comes from (None = the normal package index, for Macs)."""
    if mac:
        return None
    return TORCH_INDEX.get(vendor if vendor in ("nvidia", "amd") else "cpu")


def _unpack_source(zpath: Path, dest: Path) -> None:
    """GitHub's source zip has one top folder (owner-repo-sha); its contents go into dest."""
    tmp = dest.parent / (dest.name + ".new")
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zpath) as z:
        for n in z.namelist():
            if n.startswith("/") or ".." in Path(n).parts:
                raise ValueError("unsafe path in download: " + n)
        z.extractall(tmp)
    tops = [p for p in tmp.iterdir() if p.is_dir()]
    src = tops[0] if len(tops) == 1 else tmp
    venv = dest / ".venv"
    keep_models = dest / "models"
    if dest.exists():                         # update: keep the Python and the models
        for p in src.iterdir():
            target = dest / p.name
            if target in (venv, keep_models, dest / "output", dest / "input", dest / "user",
                          dest / "custom_nodes"):           # never wipe the add-on nodes someone installed
                continue
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            shutil.move(str(p), str(target))
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
    shutil.rmtree(tmp, ignore_errors=True)


def install_comfy_own(log: Log, progress=None, fetch=request_json) -> bool:
    """ComfyUI from its official GitHub source, in Joe's own private Python (via uv).
    Used where ComfyUI Desktop can't be installed for you (Mac without it, Linux)."""
    from . import addons, hardware
    from .doctor import _download
    from .system import MAC, WINDOWS
    uv = addons.get_uv(log)
    if not uv:
        return False
    rel = latest_release(COMFY_REPO, fetch)
    tag = str(rel.get("tag_name", ""))
    url = rel.get("zipball_url")
    if not url:
        log("Couldn't find ComfyUI's newest release on GitHub.")
        return False
    dest = own_comfy_dir()
    z = dest.parent / "comfyui-src.zip"
    log(f"Downloading ComfyUI {tag} (the program, about 10 MB)...")
    if not _download(url, z, log):
        return False
    try:
        _unpack_source(z, dest)
    finally:
        z.unlink(missing_ok=True)
    if progress:
        progress(10)
    py = dest / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
    if not py.exists() and not addons._run([uv, "venv", "--python", "3.12", str(dest / ".venv")], log):
        return False
    vendor = hardware.vendor()
    idx = torch_index(vendor, MAC)
    where = ("your Mac" if MAC else {"nvidia": "your NVIDIA card", "amd": "your AMD card"}.get(
        vendor, "the processor (no usable graphics card, so pictures will be very slow)"))
    log(f"Getting PyTorch for {where}.")
    log("This is the big part (2-4 GB) and can take a while.")
    cmd = [uv, "pip", "install", "--python", str(py), "torch", "torchvision", "torchaudio"]
    if idx:
        cmd += ["--index-url", idx]
    if not addons._run(cmd, log, timeout=7200):
        return False
    if progress:
        progress(80)
    if not addons._run([uv, "pip", "install", "--python", str(py), "-r",
                        str(dest / "requirements.txt")], log, timeout=3600):
        return False
    (dest / "joe_install.json").write_text(json.dumps({"version": tag.lstrip("v")}), encoding="utf-8")
    if progress:
        progress(100)
    log(f"ComfyUI {tag} is set up in Joe's own folder. Joe starts it when he needs it.")
    return True


def update_ollama(log: Log) -> bool:
    """Same route as installing: winget/Homebrew upgrade, Mac app swap, or the Linux one-liner."""
    from . import system
    from .doctor import run_install
    pm = system.package_manager()
    if pm == "winget":
        return _run_upgrade([shutil.which("winget") or "winget", "upgrade", "-e", "--id", "Ollama.Ollama",
                             "--accept-package-agreements", "--accept-source-agreements",
                             "--disable-interactivity"], log)
    if pm == "brew":
        return _run_upgrade([system._brew(), "upgrade", "--cask", "ollama"], log)
    return run_install("ollama", "Ollama", "https://ollama.com/download", log)


def _run_upgrade(cmd: list[str], log: Log) -> bool:
    from .addons import _run
    log("Updating: " + " ".join(cmd[1:3]) + " ...")
    return _run(cmd, log, timeout=1800)
