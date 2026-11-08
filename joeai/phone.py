"""Joe Phone: a small web app Joe serves to phones on your home Wi-Fi (Setup > Phone).

- Off until you turn it on. It runs only while Joe's window is open, on your home network only:
  requests from outside your home network are refused, and Joe never opens your router.
- A phone is paired once by scanning a QR code on Joe's screen (a one-time code, good for 10
  minutes). The phone then keeps its own key; Joe keeps only a fingerprint of it, and REMOVE in
  Setup > Phone ends that phone's access.
- It can do only what this file lists: see the run and the queue, stop a run, lists and reminders,
  ask Joe (plans need RUN IT on the phone, like on the PC), quick answers, and look at results.
  It can't change settings, open programs or read files outside Joe's Output folder.
- Home Wi-Fi traffic is plain HTTP (no certificate), like most home devices' own pages: fine at home,
  never on public Wi-Fi.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import secrets
import socket
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .fsutil import atomic_write_text

PAIR_MINUTES = 10
MAX_BAD_PAIRS = 8               # wrong pairing codes per 10 minutes before pairing pauses
PICTURE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")
TEXT_EXT = (".md", ".txt", ".csv")
VIDEO_EXT = (".mp4", ".webm", ".mov")
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".ogg")
MAX_FILE = 60_000_000           # biggest file the phone can open (a short video clip)


def _store_path() -> Path:
    from .config import config_path
    return config_path().with_name("phone.json")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_devices() -> list[dict]:
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
        return [d for d in data.get("devices", []) if isinstance(d, dict) and d.get("hash")]
    except (OSError, ValueError, AttributeError):
        return []


def save_devices(devices: list[dict]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, json.dumps({"devices": devices}, indent=1))


def remove_device(dev_id: str) -> bool:
    devs = load_devices()
    left = [d for d in devs if d.get("id") != dev_id]
    save_devices(left)
    return len(left) < len(devs)


def is_home(ip: str) -> bool:
    """A private home-network or this-PC address (never the internet)."""
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return a.is_private or a.is_loopback or a.is_link_local


def lan_ip() -> str:
    """This PC's address on the home network ('' when it has none). Nothing is sent: a UDP socket
    'connected' to a private address just tells which network card Windows/Mac/Linux would use."""
    for probe in ("192.168.0.1", "10.0.0.1", "172.16.0.1"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((probe, 9))
                ip = s.getsockname()[0]
            if ip and not ip.startswith("127.") and is_home(ip):
                return ip
        except OSError:
            continue
    return ""


class Phone:
    """The phone server's state: pairing code, paired phones, the server thread."""

    def __init__(self, app):
        self.app = app
        self.httpd: ThreadingHTTPServer | None = None
        self.address = ""
        self.error = ""
        self._pair: dict = {}
        self._bad: list[float] = []
        self.lock = threading.Lock()

    # -- life cycle -----------------------------------------------------------
    def apply(self) -> None:
        """Start, restart or stop to match Setup > Phone."""
        ps = self.app.settings.phone
        want = bool(ps.enabled)
        port = int(ps.port or 8770)
        if self.httpd and (not want or self.httpd.server_address[1] != port):
            self.stop()
        if want and not self.httpd:
            self.start(port)

    def start(self, port: int) -> None:
        ip = lan_ip()
        if not ip:
            self.error = "This PC isn't on a home network right now (Wi-Fi or a cable), so phones can't reach Joe."
            self.app.log("Joe Phone: " + self.error)
            return
        try:
            from . import system
            cls = ThreadingHTTPServer
            if system.WINDOWS:
                class _S(ThreadingHTTPServer):
                    allow_reuse_address = False
                cls = _S
            self.httpd = cls((ip, port), make_handler(self))
        except OSError as e:
            self.httpd = None
            self.error = f"Couldn't use port {port} ({e.strerror or e}). Pick another number in Setup > Phone."
            self.app.log("Joe Phone: " + self.error)
            return
        self.httpd.daemon_threads = True
        self.address = f"http://{ip}:{port}/"
        self.error = ""
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="joe-phone").start()
        self.app.log(f"Joe Phone is on at {self.address} (home Wi-Fi only)")

    def stop(self) -> None:
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except OSError:
                pass
        self.httpd = None
        self.address = ""

    # -- pairing ----------------------------------------------------------------
    def new_pairing(self) -> dict:
        if not self.httpd:
            return {"ok": False, "error": self.error or "Turn Joe Phone on first (Setup > Phone), then pair."}
        code = secrets.token_urlsafe(9)
        with self.lock:
            self._pair = {"hash": _hash(code), "until": time.time() + PAIR_MINUTES * 60}
        url = f"{self.address}#pair={code}"
        from . import qr
        return {"ok": True, "url": url, "address": self.address, "code": code, "minutes": PAIR_MINUTES,
                "qr": qr.svg(url, scale=5)}

    def pair(self, code: str, name: str) -> dict:
        now = time.time()
        with self.lock:
            self._bad = [t for t in self._bad if now - t < 600]
            if len(self._bad) >= MAX_BAD_PAIRS:
                return {"ok": False, "error": "Too many wrong codes. Wait 10 minutes, then pair again from Joe's screen."}
            good = bool(self._pair) and now < self._pair["until"] and \
                secrets.compare_digest(self._pair["hash"], _hash(code or ""))
            if not good:
                self._bad.append(now)
                return {"ok": False, "error": "That pairing code is wrong or too old. Press PAIR A PHONE on Joe's "
                                              "screen and scan the new code."}
            self._pair = {}                                  # one phone per code
        token = secrets.token_urlsafe(32)
        dev = {"id": secrets.token_hex(4), "name": (name or "Phone").strip()[:40] or "Phone", "hash": _hash(token),
               "added": datetime.now().isoformat(timespec="minutes"), "last": ""}
        devs = load_devices()
        devs.append(dev)
        save_devices(devs)
        self.app.log(f"Joe Phone: paired '{dev['name']}'")
        return {"ok": True, "token": token, "name": dev["name"]}

    def device(self, token: str) -> dict | None:
        if not token:
            return None
        h = _hash(token)
        devs = load_devices()
        for d in devs:
            if secrets.compare_digest(d["hash"], h):
                stamp = datetime.now().isoformat(timespec="minutes")
                if d.get("last") != stamp:
                    d["last"] = stamp
                    save_devices(devs)
                return d
        return None

    def info(self) -> dict:
        ps = self.app.settings.phone
        return {"enabled": bool(ps.enabled), "on": bool(self.httpd), "address": self.address, "error": self.error,
                "port": ps.port, "devices": [{k: d.get(k, "") for k in ("id", "name", "added", "last")}
                                             for d in load_devices()]}

    # -- what the phone can see and do ----------------------------------------------
    def status(self) -> dict:
        st = self.app.state()
        jobs = st.get("jobs") or []
        now = next((j for j in jobs if j.get("current")), None)
        done = sum(j.get("parts_done", 0) for j in jobs)
        total = sum(j.get("parts_total", 0) for j in jobs)
        return {"ok": True, "version": st.get("version"), "running": st.get("running"), "stopping": st.get("stopping"),
                "doing": now.get("name") if now else "", "done": done, "total": total, "eta_s": st.get("eta_s"),
                "queued": st.get("queued") or [], "report": st.get("report"),
                "media": [m for m in (st.get("media") or [])][:6],
                "log": (st.get("log") or [])[-6:]}

    def lists(self) -> dict:
        from . import reminders
        folder = self.app.sb.root / "Lists"
        names = []
        if folder.is_dir():
            for f in sorted(folder.glob("*list.md")):
                names.append(reminders.list_name(f.stem[:-4].replace("-", " ").strip()))
        for must in ("to-do", "shopping"):
            if must not in names:
                names.append(must)
        return {"ok": True, "lists": [{"name": n, "items": reminders.read_list(self.app.sb, n)} for n in names]}

    def reminders(self) -> dict:
        from . import reminders
        items = [r for r in reminders.load(self.app.sb) if not r.get("done")]
        items.sort(key=lambda r: r.get("when", ""))
        return {"ok": True, "reminders": [{"when": r["when"][:16].replace("T", " "), "what": r.get("what", "")}
                                          for r in items[:50]]}

    def results(self) -> dict:
        out = self.app.sb.output
        found = []
        for p in out.rglob("*"):
            try:
                rel = p.relative_to(out)
            except ValueError:
                continue
            if not p.is_file() or any(part.startswith((".", "_")) for part in rel.parts):
                continue
            ext = p.suffix.lower()
            kind = ("picture" if ext in PICTURE_EXT else "text" if ext in TEXT_EXT else
                    "video" if ext in VIDEO_EXT else "sound" if ext in AUDIO_EXT else "")
            if kind:
                found.append((p.stat().st_mtime, str(rel).replace("\\", "/"), kind, p.stat().st_size))
        found.sort(reverse=True)
        return {"ok": True, "files": [{"path": r, "kind": k, "size": s,
                                       "when": datetime.fromtimestamp(t).strftime("%m-%d %H:%M")}
                                      for t, r, k, s in found[:60]]}

    def file(self, rel: str) -> tuple[Path | None, str]:
        from .sandbox import SandboxError
        try:
            import os
            p = self.app.sb.resolve(rel, base="Output")
            Path(os.path.realpath(p)).relative_to(Path(os.path.realpath(self.app.sb.output)))
        except (SandboxError, ValueError, OSError):
            return None, "That file isn't in Joe's Output folder."
        if not p.is_file():
            return None, "That file isn't there any more."
        ext = p.suffix.lower()
        if ext not in PICTURE_EXT + TEXT_EXT + VIDEO_EXT + AUDIO_EXT:
            return None, "Joe Phone shows pictures, videos, sounds and text files."
        if p.stat().st_size > MAX_FILE:
            return None, "That file is too big to open on the phone. Open it on the PC (Files, F7)."
        return p, ""

    def ask(self, text: str) -> dict:
        """The phone's box: reminders, lists, quick answers and stop happen right away; questions get
        Joe's answer; work gets a plan the person can RUN IT from the phone."""
        from . import reminders, route
        text = (text or "").strip()[:2000]
        if not text:
            return {"ok": False, "error": "Type or say what you need."}
        rt = route.classify(text)
        if rt.get("kind") == "command":
            cmd = rt.get("cmd")
            sb, s = self.app.sb, self.app.settings
            if cmd == "quick":
                return {"ok": True, "say": rt["say"]}
            if cmd == "remind":
                return reminders.add(sb, s, rt.get("text", ""))
            if cmd == "list-add":
                return reminders.list_add(sb, rt.get("list", ""), rt.get("items", ""))
            if cmd == "list-done":
                return reminders.list_done(sb, rt.get("list", ""), rt.get("items", ""))
            if cmd == "list-show":
                return reminders.list_show(sb, rt.get("list", ""))
            if cmd == "list-send":
                return reminders.list_send(sb, s, rt.get("list", ""))
            if cmd in ("directions", "shop"):
                r = (reminders.directions if cmd == "directions" else reminders.shopping)(s, rt.get("text", ""))
                return r                                       # the phone opens r["open"] itself
            if cmd == "stop":
                return self.stop_run()
            if cmd == "run":
                return {"ok": True, "say": "Tap RUN IT under a plan to start it."}
            if cmd == "park":
                return self.app.park_idea(rt.get("idea", ""))
            if cmd in ("report", "files"):
                return {"ok": True, "say": "Open the Results tab below.", "tab": "results"}
            return {"ok": True, "say": "That one works on the PC screen. On the phone: ask, lists, reminders, "
                                       "results, and stop."}
        if rt.get("kind") == "unclear":
            return {"ok": True, "say": rt.get("say", "Try a few more words.")}
        if rt.get("kind") == "chat":
            r = self.app.talk(text)
            return {"ok": bool(r.get("ok", True)), "say": r.get("say") or r.get("error") or "",
                    "error": r.get("error", "")}
        from .chat import busy_drawing
        if busy_drawing(self.app):
            return {"ok": False, "error": "Joe is busy drawing right now. Ask again when the pictures are done."}
        r = self.app.plan_now(text)
        if not r.get("ok"):
            return r
        return {"ok": True, "say": "Here's the plan (" + str(r.get("time", "")) + "):", "summary": r.get("summary", ""),
                "mission": r.get("mission", "")}

    def run_plan(self, mission: str) -> dict:
        mission = (mission or "").strip()
        if not mission:
            return {"ok": False, "error": "There's no plan to run."}
        r = self.app.run(mission) if not self.app.running else self.app.enqueue(mission)
        if r.get("ok"):
            r["say"] = "Added to the queue." if r.get("queued") else "Started. Watch it on the Home tab."
        return r

    def stop_run(self) -> dict:
        if not self.app.running:
            return {"ok": True, "say": "Nothing is running."}
        self.app.stop.set()
        self.app.log("Stop requested from Joe Phone: finishing the current step...")
        return {"ok": True, "say": "Stopping after the current step."}


def _ui_file(name: str) -> bytes:
    return (Path(__file__).with_name("ui") / name).read_bytes()


ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="12" '
        'fill="#0b0f0b"/><text x="32" y="44" font-family="monospace" font-size="34" font-weight="bold" '
        'text-anchor="middle" fill="#41ff6a">J</text></svg>')
MANIFEST = {"name": "Joe", "short_name": "Joe", "start_url": "/", "display": "standalone",
            "background_color": "#0b0f0b", "theme_color": "#0b0f0b",
            "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]}


def make_handler(phone: Phone):
    class H(BaseHTTPRequestHandler):
        server_version = "JoePhone"

        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

        def _home(self) -> bool:
            if is_home(self.client_address[0]):
                return True
            self._send(403, b"Joe Phone only answers on your home network.", "text/plain")
            return False

        def _dev(self, q: dict) -> dict | None:
            d = phone.device(self.headers.get("X-Joe-Phone") or (q.get("k") or [""])[0])
            if d is None:
                self._json({"ok": False, "error": "This phone isn't paired (or was removed). Pair it again from "
                                                  "Joe's screen: Setup > Phone > PAIR A PHONE.", "unpaired": True}, 401)
            return d

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= 200_000:
                return {}
            try:
                b = json.loads(self.rfile.read(n).decode("utf-8"))
                return b if isinstance(b, dict) else {}
            except (ValueError, UnicodeDecodeError):
                return {}

        def do_GET(self):
            if not self._home():
                return
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path in ("/", "/index.html"):
                csp = ("default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; "
                       "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
                return self._send(200, _ui_file("phone.html"), "text/html; charset=utf-8",
                                  {"Content-Security-Policy": csp, "X-Frame-Options": "DENY"})
            if u.path == "/manifest.json":
                return self._send(200, json.dumps(MANIFEST).encode(), "application/manifest+json")
            if u.path == "/icon.svg":
                return self._send(200, ICON.encode(), "image/svg+xml")
            if self._dev(q) is None:
                return
            try:
                if u.path == "/api/status":
                    return self._json(phone.status())
                if u.path == "/api/lists":
                    return self._json(phone.lists())
                if u.path == "/api/reminders":
                    return self._json(phone.reminders())
                if u.path == "/api/results":
                    return self._json(phone.results())
                if u.path == "/api/report":
                    p = phone.app.sb.output / "_REPORT.md"
                    return self._json({"ok": True, "text": p.read_text(encoding="utf-8", errors="replace")[:60000]
                                       if p.exists() else "No report yet."})
                if u.path == "/api/file":
                    p, err = phone.file((q.get("p") or [""])[0])
                    if p is None:
                        return self._json({"ok": False, "error": err}, 404)
                    import mimetypes
                    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                    if p.suffix.lower() in TEXT_EXT:
                        ctype = "text/plain; charset=utf-8"
                    return self._send(200, p.read_bytes(), ctype, {"Content-Security-Policy": "sandbox"})
            except Exception as e:                          # noqa: BLE001 (one bad request never stops Joe)
                return self._json({"ok": False, "error": f"Joe had trouble with that: {e}"}, 500)
            self._json({"ok": False, "error": "unknown"}, 404)

        def do_POST(self):
            if not self._home():
                return
            u = urlparse(self.path)
            b = self._body()
            if u.path == "/api/pair":
                return self._json(phone.pair(str(b.get("code", "")), str(b.get("name", ""))))
            if self._dev({}) is None:
                return
            try:
                if u.path == "/api/ask":
                    return self._json(phone.ask(str(b.get("text", ""))))
                if u.path == "/api/run":
                    return self._json(phone.run_plan(str(b.get("mission", ""))))
                if u.path == "/api/stop":
                    return self._json(phone.stop_run())
                if u.path == "/api/list":
                    from . import reminders
                    name = str(b.get("name", ""))[:40]
                    if b.get("add"):
                        return self._json(reminders.list_add(phone.app.sb, name, str(b["add"])[:500]))
                    if b.get("done"):
                        return self._json(reminders.list_done(phone.app.sb, name, str(b["done"])[:500]))
                    return self._json({"ok": False, "error": "Add or check off what?"})
                if u.path == "/api/remind":
                    from . import reminders
                    return self._json(reminders.add(phone.app.sb, phone.app.settings, str(b.get("text", ""))[:500]))
                if u.path == "/api/forget":                  # the phone removes itself
                    d = phone.device(self.headers.get("X-Joe-Phone") or "")
                    return self._json({"ok": bool(d and remove_device(d["id"]))})
            except Exception as e:                          # noqa: BLE001
                return self._json({"ok": False, "error": f"Joe had trouble with that: {e}"}, 500)
            self._json({"ok": False, "error": "unknown"}, 404)

    return H
