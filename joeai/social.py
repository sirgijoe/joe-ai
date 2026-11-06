"""Social media posts, ready for a scheduler (EXPORT: social, and the Make shorts tool).

Joe doesn't post anything himself and never asks for your social accounts or keys. He writes
the posts into files that self-hosted schedulers and spreadsheets can take:

- <name>-social.csv   one row per post: text, length, which sites it fits, date/time/site/media
                      columns to fill in (open it in a spreadsheet, or copy into Mixpost/Postiz)
- <name>-social.json  the same posts as plain JSON (for your own scripts)
- <name>-postiz.txt   ready-to-run Postiz command lines (its free 'postiz' helper): put in your
                      channel id and date, then paste them into a terminal
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

# site -> most characters in one post (the common, free-account limits)
LIMITS = {"X": 280, "Bluesky": 300, "Threads": 500, "Mastodon": 500, "Instagram": 2200,
          "TikTok": 2200, "LinkedIn": 3000, "Facebook": 5000}
TEXT_COLS = ("post", "text", "caption", "content", "message", "copy")


def plain(text: str) -> str:
    """Markdown -> what a social site shows (no **, #, [links](url) keep their words)."""
    t = re.sub(r"\[([^\]]+)\]\((?:[^)]+)\)", r"\1", text or "")
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", t)
    t = re.sub(r"(\*\*|__)(.+?)\1", r"\2", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", t)
    t = re.sub(r"(?m)^\s*[-*]\s+", "• ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def fits(text: str) -> str:
    n = len(text)
    return ", ".join(site for site, lim in LIMITS.items() if n <= lim) or "too long for most sites"


def posts_from_markdown(text: str) -> list[dict]:
    from .items import split_items
    out = []
    for it in split_items(text):
        body = plain(it.body)
        if body:
            out.append({"title": plain(it.title), "text": body, "media": []})
    return out


def posts_from_csv(text: str) -> list[dict]:
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        return []
    head = [h.strip().lower() for h in rows[0]]
    col = next((head.index(c) for c in TEXT_COLS if c in head), len(head) - 1)
    out = []
    for r in rows[1:]:
        if len(r) > col and r[col].strip():
            out.append({"title": r[0].strip() if col else "", "text": plain(r[col]), "media": []})
    return out


def write(folder: Path, stem: str, posts: list[dict]) -> list[Path]:
    """The three files for a list of posts ({title, text, media: [file names]})."""
    from .fsutil import atomic_write_text
    if not posts:
        return []
    folder.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["post", "title", "text", "characters", "fits", "date", "time", "site", "media"])
    for n, p in enumerate(posts, 1):
        w.writerow([n, p.get("title", ""), p["text"], len(p["text"]), fits(p["text"]), "", "", "",
                    ";".join(p.get("media") or [])])
    made = []
    f = folder / f"{stem}-social.csv"
    atomic_write_text(f, "\ufeff" + buf.getvalue())          # the BOM keeps emoji right in Excel
    made.append(f)
    f = folder / f"{stem}-social.json"
    atomic_write_text(f, json.dumps({"posts": posts}, ensure_ascii=False, indent=2) + "\n")
    made.append(f)
    lines = ["# Postiz command lines (free 'postiz' helper: npm install -g postiz).",
             "# 1. Set your key once:  export POSTIZ_API_KEY=...   (Windows: set POSTIZ_API_KEY=...)",
             "#    Self-hosted Postiz: also set POSTIZ_API_URL to your own address.",
             "# 2. Find your channel id:  postiz integrations:list",
             "# 3. Replace CHANNEL-ID and the date on each line, then run the lines you want.",
             "# Pictures and videos must be uploaded first: postiz upload <file> (use the path it gives back).",
             "# Joe never posts for you; this file only saves typing.", ""]
    for n, p in enumerate(posts, 1):
        text = p["text"].replace('"', '\\"').replace("\n", "\\n")
        media = p.get("media") or []
        if media:
            lines.append(f"# post {n}: upload first ->  postiz upload \"{media[0]}\"")
        lines.append(f'postiz posts:create -c "{text}" -s "2026-01-01T12:00:00Z" -i "CHANNEL-ID"'
                     + (' -m "UPLOADED-PATH"' if media else ""))
    f = folder / f"{stem}-postiz.txt"
    atomic_write_text(f, "\n".join(lines) + "\n")
    made.append(f)
    return made


def export(out: Path, log=print) -> list[Path]:
    """EXPORT: social for a finished writing task (Markdown list or CSV)."""
    try:
        text = out.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    posts = posts_from_csv(text) if out.suffix.lower() == ".csv" else posts_from_markdown(text)
    if not posts:
        log("  EXPORT social: no posts found in the result.")
        return []
    made = write(out.parent, out.stem, posts)
    long_ones = sum(1 for p in posts if len(p["text"]) > LIMITS["X"])
    log(f"  Social posts: {len(posts)} ready for a scheduler"
        + (f" ({long_ones} are too long for X/Bluesky: the csv says where each one fits)" if long_ones else ""))
    return made
