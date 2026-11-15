"""Secure connections (2.3): an out-of-date certificate stuck in Windows' list no longer breaks good sites,
Joe says the real reason a site didn't answer, DuckDuckGo gets one more try, and System check has a
SECURE line. Found on a real PC (2026-11-15): Wikipedia "couldn't be reached" because Windows still
held a copy of "ISRG Root X2" that ran out in September 2025. Pretend certificates and local servers only."""
import datetime as dt
import socket
import ssl
import struct
import threading
import urllib.request
from pathlib import Path

import pytest

from joeai import doctor, http, pagereader, websearch
from joeai.config import Settings
from joeai.http import HttpError

import pretend_certs as pc
from fake_search import FakeWeb

ROOT = Path(__file__).resolve().parents[1]


def _der(pem: str) -> bytes:
    return ssl.PEM_cert_to_DER_cert(pem)


SERVER_AUTH = ssl.Purpose.SERVER_AUTH.oid


def _windows(monkeypatch, root=(pc.ROOT_ONE,), ca=(pc.ROOT_TWO_EXPIRED,)):
    """Pretend this is a Windows PC whose certificate lists hold these."""
    lists = {"ROOT": [(_der(p), "x509_asn", True) for p in root],
             "CA": [(_der(p), "x509_asn", True) for p in ca]}
    monkeypatch.setattr(http, "_on_windows", lambda: True)
    monkeypatch.setattr(http, "_windows_store", lambda name: list(lists.get(name, [])))
    return lists


class SecureSite:
    """A pretend https site on this computer: answers as "localhost" with the chain a real site sends
    (its own certificate, then the CURRENT Root Two)."""

    def __init__(self, tmp_path, body=b'{"ok": true}'):
        chain = tmp_path / "chain.pem"
        chain.write_text(pc.LEAF + pc.ROOT_TWO_CURRENT, encoding="utf-8")
        key = tmp_path / "key.pem"
        key.write_text(pc.LEAF_KEY, encoding="utf-8")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(chain), str(key))
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.ctx, self.body, self.stop = ctx, body, False
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self.stop:
            try:
                raw, _ = self.sock.accept()
            except OSError:
                return
            try:
                with self.ctx.wrap_socket(raw, server_side=True) as s:
                    s.settimeout(3)
                    s.recv(4096)
                    s.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                              + str(len(self.body)).encode() + b"\r\nConnection: close\r\n\r\n" + self.body)
            except (OSError, ssl.SSLError):
                pass

    def url(self, path="/"):
        return f"https://localhost:{self.port}{path}"

    def shake_hands(self, ctx):
        with socket.create_connection(("127.0.0.1", self.port), 5) as raw:
            with ctx.wrap_socket(raw, server_hostname="localhost"):
                return True

    def close(self):
        self.stop = True
        self.sock.close()


@pytest.fixture
def site(tmp_path):
    s = SecureSite(tmp_path)
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _joes_own_connections_put_back():
    """A test that installs its own pretend certificate list never leaves it in for the next test."""
    http.forget_cert_trouble()
    yield
    http.forget_cert_trouble()
    http.install()


# --------------------------------------------------------------------------- 1. the certificate list
def test_reads_a_certificates_name_and_end_date():
    f = http.cert_facts(_der(pc.ROOT_TWO_EXPIRED))
    assert f == {"name": "Pretend Root Two", "ends": dt.datetime(2025, 9, 15, 16, 0, tzinfo=dt.timezone.utc)}
    assert http.cert_facts(_der(pc.ROOT_ONE))["ends"].year == 2060           # 2050 and later are written another way
    assert http.cert_facts(b"") is None and http.cert_facts(b"\x30\x03abc") is None
    assert http.cert_facts(_der(pc.LEAF)[:80]) is None                         # a cut-off file never raises


def test_out_of_date_certificates_in_windows_list_are_left_out(monkeypatch):
    lists = _windows(monkeypatch)
    lists["ROOT"].append((b"not a certificate Joe can read", "x509_asn", True))   # kept: OpenSSL decides
    lists["ROOT"].append((_der(pc.LEAF), "x509_asn", {"1.3.6.1.5.5.7.3.4"}))       # trusted for e-mail only
    lists["CA"].append((_der(pc.ROOT_TWO_CURRENT), "pkcs_7_asn", True))            # not a single certificate
    lists["CA"].append((_der(pc.ROOT_TWO_CURRENT), "x509_asn", {SERVER_AUTH}))     # trusted for web sites
    keep, left_out = http.trusted_certs()
    assert _der(pc.ROOT_ONE) in keep and b"not a certificate Joe can read" in keep
    assert _der(pc.ROOT_TWO_CURRENT) in keep
    assert _der(pc.ROOT_TWO_EXPIRED) not in keep and _der(pc.LEAF) not in keep
    assert left_out == [{"name": "Pretend Root Two", "ended": "2025-09-15"}]
    after = dt.datetime(2061, 1, 1, tzinfo=dt.timezone.utc)                       # "now" can be handed in
    assert {x["name"] for x in http.trusted_certs(now=after)[1]} == {"Pretend Root One", "Pretend Root Two"}


def test_a_stale_certificate_no_longer_breaks_a_good_site(monkeypatch, site):
    _windows(monkeypatch)
    ctx = http.tls_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname      # still a fully checked connection
    assert site.shake_hands(ctx)


def test_one_unreadable_certificate_in_the_list_doesnt_bring_the_stale_ones_back(monkeypatch, site):
    lists = _windows(monkeypatch)
    lists["ROOT"].insert(0, (b"\x30\x03abc", "x509_asn", True))            # OpenSSL can't load this one
    assert site.shake_hands(http.tls_context())


def test_a_site_nobody_vouches_for_is_still_refused(monkeypatch, site):
    _windows(monkeypatch, root=(pc.ROOT_TWO_EXPIRED,), ca=())               # Root One isn't trusted on this PC
    with pytest.raises(ssl.SSLCertVerificationError):
        site.shake_hands(http.tls_context())


def test_other_systems_and_an_unreadable_list_use_pythons_own(monkeypatch):
    made = []
    real = ssl.create_default_context

    def spy(*a, **kw):
        made.append(kw)
        return real(*a, **kw)
    monkeypatch.setattr(ssl, "create_default_context", spy)
    monkeypatch.setattr(http, "_on_windows", lambda: False)
    assert http.tls_context().verify_mode == ssl.CERT_REQUIRED and made == [{}]
    monkeypatch.setattr(http, "_on_windows", lambda: True)

    def broken(name):
        raise OSError("Windows wouldn't open its list")
    monkeypatch.setattr(http, "_windows_store", broken)
    assert http.tls_context().verify_mode == ssl.CERT_REQUIRED and made == [{}, {}]


def test_every_web_request_joe_makes_uses_it(monkeypatch, site):
    _windows(monkeypatch)
    http.install()
    assert http.request_json("GET", site.url("/x"), timeout=5) == {"ok": True}        # http.py
    with urllib.request.urlopen(site.url("/y"), timeout=5) as r:                      # updates, downloads, ...
        assert r.status == 200
    assert pagereader._TLSConn("example.org", 443, "93.184.216.34", 5)._context.verify_mode == ssl.CERT_REQUIRED
    marker = ssl.create_default_context()
    monkeypatch.setattr(http, "tls_context", lambda: marker)
    assert pagereader._TLSConn("example.org", 443, "93.184.216.34", 5)._context is marker   # the page reader


def test_joe_starts_with_it_installed():
    import joeai
    src = (ROOT / "joeai" / "__init__.py").read_text(encoding="utf-8")
    assert "_http.install()" in src and joeai.__version__
    assert any(isinstance(h, http._Https) for h in urllib.request._opener.handlers)


# --------------------------------------------------------------------------- 2. the real reason
def _closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Rude:
    """A server that takes the call and hangs up (drop=True) or never says a word."""

    def __init__(self, drop):
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port, self.drop, self.held = self.sock.getsockname()[1], drop, []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            if self.drop:
                c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))   # hang up hard
                c.close()
            else:
                self.held.append(c)

    def close(self):
        self.sock.close()
        for c in self.held:
            c.close()


def _kind(url, timeout=5):
    with pytest.raises(HttpError) as e:
        http.request_json("GET", url, timeout=timeout)
    assert str(e.value).startswith(f"can't reach {url}: ")        # the old words stay (comfy.py reads them)
    return e.value.kind


def test_http_errors_say_what_kind_of_trouble_it_was(monkeypatch, site):
    monkeypatch.setattr(http, "_on_windows", lambda: False)        # this PC doesn't know Pretend Root One
    http.install()
    assert _kind(site.url("/")) == "cert"
    assert _kind(f"http://127.0.0.1:{_closed_port()}/") == "refused"
    rude = _Rude(drop=True)
    quiet = _Rude(drop=False)
    try:
        assert _kind(f"http://127.0.0.1:{rude.port}/") == "dropped"
        assert _kind(f"http://127.0.0.1:{quiet.port}/", timeout=0.4) == "timeout"
    finally:
        rude.close()
        quiet.close()
    assert _kind("http://no-such-site.invalid/") == "name"
    with FakeWeb() as web:
        web.route("/gone", {"error": "no"}, status=500)
        with pytest.raises(HttpError) as e:
            http.request_json("GET", web.url("/gone"))
        assert e.value.kind == "" and str(e.value).startswith("HTTP 500 ")


def test_a_certificate_refusal_is_remembered_for_system_check(monkeypatch, site):
    monkeypatch.setattr(http, "_on_windows", lambda: False)
    http.install()
    assert http.cert_trouble() is None
    with pytest.raises(OSError):
        urllib.request.urlopen(site.url("/"), timeout=5)           # any request, not only http.py's
    t = http.cert_trouble()
    assert t["site"] == "localhost" and t["why"] and t["when"] > 0
    http.forget_cert_trouble()
    assert http.cert_trouble() is None


@pytest.mark.parametrize("kind, says", [
    ("cert", "this PC didn't accept its security certificate (System check > SECURE says more)"),
    ("dropped", "the connection was cut off on the way"),
    ("timeout", "it took too long to answer"),
    ("name", "its address couldn't be found (is the internet connected?)"),
    ("refused", "it couldn't be reached"),
    ("", "it couldn't be reached"),
])
def test_a_search_source_says_the_real_reason(kind, says, monkeypatch):
    def fail(*a, **kw):
        raise HttpError("can't reach https://x: boom", kind=kind)
    monkeypatch.setattr(websearch, "request_json", fail)
    s = Settings()
    s.web.providers = "wikipedia"
    assert websearch.try_each(s) == [{"id": "wikipedia", "label": "Wikipedia", "ok": False, "text": says}]
    f = websearch.find("pottery", s)
    assert f.via() == f"Nothing found online: Wikipedia didn't answer ({says})."


# --------------------------------------------------------------------------- 3. DuckDuckGo
DDG = {"Heading": "Raku", "AbstractText": "Raku is a Japanese pottery technique.",
       "AbstractURL": "https://en.wikipedia.org/wiki/Raku_ware", "AbstractSource": "Wikipedia"}


def _ddg(monkeypatch, answers):
    """DuckDuckGo answers these, one per call: an HttpError kind to raise, or (status, data)."""
    calls = []

    def fake(method, url, payload=None, timeout=10, headers=None):
        calls.append(url)
        a = answers[min(len(calls), len(answers)) - 1]
        if isinstance(a, str):
            raise HttpError(f"can't reach {url}: {a}" if not a.startswith("HTTP") else a,
                            kind="" if a.startswith("HTTP") else a)
        return a
    monkeypatch.setattr(websearch, "request_json_status", fake)
    monkeypatch.setattr(websearch, "RETRY_PAUSE", 0)
    s = Settings()
    s.web.providers = "duckduckgo"
    return s, calls


def test_duckduckgo_gets_one_more_try_after_a_dropped_connection(monkeypatch):
    s, calls = _ddg(monkeypatch, ["dropped", (200, DDG)])
    f = websearch.find("raku", s)
    assert f.source == "duckduckgo" and len(calls) == 2 and not f.notes
    s, calls = _ddg(monkeypatch, ["timeout", (200, DDG)])
    assert websearch.find("raku", s) and len(calls) == 2


def test_duckduckgo_only_gets_one_more_try(monkeypatch):
    s, calls = _ddg(monkeypatch, ["dropped", "dropped", (200, DDG)])
    f = websearch.find("raku", s)
    assert not f and len(calls) == 2
    assert f.via() == "Nothing found online: DuckDuckGo Instant Answers didn't answer (the connection was cut off on the way)."


def test_duckduckgo_is_not_asked_again_after_a_plain_refusal(monkeypatch):
    for bad in ("HTTP 429 from x: slow down", "cert", "name"):
        websearch.reset_cooldowns()
        s, calls = _ddg(monkeypatch, [bad, (200, DDG)])
        assert not websearch.find("raku", s) and len(calls) == 1, bad


def test_duckduckgo_saying_wait_is_busy_not_broken(monkeypatch):
    s, calls = _ddg(monkeypatch, [(202, {})])
    assert websearch.try_each(s) == [{"id": "duckduckgo", "label": "DuckDuckGo Instant Answers", "ok": False,
                                      "text": "it is busy right now (it asked Joe to wait); try again in a minute"}]
    f = websearch.find("raku", s)
    assert not f and "busy right now" in f.via()
    assert "resting" in websearch.find("raku again", s).via()          # Joe leaves it alone for a moment
    websearch.reset_cooldowns()
    s, calls = _ddg(monkeypatch, [(202, DDG)])                         # "accepted" WITH an answer is an answer
    assert websearch.find("raku", s).source == "duckduckgo"
    websearch.reset_cooldowns()
    s, calls = _ddg(monkeypatch, [(200, {})])                          # nothing known about it: not a failure
    assert websearch.try_each(s)[0]["text"] == "answered, but found nothing"


def test_request_json_status_gives_the_status_too():
    with FakeWeb() as web:
        web.route("/wait", {}, status=202)
        web.route("/ok", {"a": 1})
        assert http.request_json_status("GET", web.url("/wait")) == (202, {})
        assert http.request_json_status("GET", web.url("/ok")) == (200, {"a": 1})
        assert http.request_json("GET", web.url("/ok")) == {"a": 1}


# --------------------------------------------------------------------------- 4. System check and the guide
def test_system_check_secure_line(monkeypatch):
    monkeypatch.setattr(http, "_on_windows", lambda: False)
    assert doctor.secure_line() == {"ok": True, "text": "no certificate trouble since Joe started"}
    _windows(monkeypatch)
    line = doctor.secure_line()
    assert line["ok"] and line["text"] == ("no certificate trouble since Joe started "
                                           "(Joe skips 1 out-of-date certificate in Windows' list)")
    http.note_cert_trouble("en.wikipedia.org", "certificate has expired")
    line = doctor.secure_line()
    assert not line["ok"]
    assert line["text"].startswith("this PC didn't accept the security certificate of en.wikipedia.org "
                                   "(certificate has expired).")
    for cause in ("date and time", "antivirus", "Windows Update", "GUIDE"):
        assert cause in line["text"], cause


def test_system_check_shows_the_secure_line_and_the_guide_explains_it():
    doc = (ROOT / "joeai" / "doctor.py").read_text(encoding="utf-8")
    assert '"secure": secure_line()' in doc
    js = (ROOT / "joeai" / "ui" / "app.js").read_text(encoding="utf-8")
    assert "SECURE   ${" in js and "d.secure" in js
    guide = (ROOT / "docs" / "GUIDE.md").read_text(encoding="utf-8")
    assert "Secure connections" in guide and "out-of-date certificate" in guide
    assert "certmgr.msc" in guide                                   # how to look, for whoever helps
