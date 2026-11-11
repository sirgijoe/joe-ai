"""Update check: compares this version with the newest release on GitHub.

Only reads the public releases page (no account, nothing about this PC is sent beyond a
normal web request). Never installs anything by itself: it tells you, and only when you
say yes does it download the installer for your system, check it against the release's
SHA256SUMS.txt, and start it (Windows) / open it (Mac) / swap the AppImage (Linux).
A copy run from source (git) only gets the release page.

Release file names (the build workflow makes exactly these):
  Joe-Setup-<version>-windows-x64.exe       Joe-<version>-macos-arm64.dmg
  Joe-<version>-macos-x64.dmg               Joe-<version>-linux-x86_64.AppImage
  SHA256SUMS.txt
An installed Joe has joeai/_install.json ({"kind": "windows-installer" | "mac-app" |
"linux-appimage"}), written by the build.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import time
import urllib.request
from pathlib import Path

from . import REPO, __version__
from .http import HttpError, request_json

INSTALL_FILE = Path(__file__).parent / "_install.json"
KINDS = ("windows-installer", "mac-app", "linux-appimage")


def install_kind(path: Path = INSTALL_FILE) -> str:
    """How this Joe was installed: one of KINDS, or 'source' (git / a copied folder)."""
    try:
        k = json.loads(path.read_text(encoding="utf-8")).get("kind", "")
    except (OSError, ValueError, AttributeError):
        return "source"
    return k if k in KINDS else "source"


def _arch(machine: str = "") -> str:
    m = (machine or platform.machine()).lower()
    return "arm64" if m in ("arm64", "aarch64") else "x64"


def asset_pattern(kind: str, machine: str = "") -> re.Pattern | None:
    if kind == "windows-installer":
        return re.compile(r"^Joe-Setup-[\w.\-]+-windows-x64\.exe$", re.I)
    if kind == "mac-app":
        return re.compile(rf"^Joe-[\w.\-]+-macos-{_arch(machine)}\.dmg$", re.I)
    if kind == "linux-appimage":
        a = "aarch64" if _arch(machine) == "arm64" else "x86_64"
        return re.compile(rf"^Joe-[\w.\-]+-linux-{a}\.AppImage$", re.I)
    return None


def pick_asset(assets: list, kind: str, machine: str = "") -> dict | None:
    """The release file for this computer: {name, url, size}, or None."""
    pat = asset_pattern(kind, machine)
    if not pat:
        return None
    for a in assets or []:
        if pat.match(str(a.get("name", ""))):
            return {"name": a["name"], "url": a.get("browser_download_url", ""), "size": a.get("size", 0)}
    return None


def sums_url(assets: list) -> str:
    return next((a.get("browser_download_url", "") for a in assets or []
                 if str(a.get("name", "")).upper() == "SHA256SUMS.TXT"), "")


def sig_url(assets: list) -> str:
    return next((a.get("browser_download_url", "") for a in assets or []
                 if str(a.get("name", "")).upper() == "SHA256SUMS.TXT.SIG"), "")


def expected_sha(sums_text: str, name: str) -> str:
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == name:
            return parts[0].lower()
    return ""

_CACHE: dict = {}
CACHE_S = 6 * 3600


def _cert_problem(e) -> bool:
    """Python couldn't check the site's certificate. Its copy of the computer's trusted list can
    be out of date (common on Windows); the site itself is usually fine."""
    return "certificate verify failed" in str(e).lower() or "CERTIFICATE_VERIFY_FAILED" in str(e)


def _curl(url: str, dest: Path | None = None, timeout: float = 60, headers: dict | None = None) -> bytes:
    """Fetch with the computer's own curl (Windows 10+, Mac and Linux have it), which uses the
    system's up-to-date certificate list. Still a fully checked secure connection (https only),
    and the update's checksum and signature are checked afterwards either way."""
    import shutil
    from .system import no_window_flags
    curl = shutil.which("curl")
    if not curl:
        raise OSError("this computer has no curl to fall back on")
    cmd = [curl, "-sS", "-f", "-L", "--proto", "=https", "--proto-redir", "=https", "--max-time", str(int(timeout))]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    if dest is not None:
        cmd += ["-o", str(dest)]
    try:
        r = subprocess.run(cmd + [url], capture_output=True, timeout=timeout + 15, stdin=subprocess.DEVNULL,
                           creationflags=no_window_flags())
    except subprocess.SubprocessError as e:
        raise OSError(str(e)) from e
    if r.returncode != 0:
        raise OSError(r.stderr.decode("utf-8", "replace").strip()[:200] or f"curl exit {r.returncode}")
    return r.stdout


def parse_version(v: str) -> tuple:
    """'v2.1.0' / '2.0.0.dev27' / '2.0.0rc1' -> comparable tuple. Dev/rc sort before the release."""
    v = v.strip().lstrip("vV")
    m = re.match(r"^(\d+(?:\.\d+)*)(?:[.-]?(dev|a|b|rc)(\d*))?", v)
    if not m:
        return (0,)
    nums = [int(x) for x in m.group(1).split(".")]
    while len(nums) < 3:
        nums.append(0)
    pre = {"dev": 0, "a": 1, "b": 2, "rc": 3, None: 9}[m.group(2)]
    return (*nums, pre, int(m.group(3) or 0))


def check(force: bool = False, fetch=request_json) -> dict:
    now = time.time()
    if not force and _CACHE.get("t", 0) > now - CACHE_S:
        return _CACHE["r"]
    url = f"https://api.github.com/repos/{REPO}/releases/latest"
    heads = {"Accept": "application/vnd.github+json", "User-Agent": f"joe-ai/{__version__}"}
    rel, problem = None, None
    try:
        rel = fetch("GET", url, timeout=15, headers=heads)
    except HttpError as e:
        problem = e
        if _cert_problem(e):                      # Python's certificate list is behind: ask with curl
            try:
                rel = json.loads(_curl(url, timeout=20, headers=heads))
            except (OSError, ValueError):
                rel = None
    if not isinstance(rel, dict):
        err = str(problem or "GitHub sent something odd back")
        if "HTTP 404" in err:
            msg = "No releases published yet."
        elif "HTTP 403" in err or "HTTP 429" in err:
            msg = "GitHub is limiting update checks from this network right now. Try again in an hour."
        elif "CERTIFICATE" in err.upper() or "SSL" in err.upper():
            msg = "Couldn't make a secure connection to GitHub (a firewall or antivirus may be checking web traffic)."
        elif "timed out" in err.lower():
            msg = "GitHub took too long to answer. Try again in a minute."
        else:
            msg = "Couldn't reach GitHub."
        r = {"ok": False, "current": __version__, "error": msg, "detail": err[:300]}
        return r  # don't remember failures: the next check tries again
    else:
        latest = str(rel.get("tag_name") or rel.get("name") or "")
        kind = install_kind()
        assets = rel.get("assets") or []
        r = {"ok": True, "current": __version__, "latest": latest.lstrip("vV"),
             "newer": parse_version(latest) > parse_version(__version__),
             "url": rel.get("html_url") or f"https://github.com/{REPO}/releases/latest",
             "notes": str(rel.get("body") or "")[:1500], "kind": kind,
             "asset": pick_asset(assets, kind), "sums": sums_url(assets), "sig": sig_url(assets)}
    _CACHE.update(t=now, r=r)
    return r


def updates_dir() -> Path:
    from .system import data_dir
    d = data_dir() / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def download(info: dict, log, progress=None, opener=urllib.request.urlopen) -> Path | None:
    """Download the installer the last check() found, and check its SHA-256 against the
    release's SHA256SUMS.txt. Returns the file, or None (and says why in the log)."""
    a = info.get("asset")
    if not a or not a.get("url"):
        log("There's no installer for this computer in that release; use the release page.")
        return None
    dest = updates_dir() / a["name"]
    part = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    try:
        with opener(a["url"], timeout=60) as r, open(part, "wb") as f:
            total, got = int(r.headers.get("Content-Length") or a.get("size") or 0), 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if total and progress:
                    progress(100 * got / total)
    except OSError as e:
        part.unlink(missing_ok=True)
        if not _cert_problem(e):
            log(f"Couldn't download the update: {e}")
            return None
        # Python's certificate list is behind (common on Windows): the computer's own curl has the
        # current one. The checksum and signature below are checked exactly the same.
        log("  Python couldn't check GitHub's certificate; downloading with this computer's own curl instead.")
        try:
            _curl(a["url"], dest=part, timeout=1800)
            h = hashlib.sha256()
            with open(part, "rb") as f:
                while chunk := f.read(1 << 20):
                    h.update(chunk)
        except OSError as e2:
            log(f"Couldn't download the update: {e2}")
            part.unlink(missing_ok=True)
            return None

    def small(url: str) -> bytes:
        try:
            with opener(url, timeout=30) as r:
                return r.read()
        except OSError as e:
            if _cert_problem(e):
                return _curl(url, timeout=30)
            raise

    want, sums = "", b""
    if info.get("sums"):
        try:
            sums = small(info["sums"])
            want = expected_sha(sums.decode("utf-8", "replace"), a["name"])
        except OSError:
            want = ""
    from . import SIGN_PUBLIC_KEY
    if want and SIGN_PUBLIC_KEY:                 # signed releases: the list must be the maker's
        from . import sign
        sig = ""
        if info.get("sig"):
            try:
                sig = small(info["sig"]).decode("ascii", "replace")
            except OSError:
                sig = ""
        if not sig or not sign.check(sums, sig, SIGN_PUBLIC_KEY):
            log("This release's signature is missing or doesn't match Joe's maker, so Joe won't install it. "
                "Use the release page, or ask on GitHub.")
            part.unlink(missing_ok=True)
            return None
    if not want:
        log("The release has no checksum for this file, so Joe won't install it. Use the release page.")
        part.unlink(missing_ok=True)
        return None
    if h.hexdigest() != want:
        log("The download doesn't match its checksum (damaged or tampered), so it was deleted.")
        part.unlink(missing_ok=True)
        return None
    part.replace(dest)
    log(f"Downloaded and checked {a['name']}.")
    return dest


def launch(path: Path, kind: str, log) -> bool:
    """Start the new version. Windows: the installer runs quietly and opens Joe again when
    it's done (Joe must quit right after). Mac: the disk image opens; drag Joe to
    Applications. Linux: the AppImage is swapped in place; Joe restarts."""
    from .system import no_window_flags, open_path, popen_detached
    try:
        if kind == "windows-installer":
            subprocess.Popen([str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NOCANCEL"],
                             creationflags=no_window_flags(), close_fds=True)
            log("The installer is running; Joe closes now and opens again when it's done.")
            return True
        if kind == "mac-app":
            open_path(path)
            log("The new Joe opened in Finder: drag it onto Applications (replace), then open it.")
            return True
        if kind == "linux-appimage":
            target = Path(os.environ.get("APPIMAGE", ""))
            if not target.name.endswith(".AppImage") or not target.exists():
                log(f"Couldn't find the running AppImage; the new one is at {path}.")
                return False
            path.chmod(0o755)
            try:
                os.replace(path, target)
            except OSError:                   # download folder on another drive
                import shutil
                tmp = target.with_name(target.name + ".new")
                shutil.copy2(path, tmp)
                os.replace(tmp, target)
                path.unlink(missing_ok=True)
            popen_detached([str(target)])
            log("Updated. Joe restarts now.")
            return True
    except OSError as e:
        log(f"Couldn't start the update: {e}")
        return False
    log("This copy of Joe wasn't installed with an installer; get the new version from the release page.")
    return False
