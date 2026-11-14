"""Key vault (2.3): Joe's keys and passwords live in the computer's own protected store, not in the
plain settings file.

Which keys: the Ollama web-search key, the connector password (mcp_key), the key some local AI servers
ask for (engine_key) and the phone-ping topic (anyone who knows it can read the pings).

Where, standard library only:
  Windows  DPAPI (CryptProtectData through ctypes): the keys are encrypted with your Windows sign-in
           and kept in keys.dpapi.json beside the settings file. Another account, or the file copied
           to another computer, can't read them.
  Mac      the login Keychain, through the `security` command that comes with every Mac.
  Linux    the Secret Service keyring (GNOME Keyring, KWallet) through `secret-tool`, when it's
           installed and a keyring is running. Without one, the keys stay in the settings file, which
           is made readable by your account only (owner-only permissions), and Setup says so. A night
           shift started by cron has no desktop session of its own: Joe points `secret-tool` at your
           signed-in session (/run/user/<id>/bus) so the keys still read. If nobody is signed in the
           keyring is locked, the keys read as blank that run, and Setup says so.
  Portable Joe keeps them in its own settings file on the drive: a computer's vault stays with that
           computer, and a portable Joe has to work on any of them.

Safety rules: a key is only taken out of the settings file after it was stored AND read back the same
(so one is never lost); a key Joe couldn't read from the vault this time is never deleted from it; the
settings file names where the keys are ("vault": {...}) but never holds them once they've moved.
JOE_VAULT=file forces the settings file (the tests use it, so they never touch a real keychain).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SECRETS = (("web", "ollama_key"), ("mcp_key",), ("ollama", "engine_key"), ("comfort", "ntfy_topic"))
SERVICE = "joe-ai"
LABELS = {"dpapi": "Windows' protected storage (DPAPI, locked to your Windows sign-in)",
          "keychain": "the Mac Keychain",
          "secret-tool": "the system keyring (Secret Service)",
          "file": "Joe's settings file, readable by your account only"}


def dotted(p: tuple) -> str:
    return ".".join(p)


def _get(d: dict, p: tuple):
    for k in p:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _set(d: dict, p: tuple, v) -> None:
    for k in p[:-1]:
        d = d.setdefault(k, {})
    d[p[-1]] = v


def account(p: tuple, settings_path: Path) -> str:
    """Two Joes on one computer (an installed one and a test copy) keep separate keys."""
    tag = hashlib.sha1(str(Path(settings_path).resolve()).lower().encode()).hexdigest()[:8]
    return f"{dotted(p)}@{tag}"


# ----------------------------------------------------------------------------- backends
class Backend:
    name = "file"

    def put(self, acct: str, value: str) -> bool:
        return False

    def get(self, acct: str) -> str | None:
        return None

    def delete(self, acct: str) -> None:
        pass


class _DPAPI(Backend):
    """Windows: CryptProtectData / CryptUnprotectData (current user), blobs in keys.dpapi.json."""
    name = "dpapi"
    ENTROPY = b"joe-ai key vault"

    def __init__(self, settings_path: Path):
        self.file = Path(settings_path).with_name("keys.dpapi.json")

    @staticmethod
    def _crypt(data: bytes, protect: bool, entropy: bytes) -> bytes | None:
        import ctypes
        from ctypes import wintypes

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        def blob(b: bytes):
            buf = ctypes.create_string_buffer(b, len(b))
            return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

        crypt32 = ctypes.windll.crypt32                       # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32                     # type: ignore[attr-defined]
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(BLOB), ctypes.c_void_p, ctypes.POINTER(BLOB), ctypes.c_void_p,
                       ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(BLOB)]
        fn.restype = wintypes.BOOL
        bin_, keep1 = blob(data)
        ent, keep2 = blob(entropy)
        out = BLOB()
        desc = ctypes.c_wchar_p("Joe key") if protect else None
        if not fn(ctypes.byref(bin_), desc, ctypes.byref(ent), None, None, 0x1, ctypes.byref(out)):  # UI_FORBIDDEN
            return None
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))

    def _load(self) -> dict:
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, d: dict) -> None:
        from .fsutil import atomic_write_text
        atomic_write_text(self.file, json.dumps(d, indent=1))

    def put(self, acct, value):
        try:
            enc = self._crypt(value.encode("utf-8"), True, self.ENTROPY)
        except (OSError, AttributeError, ValueError):
            return False
        if not enc:
            return False
        d = self._load()
        d[acct] = base64.b64encode(enc).decode("ascii")
        try:
            self._save(d)
        except OSError:
            return False
        return True

    def get(self, acct):
        raw = self._load().get(acct)
        if not raw:
            return None
        try:
            dec = self._crypt(base64.b64decode(raw), False, self.ENTROPY)
        except (OSError, AttributeError, ValueError):
            return None
        return dec.decode("utf-8") if dec is not None else None

    def delete(self, acct):
        d = self._load()
        if acct in d:
            del d[acct]
            try:
                self._save(d)
            except OSError:
                pass


def _run(cmd: list, stdin: str | None = None, timeout: int = 20, env: dict | None = None) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None


def session_env(environ: dict | None = None, uid: int | None = None, runtime_root: str = "/run/user") -> dict | None:
    """Linux night shift: a job started by cron or a timer has no desktop session in its environment, so
    `secret-tool` can't find the keyring even though you're signed in and it's unlocked (the keys then read
    as blank for that run). If the environment has no session bus, point at the signed-in user's own bus
    (/run/user/<uid>/bus). Returns the environment to run `secret-tool` with, or None to change nothing
    (a session is already there, there is no bus to point at, or this isn't Linux)."""
    env = dict(os.environ if environ is None else environ)
    if env.get("DBUS_SESSION_BUS_ADDRESS"):
        return None
    if uid is None:
        if not hasattr(os, "getuid"):
            return None
        uid = os.getuid()
    run_dir = Path(runtime_root) / str(uid)
    if not (run_dir / "bus").exists():
        return None
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={run_dir / 'bus'}"
    env.setdefault("XDG_RUNTIME_DIR", str(run_dir))
    return env


def _q(s: str) -> str:
    """A value quoted for `security -i` (it reads its commands from stdin, so the key never shows in
    the list of running programs)."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


class _Keychain(Backend):
    name = "keychain"

    def __init__(self, exe: str):
        self.exe = exe

    def put(self, acct, value):
        if "\n" in value or "\r" in value:
            return False
        line = (f"add-generic-password -U -a {_q(acct)} -s {_q(SERVICE)} -l {_q('Joe (joe-ai) ' + acct.split('@')[0])} "
                f"-w {_q(value)}\n")
        r = _run([self.exe, "-i"], stdin=line)
        return bool(r and r.returncode == 0)

    def get(self, acct):
        r = _run([self.exe, "find-generic-password", "-a", acct, "-s", SERVICE, "-w"])
        if not r or r.returncode != 0:
            return None
        return r.stdout[:-1] if r.stdout.endswith("\n") else r.stdout

    def delete(self, acct):
        _run([self.exe, "delete-generic-password", "-a", acct, "-s", SERVICE])


class _SecretTool(Backend):
    name = "secret-tool"

    def __init__(self, exe: str):
        self.exe = exe

    @staticmethod
    def _session() -> dict:
        """Extra arguments for _run: the signed-in user's session when this process (cron) has none."""
        env = session_env()
        return {"env": env} if env else {}

    def put(self, acct, value):
        r = _run([self.exe, "store", f"--label=Joe (joe-ai) {acct.split('@')[0]}", "service", SERVICE,
                  "account", acct], stdin=value, **self._session())
        return bool(r and r.returncode == 0)

    def get(self, acct):
        r = _run([self.exe, "lookup", "service", SERVICE, "account", acct], **self._session())
        if not r or r.returncode != 0:
            return None
        return r.stdout[:-1] if r.stdout.endswith("\n") else r.stdout

    def delete(self, acct):
        _run([self.exe, "clear", "service", SERVICE, "account", acct], **self._session())


def backend(settings_path: Path) -> Backend:
    """The store for this computer (Backend() = the settings file)."""
    force = (os.environ.get("JOE_VAULT") or "").strip().lower()
    if force == "file":
        return Backend()
    from . import portable
    if portable.active():
        return Backend()
    if sys.platform == "win32" or force == "dpapi":
        return _DPAPI(settings_path)
    if sys.platform == "darwin":
        exe = shutil.which("security") or ("/usr/bin/security" if Path("/usr/bin/security").exists() else "")
        return _Keychain(exe) if exe else Backend()
    exe = shutil.which("secret-tool")
    return _SecretTool(exe) if exe else Backend()


# ----------------------------------------------------------------------------- settings file
def before_save(settings, data: dict, settings_path: Path) -> dict:
    """The settings about to be written: each key moved into the vault (stored, read back the same,
    only then blanked here). What couldn't be moved stays in the file, which is made owner-only."""
    b = backend(settings_path)
    unread = set(getattr(settings, "_vault_unread", ()) or ())
    listed = set(getattr(settings, "_vault_listed", ()) or ())
    known = dict(getattr(settings, "_vault_known", {}) or {})       # what's in the vault already (no re-store)
    stored, kept = [], []
    for p in SECRETS:
        v = _get(data, p)
        name = dotted(p)
        if not isinstance(v, str):
            continue
        if b.name == "file":
            if v:
                kept.append(name)
            continue
        acct = account(p, settings_path)
        if v:
            ok = known.get(name) == v
            if not ok:
                try:
                    ok = b.put(acct, v) and b.get(acct) == v
                except Exception:                            # noqa: BLE001 (never lose a key over this)
                    ok = False
            if ok:
                _set(data, p, "")
                stored.append(name)
                known[name] = v
            else:
                kept.append(name)
                known.pop(name, None)
        elif name in unread:
            stored.append(name)                               # couldn't read it this time: leave it there
        elif name in listed or name in known:
            try:
                b.delete(acct)                                # cleared on purpose: out of the vault too
            except Exception:                                 # noqa: BLE001
                pass
            known.pop(name, None)
    data["vault"] = {"where": b.name, "keys": stored}
    settings._vault_kept_in_file = kept
    settings._vault_listed = set(stored)
    settings._vault_known = known
    return data


def after_write(settings_path: Path, data: dict) -> None:
    """A settings file that still holds a key is made readable by its owner only (Mac/Linux; on
    Windows the settings folder is already your own)."""
    if os.name == "nt":
        return
    if any(_get(data, p) for p in SECRETS):
        try:
            os.chmod(settings_path, 0o600)
        except OSError:
            pass


def after_load(settings, data: dict, settings_path: Path) -> bool:
    """Fill the keys in from the vault. Returns True when the file should be saved once now: it still
    has keys that should move into the vault (the first start after updating), or it has no "vault"
    part yet."""
    info = data.get("vault") if isinstance(data.get("vault"), dict) else {}
    listed = [k for k in (info.get("keys") or []) if isinstance(k, str)]
    b = backend(settings_path)
    unread = []
    known = {}
    # A settings file with no "vault" part was last saved by an older Joe (someone went back to 2.2
    # and forward again) or was rebuilt after it broke: the keys may still be in the vault, so look
    # there for any the file doesn't have, instead of leaving them stranded.
    older = "vault" not in data and b.name != "file"
    for p in SECRETS:
        name = dotted(p)
        if _get(data, p) or (name not in listed and not older):
            continue
        val = None
        if b.name != "file":
            try:
                val = b.get(account(p, settings_path))
            except Exception:                                # noqa: BLE001
                val = None
        if val is None:
            if name in listed:
                unread.append(name)
            continue
        if name not in listed:
            listed.append(name)
        known[name] = val
        obj = settings
        for k in p[:-1]:
            obj = getattr(obj, k)
        setattr(obj, p[-1], val)
    settings._vault_unread = unread
    settings._vault_listed = set(listed)
    settings._vault_known = known
    return b.name != "file" and (older or any(_get(data, p) for p in SECRETS))


def status(settings, settings_path: Path) -> dict:
    """For Setup > Privacy: where the keys are kept, in plain words."""
    b = backend(settings_path)
    from . import portable
    kept = list(getattr(settings, "_vault_kept_in_file", []) or [])
    unread = list(getattr(settings, "_vault_unread", []) or [])
    if portable.active():
        text = ("Joe is running from a drive, so your keys stay in his settings file on that drive (a computer's "
                "own vault stays with that computer). Keep the drive safe.")
    elif b.name == "file":
        text = ("Your keys are kept in Joe's settings file, readable by your account only. "
                + ("Install your system's keyring (the secret-tool program, with GNOME Keyring or KWallet) and "
                   "Joe moves them there by himself." if sys.platform.startswith("linux") else ""))
    else:
        text = f"Your keys are kept in {LABELS[b.name]}, not in Joe's settings file."
        if kept:
            text += (" These couldn't be put there and stay in the settings file (owner-only): "
                     + ", ".join(kept) + ".")
    if unread:
        text += (" Joe couldn't read " + ", ".join(unread) + " from the vault this time (is it locked?). "
                 "They're still there; nothing was deleted.")
    return {"where": b.name, "label": LABELS.get(b.name, b.name), "text": text.strip(),
            "kept_in_file": kept, "unread": unread}
