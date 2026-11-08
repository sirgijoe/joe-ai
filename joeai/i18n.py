"""Joe's own screens in other languages (Setup > Display & sound > Language).

How it works:
- The window is written in English. A language file maps English screen text to the other
  language: {"Joe Phone on": "Joe Phone activado", "Queued: {1}": "En cola: {1}", ...}.
  The window swaps each piece of text it finds (and tooltips and box hints); anything not in the
  file stays English, so a half-made language still works.
- Built-in files live in joeai/lang/<code>.json. Files Joe makes (or you edit) live in
  <Joe's folder>/Languages/<code>.json and win over the built-in ones, line by line.
- MAKE IT (Setup) queues the 'joe-language' task: Joe collects every English line from his own
  window (extract()) and the writing model translates them in small numbered batches, keeping the
  {1} placeholders and [ BRACKETS ]. It saves as it goes, so a stopped run carries on next time.
"""
from __future__ import annotations

import html.parser
import json
import re
from datetime import datetime
from pathlib import Path

from .fsutil import atomic_write_text

UI = Path(__file__).with_name("ui")
BUILTIN = Path(__file__).with_name("lang")
# code -> (name in English, name in that language)
LANGUAGES = {"en": ("English", "English"), "es": ("Spanish", "Español"), "fr": ("French", "Français"),
             "de": ("German", "Deutsch"), "pt": ("Portuguese", "Português"), "it": ("Italian", "Italiano"),
             "nl": ("Dutch", "Nederlands"), "pl": ("Polish", "Polski"), "ru": ("Russian", "Русский"),
             "uk": ("Ukrainian", "Українська"), "tr": ("Turkish", "Türkçe"), "ar": ("Arabic", "العربية"),
             "hi": ("Hindi", "हिन्दी"), "zh": ("Chinese", "中文"), "ja": ("Japanese", "日本語"),
             "ko": ("Korean", "한국어"), "vi": ("Vietnamese", "Tiếng Việt"), "id": ("Indonesian", "Bahasa Indonesia"),
             "tl": ("Tagalog", "Tagalog"), "sw": ("Swahili", "Kiswahili"), "el": ("Greek", "Ελληνικά"),
             "he": ("Hebrew", "עברית"), "bn": ("Bengali", "বাংলা"), "th": ("Thai", "ไทย")}
RTL = ("ar", "he")
BATCH = 30


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _wordy(t: str) -> bool:
    """Screen text, not code: has letters, isn't a path, an id, a CSS rule or a key name."""
    if len(t) < 2 or len(t) > 900 or not re.search(r"[A-Za-z]{2}", t):
        return False
    if re.match(r"^[#./]|^https?://|^[a-z0-9_-]+$|^[A-Z][a-z]+[A-Z]\w*$|^[a-z]+/[a-z0-9.+-]+$", t):   # ids, paths, camelCase, mime types
        return False
    if re.search(r"[{};]\s*$|=>|\bfunction\b|\bconst\b|\bdocument\.|\bclassName\b|^\w+\(|\(\)|^\[data-|^\.[a-z]", t):
        return False
    if re.fullmatch(r"[A-Z0-9_]+", t) and len(t) > 12:                           # CONSTANT_NAMES
        return False
    if " " not in t and re.fullmatch(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)+", t) and re.search(r"[A-Z]", t[1:]):
        return False                                                            # X-NR-Token, Content-Type
    if re.search(r"\+=|querySelector|\s>\s[.#a-z]|===|!==|&&|\|\||^\w+\s*\+=|\bfield\(", t):
        return False
    return True


class _HTML(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        for k, v in attrs:
            if k in ("title", "placeholder", "aria-label", "data-title") and v and _wordy(norm(v)):
                self.out.append(norm(v))

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        t = norm(data)
        if not self.skip and t and _wordy(t):
            self.out.append(t)


_JS_STR = re.compile(r"`(?:\\.|[^`\\])*`|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'")


def _js_text(src: str) -> list[str]:
    """Screen text from the window's script: string pieces between tags, ${...} turned into {1}, {2}..."""
    out = []
    for m in _JS_STR.finditer(src):
        s = m.group(0)
        q, body = s[0], s[1:-1]
        if q == "`":
            n = 0

            def ph(_):
                nonlocal n
                n += 1
                return "{" + str(n) + "}"
            body = _replace_expr(body, ph)
        body = body.replace("\\n", "\n").replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
        for piece in re.split(r"<[^>]*>", body):
            for line in piece.split("\n"):
                t = norm(line)
                if t and _wordy(t) and not re.fullmatch(r"(\{\d+\}\s*)+", t) and "${" not in t:
                    out.append(t)
    return out


def _replace_expr(body: str, ph) -> str:
    """`${...}` (with nested braces) -> ph()."""
    res, i = [], 0
    while i < len(body):
        if body.startswith("${", i):
            depth, j = 1, i + 2
            while j < len(body) and depth:
                depth += {"{": 1, "}": -1}.get(body[j], 0)
                j += 1
            res.append(ph(None))
            i = j
        else:
            res.append(body[i])
            i += 1
    return "".join(res)


def extract() -> list[str]:
    """Every English line in Joe's window (index.html and app.js), each once, in order."""
    p = _HTML()
    p.feed((UI / "index.html").read_text(encoding="utf-8"))
    found = p.out + _js_text((UI / "app.js").read_text(encoding="utf-8"))
    seen, out = set(), []
    for t in found:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _user_dir(sb) -> Path:
    return sb.root / "Languages"


def load(code: str, sb=None) -> dict:
    """The language's lines: built-in first, then the person's/Joe's own file on top."""
    code = (code or "en").lower()
    if code == "en" or code not in LANGUAGES:
        return {}
    out: dict = {}
    for p in [BUILTIN / f"{code}.json"] + ([_user_dir(sb) / f"{code}.json"] if sb is not None else []):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict):
            out.update({norm(k): str(v) for k, v in d.items() if isinstance(k, str) and isinstance(v, (str, int, float))
                        and not k.startswith("_") and str(v).strip()})
    return out


def coverage(code: str, sb=None) -> dict:
    lines = extract()
    have = load(code, sb)
    done = sum(1 for t in lines if t in have)
    return {"code": code, "done": done, "total": len(lines), "pct": round(100 * done / max(1, len(lines)))}


def choices(sb=None) -> list[dict]:
    out = []
    for code, (en, own) in LANGUAGES.items():
        if code == "en":
            out.append({"code": code, "name": own, "pct": 100})
            continue
        n = len(load(code, sb))
        out.append({"code": code, "name": f"{own} ({en})", "pct": coverage(code, sb)["pct"] if n else 0})
    return out


# --------------------------------------------------------------------------- Joe translates himself
SYSTEM = ("You translate the screen text of a friendly desktop app called Joe. Short, plain, everyday words, "
          "like the app talks to a person who isn't technical. Keep {1}, {2}... exactly as they are, keep "
          "[ BRACKETS ] and keyboard keys (F1, F5, Ctrl) and names (Joe, Ollama, ComfyUI, FFmpeg, GitHub) as they are. "
          "Keep capital-letter words in capitals. Reply with ONLY the numbered lines.")
ASK = "Translate each numbered line into {lang}. Reply with the same numbers, one line each, like '3| text'.\n\n{lines}"


def _placeholders_ok(src: str, dst: str) -> bool:
    return sorted(re.findall(r"\{\d+\}", src)) == sorted(re.findall(r"\{\d+\}", dst))


def run(engine, mission, job, st):
    """The 'joe-language' task: translate every line of Joe's window into OPTIONS: to <language>."""
    from .avtools import parse_numbered
    from .tools import _finish, option_value
    lang = option_value(job, "to")
    code = next((c for c, (en, _o) in LANGUAGES.items() if en.lower() == lang), "")
    if not code or code == "en":
        st.status, st.note = "failed", "pick the language for Joe's screens (OPTIONS: to spanish)"
        engine.log(f"'{job.name}' failed: {st.note}")
        engine._save_state(job, st)
        return st
    if not engine._text_ready(st):
        engine._save_state(job, st)
        return st
    out = _user_dir(engine.sb) / f"{code}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        mine = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        mine = {}
    have = load(code, engine.sb)
    todo = [t for t in extract() if t not in have]
    st.output = str(out.relative_to(engine.sb.root)).replace("\\", "/")
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    st.parts_total = max(1, (len(todo) + BATCH - 1) // BATCH)
    engine._save_state(job, st)
    engine.log(f"Starting '{job.name}': {len(todo)} lines of Joe's screens into {LANGUAGES[code][0]} -> {st.output}")
    failed: list[str] = []
    from .engine import Stopped
    try:
        for part in range(st.parts_total):
            if engine.stop.is_set():
                raise Stopped()
            chunk = todo[part * BATCH:(part + 1) * BATCH]
            if not chunk:
                break
            engine._progress(f"{job.name}: part {part + 1}/{st.parts_total}")
            lines = "\n".join(f"{i}| {t}" for i, t in enumerate(chunk, 1))
            try:
                r = engine._chat(job, part, "translate", SYSTEM, ASK.format(lang=LANGUAGES[code][0], lines=lines), st)
            except Exception as e:                        # noqa: BLE001 (one batch failing doesn't end the job)
                failed.append(f"part {part + 1}: {e}"[:160])
                continue
            got = parse_numbered(r.text, len(chunk))
            kept = 0
            for i, src in enumerate(chunk, 1):
                dst = norm(got.get(i, ""))
                if dst and _placeholders_ok(src, dst):
                    mine[src] = dst
                    kept += 1
            mine["_about"] = (f"Joe's screens in {LANGUAGES[code][0]}, drafted by Joe's writing model. Edit any line: "
                              "the left side is the English, the right side what Joe shows.")
            atomic_write_text(out, json.dumps(mine, ensure_ascii=False, indent=1))
            st.parts_done = part + 1
            st.items += kept
            st.titles.append(f"part {part + 1}")
            engine._save_state(job, st)
            engine.log(f"  part {part + 1}/{st.parts_total}: {kept}/{len(chunk)} lines")
    except Stopped:
        st.status, st.note = "stopped", f"stopped after part {st.parts_done} (MAKE IT again carries on)"
        engine._save_state(job, st)
        return st
    st.media_files = []
    return _finish(engine, job, st, len(st.titles) + len(failed), failed)
