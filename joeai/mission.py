"""Mission parser.

The smallest mission is one line:
    TASK: 20 Instagram captions for a small bakery  CHUNKS: 4 x 5

More control:
    PROJECT: My Shop   RULES: Warm, plain voice.
    TASK: Product blurbs  CHUNKS: 8 x 10  MIN WORDS PER ITEM: 60
    FORMAT: A short title line, then one paragraph.
    TASK: Building system  SAVE: game/building.md  PROJECT: My Game
    PART: ## Overview. Goals, player flow, core rules.
    PART: ## Data. Data tables with example rows.
    TASK: Item table  SAVE: game/items.csv  CHUNKS: 3 x 10
    HEADER: name,type,weight,value

'=== JOE MISSION ===' / '=== END ===' lines around it are optional. SAVE is optional
(default Output/<project>/<task>.md); SAVE ending in .mp4 / .png means TYPE video / image.

Two ways to split a task:
  CHUNKS: 8 x 10    list mode: 8 parts of 10 '## title' items each (duplicates dropped)
  PART: ... (repeat) guided mode: one part per PART line, its text is that part's
                     instructions; the model's text is kept as written (documents)
TYPE: image / video: SAVE is a folder. CHUNKS n x m = n parts of m prompts written by the
model (one image each, VARIANTS: 2 for more), or PART lines = one prompt brief each
(PROMPTS: as written uses them unchanged). WORKFLOW, NEGATIVE, SIZE 1024 x 1024, SEED, FPS.
TYPE: <tool> (e.g. transcribe, see tools.py) works on the person's own files: INPUT: files or
folders in Inbox, SAVE is a folder, OPTIONS: picks extras (e.g. subtitles, notes).
MODEL on an image task = part of a checkpoint file name (e.g. sdxl or a word from its file name).
A SAVE ending in .csv needs HEADER:; rows are checked and re-quoted so they import cleanly.
PROJECT may also be set per task (after its TASK line) to override the mission's.

Keys are UPPERCASE followed by ':' and must start a line or follow 2+ spaces
(or a tab), so ordinary prose like "Note: x" inside a value is left alone.
Values may run over several lines. RULES before the first TASK apply to
every task; keys after a TASK belong to that task.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

KEYS = ("PROJECT", "RULES", "TASK", "SAVE", "CHUNKS", "MIN WORDS PER ITEM",
        "FORMAT", "MODEL", "TYPE", "INPUT", "NOTES", "PART", "HEADER",
        "WORKFLOW", "NEGATIVE", "SIZE", "VARIANTS", "SEED", "FPS", "PROMPTS", "EXPORT",
        "OPTIONS", "WATERMARK", "STYLE", "FROM", "RESEARCH", "TEMPLATE")
EXPORT_FORMATS = ("docx", "pdf", "epub", "odt", "html", "social", "xlsx")   # social: posts for a scheduler (social.py)
_KEY_RE = re.compile(
    r"(?m)(?:^[ \t]*|(?<=  )|(?<=\t))(" + "|".join(re.escape(k) for k in KEYS) + r")[ \t]*:")
_BLOCK_RE = re.compile(r"===\s*JOE\s+MISSION\s*===(.*?)(?:===\s*END\s*===|\Z)", re.S | re.I)
VIDEO_EXT = (".mp4", ".webm", ".mov", ".mkv", ".gif")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
_CHUNKS_RE = re.compile(r"^\s*(\d+)\s*[x×*]\s*(\d+)\s*$", re.I)
_SIZE_RE = _CHUNKS_RE


class MissionError(ValueError):
    pass


@dataclass
class Job:
    name: str
    save: str
    parts: int
    part_size: int
    min_words: int = 0
    format: str = ""
    rules: str = ""          # task-specific rules
    model: str = ""          # blank = settings default
    type: str = "text"
    inputs: list[str] = field(default_factory=list)
    notes: str = ""
    part_prompts: list[str] = field(default_factory=list)   # guided mode
    header: str = ""                                          # CSV header line
    project: str = ""                                         # per-task override
    # image / video tasks (TYPE: image|video)
    workflow: str = ""        # file in Workflows/ (blank = built-in / Setup default)
    negative: str = ""
    style: str = ""           # one of styles.NAMES ("" = Joe guesses)
    width: int = 0            # 0 = model default
    height: int = 0
    variants: int = 1         # images per prompt (different seeds)
    seed: str = "random"      # random | a number (each image adds 1)
    fps: int = 16             # for frames -> MP4
    prompts_as_written: bool = False   # PART text used as the prompt, no rewriting
    export: list[str] = field(default_factory=list)   # finished copies: docx, pdf, epub...
    options: list[str] = field(default_factory=list)  # tool extras (OPTIONS: subtitles, notes)
    watermark: str = ""      # photo tools: text, or a logo .png in Inbox (only if asked for)
    source: str = ""         # FROM: an earlier task's name; its finished items are handed over
    research: bool = False   # RESEARCH: yes -> look it up online first, list the sources (opt-in)
    template: str = ""       # TEMPLATE: how EXPORT copies look (doctemplates.TEMPLATES; "" = Setup's default)

    @property
    def media(self) -> bool:
        return self.type in ("image", "video")

    @property
    def tool(self) -> bool:
        from .tools import is_tool
        return is_tool(self.type)

    @property
    def guided(self) -> bool:
        return bool(self.part_prompts)

    @property
    def is_csv(self) -> bool:
        return self.save.lower().endswith(".csv")

    @property
    def total_items(self) -> int:
        return 0 if self.guided else self.parts * self.part_size

    @property
    def job_id(self) -> str:
        return slug(self.name) + "-" + hashlib.sha1(self.save.encode()).hexdigest()[:6]


@dataclass
class Mission:
    project: str
    rules: str
    jobs: list[Job]

    def spec_hash(self, job: Job) -> str:
        j = asdict(job)
        if not job.media:          # keep hashes stable for text tasks saved by older versions
            for k in ("workflow", "negative", "width", "height", "variants", "seed", "fps",
                      "prompts_as_written"):
                j.pop(k, None)
        if not j.get("style"):     # keep hashes stable for tasks saved before STYLE existed
            j.pop("style", None)
        j.pop("export", None)      # exporting copies doesn't change what gets written
        if not j.get("options"):   # keep hashes stable for tasks without OPTIONS
            j.pop("options", None)
        if not j.get("watermark"):
            j.pop("watermark", None)
        if not j.get("source"):
            j.pop("source", None)
        if not j.get("research"):
            j.pop("research", None)
        j.pop("template", None)    # how copies look doesn't change what gets written
        blob = json.dumps({"p": self.project, "r": self.rules, "j": j}, sort_keys=True)
        return hashlib.sha1(blob.encode()).hexdigest()[:12]


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:48] or "job"


def parse(text: str) -> Mission:
    m = _BLOCK_RE.search(text)
    body = m.group(1) if m else text          # the === lines are optional
    hits = list(_KEY_RE.finditer(body))
    if not any(h.group(1).upper() == "TASK" for h in hits):
        raise MissionError("Nothing to do yet: start a line with TASK: and say what you want, "
                           "e.g. TASK: 20 Instagram captions for my bakery")

    pairs: list[tuple[str, str]] = []
    for i, h in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(body)
        value = body[h.end():end].strip()
        pairs.append((h.group(1).upper(), _clean(value)))

    project, global_rules, jobs = "", [], []
    cur: dict | None = None
    for key, val in pairs:
        if key == "TASK":
            if cur:
                jobs.append(_make_job(cur, project))
            cur = {"TASK": val}
        elif cur is None:
            if key == "PROJECT":
                project = val
            elif key == "RULES":
                global_rules.append(val)
            elif key == "NOTES":
                continue
            else:
                raise MissionError(f"{key}: appears before any TASK.")
        else:
            if key == "PART":
                cur.setdefault("PART", []).append(val)
            elif key in ("RULES", "FORMAT", "INPUT", "NOTES") and key in cur:
                cur[key] += "\n" + val
            else:
                cur[key] = val
    if cur:
        jobs.append(_make_job(cur, project))
    if not jobs:
        raise MissionError("Mission has no TASK.")
    ids = [j.job_id for j in jobs]
    if len(set(ids)) != len(ids):
        raise MissionError("Two tasks share the same name and SAVE path.")
    for i, j in enumerate(jobs):
        if not j.source:
            continue
        earlier = {x.name.lower(): x.name for x in jobs[:i]}
        want = j.source.strip().lower()
        if want not in earlier:
            raise MissionError(f"Task '{j.name}': FROM: must name a task above it (got '{j.source}'"
                               + (f"; tasks above: {', '.join(x.name for x in jobs[:i])}" if i else "") + ").")
        src = next(x for x in jobs[:i] if x.name.lower() == want)
        if src.media or src.guided:
            raise MissionError(f"Task '{j.name}': FROM: works with a list or spreadsheet task, not "
                               f"{'pictures/video' if src.media else 'a document'} ('{src.name}').")
        if j.tool:
            raise MissionError(f"Task '{j.name}': tools use INPUT, not FROM.")
        j.source = earlier[want]
    return Mission(project=project, rules="\n".join(global_rules), jobs=jobs)


def _clean(v: str) -> str:
    lines = [ln.rstrip() for ln in v.splitlines()]
    return "\n".join(ln.strip() for ln in lines).strip()


def default_save(name: str, project: str = "", kind: str = "text") -> str:
    """Where a task saves when nobody said: Output/<project>/<task name>(.md|.csv|folder)."""
    base = slug(name)[:40].strip("-") or "task"
    if project.strip():
        base = slug(project)[:40].strip("-") + "/" + base
    return base + {"text": ".md", "code": ".md", "sheet": ".csv"}.get(kind, "")


def _make_job(d: dict, mission_project: str = "") -> Job:
    name = d["TASK"].strip()
    if not name:
        raise MissionError("TASK needs a name.")
    save = (d.get("SAVE") or "").strip()
    ext = ("." + save.rsplit(".", 1)[1].lower()) if "." in save.rsplit("/", 1)[-1] else ""
    if not d.get("TYPE") and ext in VIDEO_EXT:            # SAVE: clip.mp4 means a video
        d["TYPE"] = "video"
    elif not d.get("TYPE") and ext in IMAGE_EXT:
        d["TYPE"] = "image"
    typ = (d.get("TYPE") or "text").strip().lower()
    if typ in ("image", "video") and ext in VIDEO_EXT + IMAGE_EXT:
        save = save[: -len(ext)]                           # pictures/videos save into a folder
    if typ in ("text", "code") and ext in VIDEO_EXT + IMAGE_EXT:
        raise MissionError(f"Task '{name}': SAVE ends in {ext}, but this task writes text. "
                           f"For a {'video' if ext in VIDEO_EXT else 'picture'}, add TYPE: "
                           f"{'video' if ext in VIDEO_EXT else 'image'}.")
    if not save:
        kind = "sheet" if d.get("HEADER", "").strip() else typ
        save = default_save(name, d.get("PROJECT", "") or mission_project, kind)
    d["SAVE"] = save
    part_prompts = [p for p in d.get("PART", []) if p.strip()]
    if part_prompts:
        if "CHUNKS" in d:
            raise MissionError(f"Task '{name}': use CHUNKS or PART lines, not both.")
        parts, size = len(part_prompts), 0
        if parts > 500:
            raise MissionError(f"Task '{name}': too many PART lines (max 500).")
    else:
        chunks = d.get("CHUNKS", "1 x 5")
        cm = _CHUNKS_RE.match(chunks)
        if not cm:
            raise MissionError(f"Task '{name}': CHUNKS must look like '8 x 10' (got '{chunks}').")
        parts, size = int(cm.group(1)), int(cm.group(2))
        if not (1 <= parts <= 500 and 1 <= size <= 50):
            raise MissionError(f"Task '{name}': CHUNKS out of range (1-500 parts, 1-50 items each).")
    header = d.get("HEADER", "").strip()
    if d["SAVE"].strip().lower().endswith(".csv"):
        if not header:
            raise MissionError(f"Task '{name}': a .csv SAVE needs a HEADER: line (the column names).")
        if "\n" in header:
            raise MissionError(f"Task '{name}': HEADER must be one line.")
    mw = d.get("MIN WORDS PER ITEM", "0").strip() or "0"
    if not mw.isdigit():
        raise MissionError(f"Task '{name}': MIN WORDS PER ITEM must be a number.")
    jtype = (d.get("TYPE") or "text").strip().lower()
    from .tools import TOOLS, ready_ids
    if jtype in TOOLS and not TOOLS[jtype].ready:
        raise MissionError(f"Task '{name}': the {TOOLS[jtype].name} tool is planned but not built yet.")
    if jtype not in ("text", "code", "image", "video") + ready_ids():
        raise MissionError(f"Task '{name}': TYPE must be text, code, image, video, or a tool "
                           f"({', '.join(ready_ids())}).")
    source = (d.get("FROM") or "").strip()
    research = (d.get("RESEARCH") or "").strip().lower() in ("yes", "y", "on", "true", "1")
    inputs = [x.strip() for x in re.split(r"[,\n]", d.get("INPUT", "")) if x.strip()]
    options = [re.sub(r"\s*[:=]\s*|\s+", " ", x.strip().lower())         # "size: 1600" -> "size 1600"
               for x in re.split(r"[,\n]", d.get("OPTIONS", "")) if x.strip()]
    if options and jtype not in TOOLS:
        raise MissionError(f"Task '{name}': OPTIONS is for tools (like TYPE: transcribe).")
    if jtype in TOOLS:
        from .makers import NO_INPUT_OK
        if not inputs and TOOLS[jtype].accepts and jtype not in NO_INPUT_OK:
            raise MissionError(f"Task '{name}': say which files to use with INPUT: (files or a "
                               "folder in Inbox).")
        if jtype == "music" and not d.get("FORMAT", "").strip():
            raise MissionError(f"Task '{name}': describe the music or sound with FORMAT: (one per line).")
        if "CHUNKS" in d or part_prompts:
            raise MissionError(f"Task '{name}': a {TOOLS[jtype].name} task doesn't use CHUNKS or PART.")
        from .tools import option_ok, options_help
        bad = [o for o in options if not option_ok(TOOLS[jtype], o)]
        if bad:
            raise MissionError(f"Task '{name}': OPTIONS can be {options_help(TOOLS[jtype])} "
                               f"(got {', '.join(bad)}).")
        from .tools import missing_required
        need = missing_required(TOOLS[jtype], options)
        if need:
            raise MissionError(f"Task '{name}': {need}.")
        if d["SAVE"].strip().lower().endswith((".md", ".csv", ".txt")):
            raise MissionError(f"Task '{name}': a tool saves into a folder; give SAVE a folder name.")
        parts, size = 1, 1
    media = {}
    if jtype in ("image", "video"):
        if part_prompts == [] and "CHUNKS" not in d:
            parts, size = 1, 4
        w = h = 0
        if d.get("SIZE"):
            sm = _SIZE_RE.match(d["SIZE"])
            if not sm:
                raise MissionError(f"Task '{name}': SIZE must look like '1024 x 1024'.")
            w, h = int(sm.group(1)), int(sm.group(2))
            if not (64 <= w <= 4096 and 64 <= h <= 4096):
                raise MissionError(f"Task '{name}': SIZE out of range (64-4096).")
            w, h = w // 8 * 8, h // 8 * 8
        var = (d.get("VARIANTS") or "1").strip()
        fps = (d.get("FPS") or "16").strip()
        if not var.isdigit() or not 1 <= int(var) <= 16:
            raise MissionError(f"Task '{name}': VARIANTS must be 1-16.")
        if not fps.isdigit() or not 1 <= int(fps) <= 60:
            raise MissionError(f"Task '{name}': FPS must be 1-60.")
        seed = (d.get("SEED") or "random").strip().lower()
        if seed != "random" and not seed.isdigit():
            raise MissionError(f"Task '{name}': SEED must be 'random' or a number.")
        pr = (d.get("PROMPTS") or "write").strip().lower()
        if pr not in ("write", "as written"):
            raise MissionError(f"Task '{name}': PROMPTS must be 'write' or 'as written'.")
        if pr == "as written" and not part_prompts:
            raise MissionError(f"Task '{name}': PROMPTS: as written needs PART lines (one prompt each).")
        if d["SAVE"].strip().lower().endswith(".csv"):
            raise MissionError(f"Task '{name}': image/video SAVE is a folder, not a .csv.")
        style = d.get("STYLE", "").strip().lower()
        from .styles import NAMES as _STYLES
        if style and style not in _STYLES:
            raise MissionError(f"Task '{name}': STYLE can be {', '.join(_STYLES)}.")
        media = dict(workflow=d.get("WORKFLOW", "").strip(), negative=d.get("NEGATIVE", ""), style=style,
                     width=w, height=h, variants=int(var), seed=seed, fps=int(fps),
                     prompts_as_written=pr == "as written")
    export = [x.strip().lower().lstrip(".") for x in re.split(r"[,\s]+", d.get("EXPORT", "")) if x.strip()]
    if jtype == "video":                    # videos: EXPORT: gif adds a looping GIF next to each clip
        bad = [x for x in export if x != "gif"]
        if bad:
            raise MissionError(f"Task '{name}': a video task can only EXPORT: gif (got {', '.join(bad)}).")
    else:
        bad = [x for x in export if x not in EXPORT_FORMATS]
        if bad:
            raise MissionError(f"Task '{name}': EXPORT can be {', '.join(EXPORT_FORMATS)}"
                               + (" (gif is for video tasks)" if "gif" in bad else "") + f" (got {', '.join(bad)}).")
        if export and jtype == "image":
            raise MissionError(f"Task '{name}': EXPORT works on writing tasks (not pictures).")
        if d["SAVE"].strip().lower().endswith(".csv") and [x for x in export if x not in ("social", "xlsx")]:
            raise MissionError(f"Task '{name}': a spreadsheet (.csv) task can EXPORT: xlsx and social.")
        if "xlsx" in export and not d["SAVE"].strip().lower().endswith(".csv"):
            raise MissionError(f"Task '{name}': EXPORT: xlsx is for spreadsheet tasks (SAVE: name.csv).")
    template = (d.get("TEMPLATE") or "").strip().lower().replace("'", "").replace(" ", "-")
    if template:
        from .doctemplates import TEMPLATES as _TPL
        from .doctemplates import ALIASES as aliases
        template = aliases.get(template, template)
        if template not in _TPL:
            raise MissionError(f"Task '{name}': TEMPLATE can be {', '.join(_TPL)}.")
    watermark = " ".join(d.get("WATERMARK", "").split())[:120]
    if watermark:
        from .tools import TOOLS as _T
        if jtype not in _T or not _T[jtype].mark:
            raise MissionError(f"Task '{name}': WATERMARK works on photo tools (TYPE: photo-batch).")
    return Job(**media, export=export, options=options, watermark=watermark, name=name, save=d["SAVE"].strip(), parts=parts, part_size=size,
               min_words=int(mw), format=d.get("FORMAT", ""), rules=d.get("RULES", ""),
               model=d.get("MODEL", "").strip(), type=jtype, inputs=inputs,
               notes=d.get("NOTES", ""), part_prompts=part_prompts, header=header,
               project=d.get("PROJECT", "").strip(), source=source, research=research, template=template)


# --------------------------------------------------------------------------- builder support
# The F6 Builder edits tasks as plain dicts and turns them back into a mission block,
# so nobody has to hand-edit a file. parse(to_text(...)) round-trips.
TASK_FIELDS = ("name", "save", "type", "project", "parts", "part_size", "part_prompts", "format",
               "rules", "min_words", "header", "inputs", "model", "notes", "workflow",
               "negative", "style", "width", "height", "variants", "seed", "fps", "prompts_as_written",
               "export", "options", "watermark", "source", "research", "template")


def job_to_dict(j: Job) -> dict:
    d = {k: getattr(j, k) for k in TASK_FIELDS}
    d["mode"] = ("tool" if j.tool else "media" if j.media else "csv" if j.is_csv
                 else "guided" if j.guided else "list")
    return d


def mission_to_dict(m: Mission) -> dict:
    return {"project": m.project, "rules": m.rules, "tasks": [job_to_dict(j) for j in m.jobs]}


_KEY_IN_VALUE = re.compile(r"(?m)(^[ \t]*|[ \t]{2,})(" + "|".join(re.escape(k) for k in KEYS) + r")([ \t]*):")


def _safe(v) -> str:
    """Keep a value from being read as a new KEY: (e.g. a FORMAT that says 'NOTES: ...')."""
    s = str(v if v is not None else "").strip()
    return _KEY_IN_VALUE.sub(lambda m: (" " if m.group(1) else "") + m.group(2).capitalize() + m.group(3) + ":", s)


def to_text(project: str, rules: str, tasks: list[dict]) -> str:
    L = ["=== JOE MISSION ==="]
    if str(project or "").strip():
        L.append(f"PROJECT: {_safe(project)}")
    if str(rules or "").strip():
        L.append(f"RULES: {_safe(rules)}")
    for t in tasks:
        name = " ".join(_safe(t.get("name") or "Untitled task").split())
        save = " ".join(_safe(t.get("save") or "").split())
        L.append("")
        L.append(f"TASK: {name}" + (f"  SAVE: {save}" if save else ""))
        typ = (t.get("type") or "text").strip().lower()
        if typ != "text":
            L.append(f"TYPE: {typ}")
        if str(t.get("project") or "").strip():
            L.append(f"PROJECT: {_safe(t['project'])}")
        prompts = [p for p in (t.get("part_prompts") or []) if str(p).strip()]
        from .tools import is_tool
        if not prompts and not is_tool(typ):
            L.append(f"CHUNKS: {int(t.get('parts') or 1)} x {int(t.get('part_size') or 5)}")
        if int(t.get("min_words") or 0):
            L.append(f"MIN WORDS PER ITEM: {int(t['min_words'])}")
        if t.get("research"):
            L.append("RESEARCH: yes")
        for key, fld in (("FROM", "source"), ("HEADER", "header"), ("FORMAT", "format"), ("RULES", "rules"),
                         ("MODEL", "model"), ("NOTES", "notes")):
            if str(t.get(fld) or "").strip():
                L.append(f"{key}: {_safe(t[fld])}")
        exp = t.get("export") or []
        if isinstance(exp, str):
            exp = [x for x in re.split(r"[,\s]+", exp) if x]
        if exp and typ != "image":
            L.append("EXPORT: " + ", ".join(_safe(x) for x in exp))
        if str(t.get("template") or "").strip():
            L.append(f"TEMPLATE: {_safe(t['template'])}")
        inputs = t.get("inputs") or []
        if isinstance(inputs, str):
            inputs = [x for x in re.split(r"[,\n]", inputs) if x.strip()]
        if inputs:
            L.append("INPUT: " + ", ".join(_safe(x) for x in inputs))
        opts = t.get("options") or []
        if isinstance(opts, str):
            opts = [x for x in re.split(r"[,\s]+", opts) if x]
        if opts and is_tool(typ):
            L.append("OPTIONS: " + ", ".join(_safe(x) for x in opts))
        if str(t.get("watermark") or "").strip() and is_tool(typ):
            L.append("WATERMARK: " + " ".join(_safe(t["watermark"]).split()))
        if typ in ("image", "video"):
            if str(t.get("workflow") or "").strip():
                L.append(f"WORKFLOW: {_safe(t['workflow'])}")
            if str(t.get("negative") or "").strip():
                L.append(f"NEGATIVE: {_safe(t['negative'])}")
            if str(t.get("style") or "").strip():
                L.append(f"STYLE: {_safe(t['style'])}")
            if int(t.get("width") or 0) and int(t.get("height") or 0):
                L.append(f"SIZE: {int(t['width'])} x {int(t['height'])}")
            if int(t.get("variants") or 1) != 1:
                L.append(f"VARIANTS: {int(t['variants'])}")
            if str(t.get("seed") or "random").strip().lower() != "random":
                L.append(f"SEED: {_safe(t['seed'])}")
            if typ == "video" and int(t.get("fps") or 16) != 16:
                L.append(f"FPS: {int(t['fps'])}")
            if t.get("prompts_as_written") and prompts:
                L.append("PROMPTS: as written")
        for p in prompts:
            L.append(f"PART: {_safe(p)}")
    L += ["=== END ===", ""]
    return "\n".join(L)
