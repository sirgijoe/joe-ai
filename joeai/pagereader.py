"""Joe's own safe page reader: the text of one web page, for people without the Ollama key.

Used only to read a page that a search returned (websearch.read_page), and only when the person
turned on Setup > Privacy and internet > "Let RESEARCH tasks read whole result pages".

What it will and won't do (tests/test_pagereader.py checks each line):
  - http:// and https:// only. No name and password in the address. Usual web ports only.
  - Never this PC or the home network: names like localhost, printer.local or a one-word name are
    refused; every address a name points at must be out on the internet, and Joe connects to the
    address he checked (so a name can't be switched to a home address in between), then checks the
    connection itself once more before sending anything.
  - At most MAX_REDIRECTS redirects, each new address checked the same way.
  - Text only: an HTML or plain-text page. Pictures, PDFs, programs and anything else are refused.
    Packed (gzip) answers are refused, so a small download can't unpack into a huge one.
  - Size cap (MAX_BYTES downloaded, MAX_TEXT characters kept) and a time limit for the whole read.
  - Scripts never run: the page is only parsed for its words; script, style, menus and parts
    marked hidden are dropped. No cookies, no "where I came from" header, nothing from the PC is sent.
  - The result is DATA for the model, never instructions (websearch.as_context says so).
Standard library only.
"""
from __future__ import annotations

import codecs
import html.parser
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
import urllib.parse

from . import http as _http

AGENT = "Joe-ai/2 (open-source desktop assistant; reads one page as text)"
MAX_BYTES = 2_000_000          # downloaded
MAX_PARSE = 1_000_000          # characters of HTML looked at (a huge page can't keep the parser busy)
MAX_TEXT = 20_000              # characters kept
PARSE_SECONDS = 5.0            # at most this long picking the words out of one page
TIME_LIMIT = 20.0              # seconds for the whole read, redirects included
MAX_REDIRECTS = 3
PORTS = {80, 443, 8080, 8443}
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
_PRIVATE_NAMES = (".local", ".lan", ".home", ".internal", ".localhost", ".localdomain", ".home.arpa",
                  ".corp", ".intranet", ".private")

last_refusal = ""              # why the last read() returned None (for the log and the tests)


class Refused(Exception):
    pass


# --------------------------------------------------------------------------- the address checks
def public_ip(addr: str) -> bool:
    """An address out on the internet. An IPv4 address hidden in an IPv6 one is judged by the IPv4.
    Any other IPv6 address must be in 2000::/3, the only block the internet hands out: that leaves
    out the old ways of writing an IPv4 address in IPv6 (::127.0.0.1, ::ffff:0:127.0.0.1), the old
    site-local block (fec0::/10) and everything else that was never given out."""
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        inner = ip.ipv4_mapped or ip.sixtofour or (
            ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF) if ip in _NAT64 else None)
        if inner is not None:
            ip = inner
        elif ip not in _V6_INTERNET:
            return False
    return bool(ip.is_global) and not ip.is_multicast


_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_V6_INTERNET = ipaddress.ip_network("2000::/3")


def check_url(url: str) -> urllib.parse.SplitResult:
    """The address, if Joe may read it at all (before looking the name up). Raises Refused."""
    if not isinstance(url, str) or len(url) > 2000 or any(c in url for c in "\r\n\t\x00 "):
        raise Refused("not a plain web address")
    try:
        u = urllib.parse.urlsplit(url)
        port = u.port
    except ValueError:
        raise Refused("not a plain web address") from None
    if u.scheme not in ("http", "https"):
        raise Refused("only http:// and https:// pages")
    if u.username or u.password or "@" in u.netloc:
        raise Refused("addresses with a name and password are refused")
    host = (u.hostname or "").rstrip(".").lower()
    if not host:
        raise Refused("no site name in the address")
    if (443 if u.scheme == "https" else 80) not in PORTS if port is None else port not in PORTS:
        raise Refused("only the usual web ports")
    try:
        ipaddress.ip_address(host.split("%")[0])
        literal = True
    except ValueError:
        literal = False
    if "[" in u.netloc and not literal:
        raise Refused("odd site name")                  # [v1.something]: not an address Joe knows
    if literal:
        if not public_ip(host):
            raise Refused("that address is on this PC or the home network")
    else:
        if host == "localhost" or host.endswith(_PRIVATE_NAMES) or "." not in host:
            raise Refused("that name is on this PC or the home network")
        if not re.fullmatch(r"[a-z0-9.-]+", host) or re.fullmatch(r"(?:0x[0-9a-f]*|[0-9]+)(?:\.(?:0x[0-9a-f]*|[0-9]+))*", host) \
                or re.fullmatch(r"[0-9x]+", host.rsplit(".", 1)[-1]):
            raise Refused("odd site name")              # 0x7f.1, 127.1, 2130706433 and other number tricks
    return u


def _resolve(host: str, port: int) -> str:
    """The one address Joe will connect to: every address the name points at must be public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise Refused("the site's name can't be found") from None
    addrs = [i[4][0] for i in infos]
    if not addrs:
        raise Refused("the site's name can't be found")
    if not all(public_ip(a) for a in addrs):
        raise Refused("that name points at this PC or the home network")
    return addrs[0]


class _Conn(http.client.HTTPConnection):
    """Connects to the address Joe checked, then checks the connection itself before sending."""

    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        _check_peer(sock)
        self.sock = sock


class _TLSConn(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout, context=_http.tls_context())
        self._ip = ip

    def connect(self):
        raw = socket.create_connection((self._ip, self.port), self.timeout)
        _check_peer(raw)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)   # checks the site's certificate


def _check_peer(sock) -> None:
    try:
        ok = public_ip(sock.getpeername()[0])
    except (OSError, IndexError):
        ok = False
    if not ok:
        sock.close()
        raise Refused("the connection reached this PC or the home network")


# --------------------------------------------------------------------------- reading
def read(url: str, time_limit: float = TIME_LIMIT) -> dict | None:
    """{"title", "url" (after redirects), "text"} or None (last_refusal says why). Never raises."""
    global last_refusal
    last_refusal = ""
    try:
        return _read(url, time.monotonic() + max(1.0, time_limit))
    except Refused as e:
        last_refusal = str(e)
    except (OSError, http.client.HTTPException, ssl.SSLError, ValueError) as e:
        last_refusal = f"the page couldn't be read ({type(e).__name__})"
    except Exception as e:                             # noqa: BLE001 (a strange page never stops Joe)
        last_refusal = f"the page couldn't be read ({type(e).__name__})"
    return None


def _cut_off(conn) -> None:
    """The time limit is up: close the connection under a site that drips its answer slowly."""
    try:
        if conn.sock is not None:
            conn.sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def _read(url: str, deadline: float) -> dict:
    for _ in range(MAX_REDIRECTS + 1):
        u = check_url(url)
        left = deadline - time.monotonic()
        if left <= 0:
            raise Refused("it took too long")
        port = u.port or (443 if u.scheme == "https" else 80)
        ip = _resolve(u.hostname, port)
        conn = (_TLSConn if u.scheme == "https" else _Conn)(u.hostname, port, ip, min(left, 10.0))
        timer = threading.Timer(left, _cut_off, [conn])          # a hard stop, however slowly it drips
        timer.daemon = True
        timer.start()
        try:
            path = urllib.parse.quote((u.path or "/") + (f"?{u.query}" if u.query else ""), safe=_URL_SAFE)
            conn.request("GET", path, headers={"User-Agent": AGENT, "Accept": "text/html, text/plain;q=0.9",
                                               "Accept-Encoding": "identity", "Connection": "close"})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.getheader("Location") or ""
                if not loc:
                    raise Refused("a redirect with no address")
                url = urllib.parse.urljoin(url, loc.strip())
                continue
            if resp.status != 200:
                raise Refused(f"the site answered {resp.status}")
            kind = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
            if kind not in TEXT_TYPES:
                raise Refused("not a text page (" + (kind or "unknown kind") + ")")
            enc = (resp.getheader("Content-Encoding") or "identity").strip().lower()
            if enc not in ("", "identity"):
                raise Refused("packed pages are refused")
            size = resp.getheader("Content-Length")
            if size and size.isdigit() and int(size) > MAX_BYTES:
                raise Refused("the page is too big")
            raw = _body(resp, conn, deadline)
            if time.monotonic() > deadline:
                raise Refused("it took too long")
            charset = _charset(resp.getheader("Content-Type") or "", raw)
            text = raw.decode(charset, "replace")[:MAX_PARSE]
            title, words = (extract(text) if kind != "text/plain" else ("", _tidy(text)))
            return {"title": title[:200], "url": url, "text": words[:MAX_TEXT]}
        finally:
            timer.cancel()
            conn.close()
    raise Refused(f"more than {MAX_REDIRECTS} redirects")


_URL_SAFE = "/?&=%:@!$'()*+,;~-._[]"       # letters outside ASCII in an address are sent as %XX


def _body(resp, conn, deadline: float) -> bytes:
    out = bytearray()
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise Refused("it took too long")
        if conn.sock is not None:
            conn.sock.settimeout(min(left, 10.0))
        chunk = resp.read(65536)
        if not chunk:
            return bytes(out)
        out += chunk
        if len(out) > MAX_BYTES:
            raise Refused("the page is too big")


def _charset(ctype: str, raw: bytes) -> str:
    m = re.search(r"charset=[\"']?([\w.-]+)", ctype, re.I) or \
        re.search(rb"<meta[^>]+charset=[\"']?([\w.-]+)", raw[:4096], re.I)
    name = m.group(1) if m else "utf-8"
    name = name.decode("ascii", "replace") if isinstance(name, bytes) else name
    try:
        real = codecs.lookup(name).name                    # Python's own name for it ("iso8859-1")
    except (LookupError, ValueError, TypeError, UnicodeError):
        return "utf-8"
    return real if _CHARSETS.fullmatch(real) else "utf-8"


# The character sets web pages are really written in. Anything else a page claims (rot13, zlib,
# base64, and punycode or idna, which can take minutes on a big page) is read as UTF-8.
_CHARSETS = re.compile(
    r"utf-8|utf-8-sig|utf-16(?:-[lb]e)?|ascii|latin-1|iso8859-\d{1,2}|cp125[0-8]|cp437|cp850|cp866|cp874|cp932|"
    r"cp949|cp950|koi8-[rtu]|mac-(?:roman|cyrillic|greek|latin2|turkish|iceland)|shift_jis(?:_2004|x0213)?|"
    r"euc_jp|euc_jis_2004|euc_jisx0213|iso2022_jp(?:_1|_2|_2004|_3|_ext)?|iso2022_kr|euc_kr|johab|"
    r"gb2312|gbk|gb18030|hz|big5|big5hkscs|tis-620|ptcp154|kz1048")


# --------------------------------------------------------------------------- words from HTML
_SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "object", "canvas", "head",
         "select", "button", "nav", "footer"}
_BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "section",
          "article", "header", "blockquote", "pre", "dd", "dt", "hr", "main", "aside", "figcaption", "form"}
_VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "source", "track", "wbr", "embed",
         "param"}                                      # tags that never have a closing tag
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
_LOOK_BACK = 60                                         # open tags searched for the one a closing tag ends


def _hidden(attrs) -> bool:
    """Marked as not shown: hidden, aria-hidden="true", or style display:none / visibility:hidden.
    (A page can hide words in other ways too, e.g. with its style sheet; those stay, as data.)"""
    for k, v in attrs:
        if k == "hidden" and (v or "").lower() != "until-found":
            return True
        if k == "aria-hidden" and (v or "").strip().lower() == "true":
            return True
        if k == "style" and v and _HIDDEN_STYLE.search(v):
            return True
    return False


class _Words(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0                                  # how many open tags say "don't keep these words"
        self.open: list[tuple[str, bool]] = []         # the open tags: (name, does it hide its words?)
        self.in_title = False
        self.title: list[str] = []
        self.out: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK:
            self.out.append("\n")
        if tag in _VOID:
            return
        if tag == "title":
            self.in_title = True
        hide = tag in _SKIP or _hidden(attrs)
        self.open.append((tag, hide))
        self.skip += hide

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in _BLOCK:
            self.out.append("\n")
        for i in range(len(self.open) - 1, max(-1, len(self.open) - 1 - _LOOK_BACK), -1):
            if self.open[i][0] == tag:                 # closes this one and anything left open inside it
                self.skip -= sum(h for _, h in self.open[i:])
                del self.open[i:]
                break

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        elif not self.skip:
            self.out.append(data)


def extract(page: str) -> tuple[str, str]:
    """(title, the readable words) of an HTML page. Nothing in it is run. A page built to keep the
    parser busy is cut off after PARSE_SECONDS; what was read so far is kept."""
    p = _Words()
    stop = time.monotonic() + PARSE_SECONDS
    try:
        for i in range(0, len(page), 20_000):
            p.feed(page[i:i + 20_000])
            if time.monotonic() > stop:
                break
        else:
            p.close()
    except Exception:                                  # noqa: BLE001 (broken HTML: keep what was read)
        pass
    return _tidy(" ".join(p.title)), _tidy("".join(p.out))


def _tidy(t: str) -> str:
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f​-‏‪-‮⁦-⁩]", " ", t)
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in t.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(ln for ln in lines if ln) if lines else "").strip()
