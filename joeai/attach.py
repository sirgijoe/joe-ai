"""Files dropped into Talk (F4): copied into Inbox\\dropped\\, then turned into text Joe can
read aloud or think about. Pictures go to a vision model if one is installed in Ollama.

Text extraction uses only the standard library (txt, md, csv, json, html, docx). PDFs use the
voice add-on's private Python (pypdf is added there on first use), so Joe himself stays
dependency-free.
"""
from __future__ import annotations

import base64
import html
import json
import re
import subprocess
import zipfile
from pathlib import Path


TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".ini", ".yaml", ".yml",
            ".py", ".js", ".ts", ".cs", ".cpp", ".h", ".css", ".xml", ".srt", ".vtt"}
HTML_EXT = {".html", ".htm"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MAX_BYTES = 25_000_000
MAX_TEXT = 60_000                    # characters kept per file
VISION_HINT = re.compile(r"llava|vision|-vl|vl:|qwen2\.5vl|qwen2-vl|gemma3|minicpm-v|moondream|bakllava|granite3\.2-vision|mistral-small3", re.I)
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name: str) -> str:
    name = _BAD.sub("_", Path(name or "file").name).strip(" .") or "file"
    return name[:120]


def save_drop(sb, name: str, data: bytes) -> Path:
    """Copy a dropped file into Inbox/dropped/ (never overwrites)."""
    if len(data) > MAX_BYTES:
        raise ValueError("That file is over 25 MB.")
    folder = sb.inbox / "dropped"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / safe_name(name)
    stem, ext, n = target.stem, target.suffix, 2
    while target.exists():
        target = folder / f"{stem}_{n}{ext}"
        n += 1
    sb.check(target)
    target.write_bytes(data)
    return target


def _docx_text(p: Path) -> str:
    with zipfile.ZipFile(p) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def _html_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</li>|</div>", "\n", raw)
    return html.unescape(re.sub(r"<[^>]+>", "", raw))


def _pdf_text(p: Path, log) -> str:
    from . import addons
    if not addons.voice_python().exists():
        raise ValueError("Reading PDFs needs Joe's voice add-on (F10 > System check), or save it as .txt/.docx.")
    py = str(addons.voice_python())
    code = ("import sys,pypdf;r=pypdf.PdfReader(sys.argv[1]);"
            "sys.stdout.reconfigure(encoding='utf-8');"
            "print('\\n\\n'.join((pg.extract_text() or '') for pg in r.pages[:200]))")
    run = lambda: subprocess.run([py, "-I", "-c", code, str(p)], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=180,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    r = run()
    if r.returncode != 0 and "No module named 'pypdf'" in (r.stderr or ""):
        uv = addons.uv_exe()
        if not uv:
            raise ValueError("Couldn't add the PDF reader (uv not found).")
        log("Adding the PDF reader to Joe's voice add-on (one time)...")
        addons._run([uv, "pip", "install", "--python", py, "pypdf"], log, 600)
        r = run()
    if r.returncode != 0:
        last = (r.stderr or "").strip().splitlines()
        raise ValueError("Couldn't read that PDF" + (f": {last[-1][:200]}" if last else "."))
    return r.stdout


def extract(p: Path, log=print, limit: int = MAX_TEXT) -> dict:
    """{'kind': 'text'|'image', 'text': ..., 'image_b64': ...}. `limit` = characters kept
    (tools that read whole documents pass a bigger one)."""
    ext = p.suffix.lower()
    if ext in IMAGE_EXT:
        return {"kind": "image", "text": "", "image_b64": base64.b64encode(p.read_bytes()).decode()}
    if ext in TEXT_EXT:
        text = p.read_bytes().decode("utf-8", "replace")
        if ext == ".json":
            try:
                text = json.dumps(json.loads(text), indent=1)[:limit]
            except ValueError:
                pass
    elif ext in HTML_EXT:
        text = _html_text(p.read_text(encoding="utf-8", errors="replace"))
    elif ext == ".docx":
        try:
            text = _docx_text(p)
        except (KeyError, zipfile.BadZipFile) as e:
            raise ValueError(f"Couldn't open that Word file: {e}") from e
    elif ext == ".pdf":
        text = _pdf_text(p, log)
    else:
        head = p.read_bytes()[:4096]
        if b"\x00" in head:
            raise ValueError(f"Joe can't read {ext or 'that kind of'} files yet. Text, Word, PDF, web pages "
                             "and pictures work.")
        text = p.read_bytes().decode("utf-8", "replace")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise ValueError("That file doesn't have any text Joe can read (is it a scan?).")
    return {"kind": "text", "text": text[:limit], "truncated": len(text) > limit}


def vision_model(models: list[dict]) -> str | None:
    """An installed Ollama model that can look at pictures, if any."""
    for m in models:
        if VISION_HINT.search(m["name"]):
            return m["name"]
    return None
