"""Tiny JSON-over-HTTP helper (stdlib only, keeps the packaged app small), and what Joe trusts
for secure (https) connections.

Why Joe builds his own trusted list on Windows: Python hands OpenSSL every certificate in Windows'
"trusted roots" AND "intermediate" lists. Windows never clears out-of-date ones, and OpenSSL then
follows a stale one and refuses a perfectly good site ("certificate has expired"). Browsers skip
them; so does Joe now (found 2026-11-15: an "ISRG Root X2" copy that ran out in September 2025
made Wikipedia unreachable). An out-of-date certificate can never make a connection pass, so
leaving it out can't let anything through that wasn't let through before. Nothing on the PC is
changed: Joe only decides what he reads."""
from __future__ import annotations

import datetime as _dt
import errno
import http.client
import json
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request


class HttpError(RuntimeError):
    """`kind` says what sort of trouble it was, for a plain reason on screen:
    "cert" (this PC didn't accept the site's certificate), "dropped" (cut off on the way),
    "timeout", "name" (the site's name couldn't be looked up), "refused", or "" (anything else,
    and every "HTTP 404"-style answer)."""

    def __init__(self, text: str, kind: str = ""):
        super().__init__(text)
        self.kind = kind


# --------------------------------------------------------------------------- reading a certificate
def _tlv(b: bytes, i: int) -> tuple[int, int, int]:
    """One piece of a certificate file at position i: (its tag, where its content starts, where it ends)."""
    tag, n = b[i], b[i + 1]
    i += 2
    if n & 0x80:
        k = n & 0x7F
        if not 1 <= k <= 4:
            raise ValueError("odd length")
        n = int.from_bytes(b[i:i + k], "big")
        i += k
    if i + n > len(b):
        raise ValueError("cut off")
    return tag, i, i + n


def _when(tag: int, raw: bytes) -> _dt.datetime:
    t = raw.decode("ascii")
    if tag == 0x17:                                    # two-digit year: 50-99 are 1950-1999
        t = ("19" if int(t[:2]) >= 50 else "20") + t
    elif tag != 0x18:
        raise ValueError("not a date")
    return _dt.datetime.strptime(t[:14], "%Y%m%d%H%M%S").replace(tzinfo=_dt.timezone.utc)


def cert_facts(der: bytes) -> dict | None:
    """{"name": who the certificate is for, "ends": the moment it runs out} or None when Joe can't read it."""
    try:
        _, i, _ = _tlv(der, 0)                         # the certificate
        _, i, tbs_end = _tlv(der, i)                   # the signed part
        tag, a, z = _tlv(der, i)
        if tag == 0xA0:                                # version (left out in very old ones)
            tag, a, z = _tlv(der, z)
        for _ in range(2):                             # serial number -> signature kind -> issuer
            tag, a, z = _tlv(der, z)
        tag, a, z = _tlv(der, z)                       # the dates
        if tag != 0x30:
            return None
        _, _, nb_end = _tlv(der, a)                    # starts
        t, s, e = _tlv(der, nb_end)                    # ends
        ends = _when(t, der[s:e])
        tag, a, subj_end = _tlv(der, z)                # who it is for
        name, org = "", ""
        while a < subj_end:
            _, s1, set_end = _tlv(der, a)              # SET
            _, s2, _ = _tlv(der, s1)                   # SEQUENCE
            _, o1, o2 = _tlv(der, s2)                  # what kind of name
            vt, v1, v2 = _tlv(der, o2)
            text = der[v1:v2].decode("utf-16-be" if vt == 0x1E else "utf-8", "replace").strip()
            if der[o1:o2] == b"\x55\x04\x03":          # common name
                name = text
            elif der[o1:o2] in (b"\x55\x04\x0a", b"\x55\x04\x0b") and not org:
                org = text
            a = set_end
        return {"name": (name or org or "a certificate with no name")[:80], "ends": ends}
    except (ValueError, IndexError, UnicodeError, OverflowError):
        return None


# --------------------------------------------------------------------------- what Joe trusts
def _on_windows() -> bool:
    return sys.platform == "win32"


def _windows_store(name: str) -> list:
    """Windows' own list ("ROOT" or "CA"): (certificate, how it's written, what it's trusted for)."""
    return list(ssl.enum_certificates(name))


def trusted_certs(now: _dt.datetime | None = None) -> tuple[list[bytes], list[dict]]:
    """Windows' certificates the way Python loads them, minus the ones that have run out.
    Returns (the certificates, [{"name", "ended"}] for each one left out)."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    keep, left_out, seen = [], [], set()
    for store in ("CA", "ROOT"):
        for cert, how, trust in _windows_store(store):
            if how != "x509_asn" or not (trust is True or ssl.Purpose.SERVER_AUTH.oid in trust):
                continue                               # the same rule Python uses
            cert = bytes(cert)
            if cert in seen:
                continue
            seen.add(cert)
            f = cert_facts(cert)
            if f and f["ends"] < now:
                left_out.append({"name": f["name"], "ended": f["ends"].strftime("%Y-%m-%d")})
                continue
            keep.append(cert)
    left_out.sort(key=lambda x: (x["name"], x["ended"]))
    return keep, left_out


def tls_context() -> ssl.SSLContext:
    """What Joe checks a secure connection against. Always a fully checked connection (the site's
    certificate and its name). On Windows: the PC's list without out-of-date certificates."""
    if _on_windows():
        try:
            ctx = None
            for cert in trusted_certs()[0]:            # one at a time: a certificate OpenSSL can't
                try:                                   # read is passed over, not the ones after it
                    if ctx is None:
                        ctx = ssl.create_default_context(cadata=cert)
                    else:
                        ctx.load_verify_locations(cadata=cert)
                except ssl.SSLError:
                    continue
            if ctx is not None:
                return ctx
        except Exception:                              # noqa: BLE001 (any trouble: Python's own way)
            pass
    return ssl.create_default_context()


def skipped_certs() -> list[dict]:
    """The out-of-date certificates Joe leaves out on this PC ([] off Windows or when the list can't be read)."""
    if not _on_windows():
        return []
    try:
        return trusted_certs()[1]
    except Exception:                                  # noqa: BLE001
        return []


# --------------------------------------------------------------------------- certificate trouble seen
_trouble: dict | None = None
_lock = threading.Lock()


def note_cert_trouble(site: str, why: str) -> None:
    """Remember the latest site whose certificate this PC didn't accept (System check shows it)."""
    global _trouble
    with _lock:
        _trouble = {"site": str(site or "a site")[:120], "why": str(why or "it couldn't be checked")[:160],
                    "when": time.time()}


def cert_trouble() -> dict | None:
    with _lock:
        return dict(_trouble) if _trouble else None


def forget_cert_trouble() -> None:
    global _trouble
    with _lock:
        _trouble = None


def _cert_error(e: BaseException) -> ssl.SSLCertVerificationError | None:
    for x in (e, getattr(e, "reason", None), e.__cause__, e.__context__):
        if isinstance(x, ssl.SSLCertVerificationError):
            return x
    return None


class _Https(urllib.request.HTTPSHandler):
    """Every https request Joe makes: checked against tls_context(), and a certificate refusal is noted.
    The certificate list is read on the first secure request, not when Joe starts: the connector and
    other parts that never go online don't touch it."""

    def __init__(self):
        urllib.request.AbstractHTTPHandler.__init__(self)      # no list read yet
        self._ctx = None
        self._ctx_lock = threading.Lock()

    def _context_now(self) -> ssl.SSLContext:
        with self._ctx_lock:
            if self._ctx is None:
                self._ctx = tls_context()
            return self._ctx

    def https_open(self, req):
        try:
            return self.do_open(http.client.HTTPSConnection, req, context=self._context_now())
        except OSError as e:
            c = _cert_error(e)
            if c is not None:
                note_cert_trouble(req.host.rsplit(":", 1)[0] if req.host else "",
                                  getattr(c, "verify_message", "") or str(c))
            raise


def install() -> bool:
    """Make every urllib request in Joe (lookups, update checks, downloads) use tls_context().
    Called once when Joe starts (joeai/__init__.py). Reads nothing and connects to nothing itself.
    False when it couldn't be set up (Joe still starts; connections then go Python's own way)."""
    try:
        urllib.request.install_opener(urllib.request.build_opener(_Https()))
        return True
    except Exception:                                  # noqa: BLE001 (never stop Joe from starting)
        return False


# --------------------------------------------------------------------------- requests
def _kind(e: BaseException) -> str:
    r = getattr(e, "reason", None)
    r = r if isinstance(r, BaseException) else e
    if _cert_error(e) is not None:
        return "cert"
    if isinstance(r, (TimeoutError, socket.timeout)) or "timed out" in str(r).lower():
        return "timeout"
    if isinstance(r, socket.gaierror):
        return "name"
    if isinstance(r, ConnectionRefusedError):
        return "refused"
    if isinstance(r, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError,
                      http.client.RemoteDisconnected, http.client.IncompleteRead, ssl.SSLEOFError)):
        return "dropped"
    # A hang-up can also come as a plain OSError, known only by its number. On a Mac, once the other
    # side has reset the connection, Python's own "no delay" setting fails with EINVAL ("Invalid
    # argument"); that is the same hang-up (found on GitHub's Mac run, 2026-11-22). EINVAL is too
    # general to trust on other systems, so only a Mac reads it that way.
    n = getattr(r, "errno", None)
    if n in (errno.ECONNRESET, errno.ECONNABORTED, errno.EPIPE, errno.ENOTCONN):
        return "dropped"
    if n == errno.EINVAL and sys.platform == "darwin":
        return "dropped"
    return ""


def request_json_status(method: str, url: str, payload: dict | None = None, timeout: float = 10,
                        headers: dict | None = None):
    """(the HTTP status, the JSON answer). An empty answer is {}."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise HttpError(f"HTTP {e.code} from {url}: {detail}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.HTTPException) as e:
        raise HttpError(f"can't reach {url}: {e}", kind=_kind(e)) from e
    if not body.strip():
        return status, {}
    try:
        return status, json.loads(body)
    except json.JSONDecodeError as e:
        raise HttpError(f"bad JSON from {url}: {body[:200]}") from e


def request_json(method: str, url: str, payload: dict | None = None, timeout: float = 10,
                 headers: dict | None = None):
    return request_json_status(method, url, payload, timeout, headers)[1]


def request_bytes(url: str, timeout: float = 60) -> bytes:
    """GET raw bytes (images/videos from ComfyUI's /view)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise HttpError(f"HTTP {e.code} from {url}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise HttpError(f"can't reach {url}: {e}", kind=_kind(e)) from e
