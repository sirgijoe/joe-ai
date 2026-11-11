"""Fixes from the 2026-11 outside review: each test fails on the old code."""
from __future__ import annotations

import io
import json
import shutil
import sys
import zipfile

import pytest

from joeai import addons, backup, sheets
from joeai.config import Settings
from joeai.sandbox import Sandbox, SandboxError


@pytest.fixture
def sb(tmp_path):
    return Sandbox(tmp_path / "ws").ensure()


# -- 1. exports never pull in a file from outside the document's folder ----------------------
def test_export_text_drops_outside_pictures_and_keeps_own(tmp_path):
    doc = tmp_path / "Output" / "book"
    doc.mkdir(parents=True)
    (doc / "own.png").write_bytes(b"\x89PNG")
    secret = tmp_path / "private.txt"
    secret.write_text("secret")
    text = (f"![a]({secret}) ![b](../../private.txt) ![c](file://{secret}) ![d](https://example.com/x.png)\n"
            f"![e](%2e%2e/%2e%2e/private.txt) ![kept](own.png) [link](https://example.com)\n"
            f"![f][r] ![r]\n\n[r]: {secret}\n[ok]: https://example.com\n")
    out = addons.safe_export_text(text, doc)
    assert "private.txt" not in out and "example.com/x.png" not in out
    assert "![kept](own.png)" in out and "[link](https://example.com)" in out and "[ok]: https://example.com" in out
    assert "![" not in out.replace("![kept](own.png)", "")


@pytest.mark.skipif(not shutil.which("pandoc"), reason="needs pandoc")
def test_exported_copies_hold_no_outside_file_and_no_script(tmp_path):
    doc = tmp_path / "Output" / "d"
    doc.mkdir(parents=True)
    secret = tmp_path / "private.txt"
    secret.write_text("TOP-SECRET-OUTSIDE")
    md = doc / "doc.md"
    md.write_text(f"---\ncss: {secret}\n---\n# T\n\n## One\n\n![x]({secret})\n\n<script>alert(1)</script>\n\n"
                  f'<iframe src="file://{secret}"></iframe>\n\n```{{=html}}\n<iframe src="file://{secret}"></iframe>\n```\n')
    made = addons.export_document(md, ["html", "docx", "epub"], shutil.which("pandoc"), lambda m: None)
    assert {p.suffix for p in made} == {".html", ".docx", ".epub"}
    html = (doc / "doc.html").read_text(encoding="utf-8", errors="replace")
    assert "TOP-SECRET" not in html and "TOP%2DSECRET" not in html and "<iframe" not in html and "<script>alert" not in html
    for ext in ("docx", "epub"):
        z = zipfile.ZipFile(doc / f"doc.{ext}")
        assert not any(b"TOP-SECRET" in z.read(n) for n in z.namelist()), ext


# -- 3. INPUT can't reach Joe's private folders -------------------------------------------------
def test_input_cannot_read_private_folders(sb):
    chat = sb.meta / "chats" / "20261110_101500.json"
    chat.parent.mkdir(parents=True)
    chat.write_text("{}")
    (sb.inbox / "note.txt").write_text("hi")
    (sb.output / "made.md").write_text("hi")
    for bad in ("Output/.joe/chats/20261110_101500.json", "Output/.joe", ".hidden/x.txt"):
        with pytest.raises(SandboxError):
            sb.resolve_input(bad)
    assert sb.resolve_input("note.txt") == sb.inbox / "note.txt"
    assert sb.resolve_input("Output/made.md") == sb.output / "made.md"       # chaining tools still works


def test_tool_folder_input_skips_private_files(sb, monkeypatch):
    from types import SimpleNamespace
    from joeai import tools
    (sb.output / ".joe").mkdir(parents=True, exist_ok=True)
    (sb.output / ".joe" / "state.txt").write_text("private")
    (sb.output / "ok.txt").write_text("fine")
    job = SimpleNamespace(type="summarize", inputs=["Output"])
    files, _ = tools.resolve_inputs(SimpleNamespace(sb=sb), job)
    assert [f.name for f in files] == ["ok.txt"]


# -- 5. a backup can't point Joe at another machine or turn Joe Phone on -----------------------
def _backup_zip(settings: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps({"kind": backup.MARK, "joe": "2.1.2", "made": "2026-11-10T10:00:00"}))
        z.writestr("settings.json", json.dumps(settings))
    return buf.getvalue()


def test_restore_keeps_ai_addresses_local_and_phone_off(sb):
    s = Settings()
    r = backup.restore(s, sb, _backup_zip({"ollama": {"url": "http://evil.example:11434", "engine_url": "http://10.0.0.9:1234"},
                                           "comfy": {"url": "https://evil.example"}, "phone": {"enabled": True, "port": 9000},
                                           "ui": {"text_size": 30}}))
    assert s.ollama.url == "http://127.0.0.1:11434" and s.ollama.engine_url == "" and s.comfy.url == "http://127.0.0.1:8000"
    assert s.phone.enabled is False and s.ui.text_size == 30                 # ordinary settings still come back
    assert set(r["skipped"]) == {"ollama.url", "ollama.engine_url", "comfy.url", "phone.enabled"}
    s2 = Settings()
    backup.restore(s2, sb, _backup_zip({"ollama": {"url": "http://localhost:11500"}, "comfy": {"url": "http://127.0.0.1:8188"}}))
    assert s2.ollama.url == "http://localhost:11500" and s2.comfy.url == "http://127.0.0.1:8188"   # your own PC's: kept


# -- 7. a start line with a path in its options -------------------------------------------------
def test_comfy_start_folder_is_the_programs_folder(tmp_path):
    from pathlib import Path
    from joeai.finder import find_comfy
    inst = find_comfy(f'"{sys.executable}" -s {tmp_path / "ComfyUI" / "main.py"} --port 8188')
    assert inst is not None and Path(inst.cwd) == Path(sys.executable).parent


# -- 9. a tiny spreadsheet that unpacks to gigabytes --------------------------------------------
def test_xlsx_zip_bomb_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(sheets, "MAX_PART_BYTES", 1_000_000)
    p = tmp_path / "bomb.xlsx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/sharedStrings.xml", b"<sst>" + b" " * 3_000_000 + b"</sst>")
        z.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(sheets.SheetError, match="unpacks"):
        sheets.read_xlsx(p)


# -- 6 / 14. the window: no framing, no key in the page ----------------------------------------
def test_window_page_cannot_be_framed(tmp_path, monkeypatch):
    import threading
    import urllib.request
    from joeai.server import App, serve
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = s.comfy.url = "http://127.0.0.1:9"
    app = App(settings=s)
    httpd = serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_address[1]}/", timeout=5) as r:
            body = r.read()
            assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"] and r.headers["X-Frame-Options"] == "DENY"
        assert app.token.encode() not in body
    finally:
        httpd.shutdown()


# -- updates on a PC whose Python certificate list is out of date -------------------------------
def test_update_falls_back_to_curl_on_certificate_errors(tmp_path, monkeypatch):
    import hashlib
    import ssl
    import urllib.error
    from joeai import sign, update
    from joeai.http import HttpError
    seed = bytes(range(32))
    monkeypatch.setattr("joeai.SIGN_PUBLIC_KEY", sign.b64(sign.public_key(seed)))
    monkeypatch.setattr(update, "updates_dir", lambda: tmp_path)
    body = b"installer-bytes" * 1000
    name = "Joe-Setup-9.9.9-windows-x64.exe"
    sums = f"{hashlib.sha256(body).hexdigest()}  {name}\n".encode()
    files = {"https://x/" + name: body, "https://x/SHA256SUMS.txt": sums,
             "https://x/SHA256SUMS.txt.sig": sign.sign_file_text(sign.b64(seed), sums).encode()}
    used = []

    def bad_cert(*a, **k):
        raise urllib.error.URLError(ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"))

    def fake_curl(url, dest=None, timeout=60, headers=None):
        used.append(url)
        if dest is not None:
            dest.write_bytes(files[url])
            return b""
        return files[url]

    monkeypatch.setattr(update, "_curl", fake_curl)
    info = {"asset": {"name": name, "url": "https://x/" + name, "size": len(body)},
            "sums": "https://x/SHA256SUMS.txt", "sig": "https://x/SHA256SUMS.txt.sig"}
    log = []
    got = update.download(info, log.append, opener=bad_cert)
    assert got is not None and got.read_bytes() == body and len(used) == 3, log
    files["https://x/" + name] = body + b"tampered"                 # the checks still bite with curl
    assert update.download(info, log.append, opener=bad_cert) is None

    def no_net(*a, **k):                                             # any other error: no curl, plain message
        raise OSError("network is down")
    used.clear()
    assert update.download(info, log.append, opener=no_net) is None and not used

    def cert_fetch(*a, **k):
        raise HttpError("can't reach https://api.github.com: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    monkeypatch.setattr(update, "_curl", lambda url, **k: b'{"tag_name": "v9.9.9", "assets": []}')
    update._CACHE.clear()
    r = update.check(force=True, fetch=cert_fetch)
    assert r["ok"] and r["newer"] and r["latest"] == "9.9.9"
    update._CACHE.clear()
