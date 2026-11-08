"""Everyday file helpers on the Tools tab (2.1):

- calendar-file: dates and to-dos pulled out of notes, emails or a transcript into a calendar file
  (.ics) any calendar app imports. Joe never touches anyone's calendar account.
- sort-files: documents sorted into folders with clear names (copies; the originals stay put).
- ask-sheet: questions about a spreadsheet answered by Joe's own math. The writing model only turns
  the question into a plan ("add up Price where Category is Mugs"); Joe's code does the counting,
  so the numbers are always right, and the answer shows how it was worked out.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from .fsutil import atomic_write_text

if TYPE_CHECKING:
    from .engine import Engine, JobState
    from .mission import Job, Mission

FILE_TOOLS = ("calendar-file", "sort-files", "ask-sheet")


def _json(raw: str):
    t = re.sub(r"(?s)<think>.*?</think>", "", raw or "")
    t = re.sub(r"```[\w-]*", "", t)
    for a, b in (("{", "}"), ("[", "]")):
        i, j = t.find(a), t.rfind(b)
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                continue
    return None


# --------------------------------------------------------------------------- calendar file
CAL_SYSTEM = ("You pull dates out of the person's notes for their calendar. Only dates and times the text "
              "actually gives (or clearly means, like 'next Friday' counted from today). Never invent a date, "
              "time or place. Reply with ONLY JSON.")
CAL_ASK = ('Today is {today} ({weekday}). From the text below, reply with ONLY JSON: {{"events": [{{"title": "", '
           '"date": "YYYY-MM-DD", "start": "HH:MM or empty for all day", "end": "HH:MM or empty", "place": "", '
           '"notes": "", "sure": true}}], "todos": [{{"task": "", "due": "YYYY-MM-DD or empty", "who": ""}}]}}. '
           'sure = false when the date or time is a guess. Nothing found: empty lists.\n\n<<<\n{text}\n>>>')


def _d(v) -> date | None:
    try:
        return datetime.strptime(str(v).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _t(v) -> tuple[int, int] | None:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", str(v or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return int(m.group(1)), int(m.group(2))


def ics_escape(s: str) -> str:
    return (str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "")
            .replace("\n", "\\n"))


def _fold(line: str) -> str:
    """iCalendar lines longer than 75 bytes are folded (RFC 5545)."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > 74:
            out.append(cur)
            cur = " " + ch
        else:
            cur += ch
    return "\r\n".join(out + [cur])


def build_ics(events: list[dict], todos: list[dict], stamp: datetime | None = None) -> tuple[str, list[str]]:
    """(the .ics text, problems). Times are the computer's local time ("floating"), which is what
    a person means by "3pm". Events or to-dos with a date that doesn't parse are left out and listed."""
    import uuid
    now = (stamp or datetime.now()).strftime("%Y%m%dT%H%M%S")
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//joe-ai//Joe//EN", "CALSCALE:GREGORIAN"]
    problems = []
    for e in events:
        d = _d(e.get("date"))
        title = str(e.get("title") or "").strip() or "Event"
        if not d:
            problems.append(f"{title}: no clear date")
            continue
        if not e.get("sure", True):
            title += " [CHECK]"
        L += ["BEGIN:VEVENT", f"UID:{uuid.uuid4()}@joe-ai", f"DTSTAMP:{now}", f"SUMMARY:{ics_escape(title)}"]
        st, en = _t(e.get("start")), _t(e.get("end"))
        if st:
            begin = datetime(d.year, d.month, d.day, *st)
            finish = datetime(d.year, d.month, d.day, *en) if en else begin + timedelta(hours=1)
            if finish <= begin:
                finish = begin + timedelta(hours=1)
            L += [f"DTSTART:{begin:%Y%m%dT%H%M%S}", f"DTEND:{finish:%Y%m%dT%H%M%S}"]
        else:
            L += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}"]
        if str(e.get("place") or "").strip():
            L.append(f"LOCATION:{ics_escape(e['place'])}")
        if str(e.get("notes") or "").strip():
            L.append(f"DESCRIPTION:{ics_escape(e['notes'])}")
        L.append("END:VEVENT")
    for t in todos:
        task = str(t.get("task") or "").strip()
        if not task:
            continue
        who = str(t.get("who") or "").strip()
        L += ["BEGIN:VTODO", f"UID:{uuid.uuid4()}@joe-ai", f"DTSTAMP:{now}",
              f"SUMMARY:{ics_escape(task + (f' ({who})' if who else ''))}"]
        d = _d(t.get("due"))
        if d:
            L.append(f"DUE;VALUE=DATE:{d:%Y%m%d}")
        L += ["STATUS:NEEDS-ACTION", "END:VTODO"]
    L.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in L) + "\r\n", problems


# --------------------------------------------------------------------------- sort files
SORT_SYSTEM = ("You sort the person's documents. Use only what the document shows. Never invent names or dates. "
               "Reply with ONLY JSON.")
SORT_ASK = ('Document file name: {name}\nStart of the document:\n<<<\n{text}\n>>>\n\n{cats}Reply with ONLY JSON: '
            '{{"category": "short folder name", "title": "a clear 3-8 word name for the file", '
            '"date": "YYYY-MM-DD if the document has its own date (a bill date, letter date), else empty"}}')
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(s: str, n: int = 80) -> str:
    s = _BAD.sub(" ", str(s or "")).strip().strip(".")
    return re.sub(r"\s+", " ", s)[:n].strip() or "Document"


# --------------------------------------------------------------------------- ask my spreadsheet
SHEET_SYSTEM = ("You turn a question about a spreadsheet into a plan for a calculator. You never do the math "
                "yourself. Use the exact column names given. Reply with ONLY JSON.")
SHEET_ASK = ('Columns: {cols}\nFirst rows (as JSON):\n{sample}\n\nQuestion: {q}\n\nReply with ONLY JSON: '
             '{{"op": "sum|average|count|min|max|list", "column": "the number column (empty for count/list)", '
             '"group_by": "a column to split by, or empty", "filters": [{{"column": "", "is": "=|!=|>|<|>=|<=|contains|'
             'year|month", "value": ""}}], "sort": "desc|asc|", "limit": 0, "chart": true}}. '
             'month value = YYYY-MM. If the sheet can\'t answer it, {{"op": "none", "why": "..."}}.')
OPS = ("sum", "average", "count", "min", "max", "list")


def number(v: str) -> float | None:
    t = str(v or "").strip().replace(",", "").replace("$", "").replace("£", "").replace("€", "").replace("%", "")
    if t.startswith("(") and t.endswith(")"):
        t = "-" + t[1:-1]
    try:
        return float(t)
    except ValueError:
        return None


def _when(v: str) -> date | None:
    v = str(v or "").strip()
    for cand in (v, v[:10], v.split(" ")[0]):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d.%m.%Y", "%Y/%m/%d", "%b %d, %Y", "%d %b %Y"):
            try:
                return datetime.strptime(cand, fmt).date()
            except ValueError:
                continue
    return None


def _col(header: list[str], name: str) -> int | None:
    name = str(name or "").strip().lower()
    for i, h in enumerate(header):
        if h.strip().lower() == name:
            return i
    return None


def run_query(header: list[str], rows: list[list[str]], plan: dict) -> dict:
    """Joe's own math for a plan. Returns {"rows": [(label, value)], "how": "...", "skipped": n} or
    {"error": ...}. Never guesses: unknown columns or no numbers are errors."""
    op = str(plan.get("op") or "").lower()
    if op == "none":
        return {"error": str(plan.get("why") or "the spreadsheet doesn't have what that needs")}
    if op not in OPS:
        return {"error": f"unknown kind of answer '{op}'"}
    vi = _col(header, plan.get("column", "")) if op not in ("count", "list") else None
    if op not in ("count", "list") and vi is None:
        return {"error": f"there's no column called '{plan.get('column', '')}'"}
    gi = _col(header, plan.get("group_by", "")) if str(plan.get("group_by") or "").strip() else None
    if str(plan.get("group_by") or "").strip() and gi is None:
        return {"error": f"there's no column called '{plan.get('group_by')}'"}
    how = []
    keep = rows
    for f in plan.get("filters") or []:
        ci = _col(header, f.get("column", ""))
        if ci is None:
            return {"error": f"there's no column called '{f.get('column', '')}'"}
        rel, val = str(f.get("is") or "=").strip(), str(f.get("value") or "").strip()

        def ok(cell: str, rel=rel, val=val) -> bool:
            c = cell.strip()
            if rel == "contains":
                return val.lower() in c.lower()
            if rel in ("year", "month"):
                d = _when(c)
                return bool(d) and (str(d.year) == val[:4] if rel == "year" else f"{d:%Y-%m}" == val[:7])
            a, b = number(c), number(val)
            if rel in (">", "<", ">=", "<=") and a is not None and b is not None:
                return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[rel]
            if rel == "!=":
                return c.lower() != val.lower()
            return c.lower() == val.lower()
        keep = [r for r in keep if ci < len(r) and ok(r[ci])]
        how.append(f"{header[ci]} {rel} {val}")
    groups: dict[str, list[list[str]]] = {}
    for r in keep:
        groups.setdefault(r[gi].strip() if gi is not None and gi < len(r) else "All", []).append(r)
    out, skipped = [], 0
    if op == "list":
        lim = int(plan.get("limit") or 50)
        return {"list": [dict(zip(header, r)) for r in keep[:lim]], "how": _how(op, None, None, how, header),
                "skipped": 0, "total_rows": len(keep)}
    for g, rs in groups.items():
        if op == "count":
            out.append((g, float(len(rs))))
            continue
        nums = [number(r[vi]) if vi < len(r) else None for r in rs]
        vals = [x for x in nums if x is not None]
        skipped += len(nums) - len(vals)
        if not vals:
            continue
        v = {"sum": sum(vals), "average": sum(vals) / len(vals), "min": min(vals), "max": max(vals)}[op]
        out.append((g, round(v, 4)))
    if str(plan.get("sort") or "") in ("desc", "asc"):
        out.sort(key=lambda x: x[1], reverse=plan.get("sort") == "desc")
    lim = int(plan.get("limit") or 0)
    if lim > 0:
        out = out[:lim]
    if not out:
        return {"error": "no rows matched (or the column has no numbers)"}
    return {"rows": out, "how": _how(op, header[vi] if vi is not None else None,
                                     header[gi] if gi is not None else None, how, header),
            "skipped": skipped, "matched": len(keep)}


def _how(op, col, grp, filters, header) -> str:
    what = {"sum": f"added up {col}", "average": f"took the average of {col}", "count": "counted the rows",
            "min": f"found the smallest {col}", "max": f"found the largest {col}", "list": "listed the rows"}[op]
    return what + (f" for each {grp}" if grp else "") + (" where " + " and ".join(filters) if filters else "")


def fmt(v: float) -> str:
    return f"{int(v):,}" if float(v).is_integer() else f"{v:,.2f}"


def bar_svg(rows: list[tuple[str, float]], title: str) -> str:
    """A plain bar chart (SVG) made by Joe's code from the same numbers as the answer."""
    from xml.sax.saxutils import escape
    rows = rows[:20]
    top = max((abs(v) for _, v in rows), default=1) or 1
    bh, gap, left, width = 26, 8, 180, 760
    h = 50 + len(rows) * (bh + gap)
    L = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h}" font-family="sans-serif" font-size="14">',
         '<rect width="100%" height="100%" fill="white"/>',
         f'<text x="10" y="28" font-size="16" font-weight="bold">{escape(title[:90])}</text>']
    for i, (lbl, v) in enumerate(rows):
        y = 45 + i * (bh + gap)
        w = int((width - left - 110) * abs(v) / top)
        L += [f'<text x="{left - 8}" y="{y + 18}" text-anchor="end">{escape(str(lbl)[:24])}</text>',
              f'<rect x="{left}" y="{y}" width="{max(w, 1)}" height="{bh}" fill="#2d6a8f"/>',
              f'<text x="{left + w + 6}" y="{y + 18}">{escape(fmt(v))}</text>']
    return "\n".join(L + ["</svg>"]) + "\n"


# --------------------------------------------------------------------------- run
def run(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .engine import PartFailed, Stopped
    from .tools import TOOLS, _finish, _key, _no_files, resolve_inputs, tool_dir, unique_stem
    tid = job.type
    if (bad := _no_files(engine, job, st, "files to work on")) is not None:
        return bad
    files, _ = resolve_inputs(engine, job)
    if tid == "ask-sheet" and not job.format.strip():
        st.status, st.note = "failed", "type your question(s) about the spreadsheet in the box"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    if not engine._text_ready(st):
        engine._save_state(job, st)
        return st
    folder = tool_dir(engine, job, st)
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}' ({TOOLS[tid].name}) -> {st.output}")
    rules = ("\n" + job.rules.strip()) if job.rules.strip() else ""
    part = [0]

    def ask(kind: str, system: str, prompt: str):
        for attempt in range(2):
            if engine.stop.is_set():
                raise Stopped()
            r = engine._chat(job, part[0], kind, system + rules, prompt + ("\n\nReply with ONLY the JSON." if attempt else ""), st)
            part[0] += 1
            got = _json(r.text)
            if got is not None:
                return got
            st.retries += 1
        return None

    failed: list[str] = []
    try:
        if tid == "calendar-file":
            total = 1
            if not st.titles:
                _calendar(engine, job, st, files, ask, folder, failed)
                st.titles.append("calendar")
        elif tid == "sort-files":
            total = len(files)
            _sort(engine, job, st, files, ask, folder, failed)
        else:
            total = len(files)
            for i, src in enumerate(files):
                if _key(engine, src) in st.titles:
                    continue
                try:
                    _sheet(engine, job, st, src, unique_stem(files, i), ask, folder)
                except RuntimeError as e:
                    failed.append(f"{src.name}: {e}"[:200])
                    engine.log(f"  {src.name}: {e}")
                    continue
                st.titles.append(_key(engine, src))
                st.items += 1
                engine._save_state(job, st)
    except PartFailed as e:
        failed.append(str(e)[:200])
        total = max(1, len(files))
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} file(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    return _finish(engine, job, st, total, failed)


def _calendar(engine, job, st, files, ask, folder: Path, failed: list[str]) -> None:
    from .tools import document_text, proof_chunks
    today = date.today()
    events, todos = [], []
    for src in files:
        try:
            text = document_text(src, engine.log)
        except (ValueError, OSError) as e:
            failed.append(f"{src.name}: {e}"[:200])
            continue
        for piece in proof_chunks(text, 2500):
            if not piece.strip():
                continue
            got = ask("calendar", CAL_SYSTEM, CAL_ASK.format(today=today.isoformat(), weekday=today.strftime("%A"),
                                                            text=piece.strip()))
            if isinstance(got, dict):
                events += [e for e in (got.get("events") or []) if isinstance(e, dict)]
                todos += [t for t in (got.get("todos") or []) if isinstance(t, dict)]
    seen, uniq = set(), []
    for e in events:                                     # the same meeting found in two parts: once
        k = (str(e.get("title", "")).lower().strip(), str(e.get("date", "")), str(e.get("start", "")))
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    text, problems = build_ics(uniq, todos)
    atomic_write_text(folder / "calendar.ics", text)
    L = ["# Dates and to-dos", "", "Open **calendar.ics** (double-click, or import it in Google Calendar, Outlook or "
         "Apple Calendar) to add them. Joe doesn't touch your calendar account. Check anything marked [CHECK].", ""]
    good = [e for e in uniq if _d(e.get("date"))]
    if good:
        L += ["## Events", ""] + [f"- {e.get('date')} {e.get('start') or '(all day)'}: {e.get('title', '')}"
                                  + ("" if e.get("sure", True) else " [CHECK]") for e in sorted(good, key=lambda x: str(x.get("date")))]
        L.append("")
    if todos:
        L += ["## To-dos", ""] + [f"- {t.get('task', '')}" + (f" (due {t['due']})" if _d(t.get("due")) else "")
                                  + (f" - {t['who']}" if str(t.get('who') or '').strip() else "") for t in todos if t.get("task")]
        L.append("")
    if problems:
        L += ["## Left out (no clear date)", ""] + [f"- {p} [CHECK]" for p in problems] + [""]
    if not good and not todos:
        L += ["Joe found no dates or to-dos in it.", ""]
    atomic_write_text(folder / "dates-and-todos.md", "\n".join(L))
    st.media_files += ["calendar.ics", "dates-and-todos.md"]
    st.items = len(good) + len(todos)
    st.flags.extend({"item": "calendar", "flag": f"[CHECK] {p}"} for p in problems[:20])
    st.flags.extend({"item": "calendar", "flag": f"[CHECK] guessed: {e.get('title')}"} for e in good if not e.get("sure", True))
    engine.log(f"  {len(good)} event(s), {len(todos)} to-do(s) -> calendar.ics")


def _sort(engine, job, st, files, ask, folder: Path, failed: list[str]) -> None:
    from .tools import _key, chosen_options
    opts = chosen_options(job)
    cats = [c.strip() for c in re.split(r"[,;\n]", job.format) if c.strip()] if job.format.strip() else []
    cat_line = (f"Pick the category from this list: {', '.join(cats)} (or 'Other').\n" if cats else
                "Pick a short, plain category like Bills, Taxes, Medical, School, Work, Receipts, Letters, Manuals.\n")
    plan_path = folder / "_sorted.md"
    lines = ["# Sorted copies", "", "Your original files were not moved or changed.", "",
             "| Original | Copy |", "|---|---|"]
    for src in files:
        key = _key(engine, src)
        if key in st.titles:
            continue
        from .tools import document_text
        try:
            text = document_text(src, engine.log)[:1500] if src.suffix.lower() != ".csv" else src.read_text("utf-8", "replace")[:1500]
        except (ValueError, OSError) as e:
            failed.append(f"{src.name}: {e}"[:200])
            continue
        got = ask("sort-files", SORT_SYSTEM, SORT_ASK.format(name=src.name, text=text, cats=cat_line))
        if not isinstance(got, dict):
            failed.append(f"{src.name}: the model's answer didn't make sense")
            continue
        cat = safe_name(got.get("category") or "Other", 40) if "folders" in opts else ""
        if cats and cat and cat.lower() not in {c.lower() for c in cats} | {"other"}:
            st.flags.append({"item": src.name, "flag": f"[CHECK] put in '{cat}', not one of your categories"})
        name = src.name
        if "rename" in opts:
            d = _d(got.get("date"))
            name = (f"{d:%Y-%m-%d} " if d else "") + safe_name(got.get("title") or src.stem) + src.suffix.lower()
        dest_dir = folder / cat if cat else folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest, n = dest_dir / name, 2
        while dest.exists():
            dest = dest_dir / f"{Path(name).stem} ({n}){Path(name).suffix}"
            n += 1
        shutil.copy2(src, dest)
        rel = str(dest.relative_to(folder)).replace("\\", "/")
        lines.append(f"| {src.name} | {rel} |")
        st.titles.append(key)
        st.media_files.append(rel)
        st.items += 1
        engine._save_state(job, st)
        engine.log(f"  {src.name} -> {rel}")
        atomic_write_text(plan_path, "\n".join(lines) + "\n")


def _sheet(engine, job, st, src: Path, stem: str, ask, folder: Path) -> None:
    from .sheets import SheetError, read_table
    from .tools import questions_from
    try:
        header, rows, cut = read_table(src)
    except (SheetError, OSError, ValueError) as e:
        raise RuntimeError(str(e)) from e
    if not header or not rows:
        raise RuntimeError("the spreadsheet looks empty")
    qs = questions_from(job.format) or [job.format.strip()]
    sample = json.dumps([dict(zip(header, r)) for r in rows[:5]], ensure_ascii=False)
    L = [f"# Answers: {src.name}", "", f"{len(rows)} rows" + (" (only the first part of a very big sheet)" if cut else "")
         + ". The numbers are worked out by Joe's own math, not guessed by AI.", ""]
    charts = 0
    for q in qs:
        plan = ask("ask-sheet", SHEET_SYSTEM, SHEET_ASK.format(cols=", ".join(header), sample=sample, q=q))
        L += [f"## {q}", ""]
        if not isinstance(plan, dict):
            L += ["Joe couldn't turn that question into a plan. Try asking it more simply.", ""]
            continue
        res = run_query(header, rows, plan)
        if res.get("error"):
            L += [f"Joe couldn't answer this: {res['error']}.", ""]
            st.flags.append({"item": src.name, "flag": f"[CHECK] '{q[:60]}': {res['error']}"})
            continue
        L += [f"How Joe worked it out: {res['how']}.", ""]
        if "list" in res:
            lst = res["list"]
            L += [f"{res['total_rows']} matching row(s)" + (f", first {len(lst)} shown" if len(lst) < res["total_rows"] else "") + ":", ""]
            if lst:
                L += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
                L += ["| " + " | ".join(str(r.get(h, "")) for h in header) + " |" for r in lst]
            L.append("")
            continue
        out = res["rows"]
        if len(out) == 1 and out[0][0] == "All":
            L += [f"**{fmt(out[0][1])}**", ""]
        else:
            L += ["| | Answer |", "|---|---|"] + [f"| {g} | {fmt(v)} |" for g, v in out] + [""]
            if plan.get("chart", True) and len(out) > 1:
                charts += 1
                name = f"{stem}-chart-{charts}.svg"
                atomic_write_text(folder / name, bar_svg(out, q))
                st.media_files.append(name)
                L += [f"Chart: {name}", ""]
        if res.get("skipped"):
            L += [f"_{res['skipped']} row(s) had no number there and were left out._", ""]
    name = f"{stem}-answers.md"
    atomic_write_text(folder / name, "\n".join(L))
    st.media_files.append(name)
    engine.log(f"  {src.name}: {len(qs)} question(s) -> {name}")
