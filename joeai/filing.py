"""How Joe files what he makes (Setup > General > HOW JOE FILES HIS WORK).

Three ways, picked in Setup (settings.filing.how):
  date     (the default) one folder per mission with the date in front, every task inside it:
           Output/2026-11-10 Showcase video/...
  project  the same mission folders, inside a folder for the mission's PROJECT:
           Output/My Shop/2026-11-10 Product blurbs/...  (no PROJECT: = like "date")
  flat     as Joe did before 2.3: every task straight into Output under its SAVE: name.

Inside a mission folder:
  - writing gets its own folder, with its exports (.docx, .pdf...) and versions inside:
        <mission>/<task>/<task>.md, <task>.docx, <task> v2.md ...
  - pictures, video and tools get a folder: <mission>/<task>/
  - a mission with only one task uses the mission folder itself (no folder in a folder).
  - running a task again puts the new result inside the original's folder as a numbered version
    (<task> v2.md, or a v2 folder), even on another day. Joe remembers where each task went in
    Output/.joe/filing.json.
A SAVE: line still names the file; in "date" and "project" filing only its name is used (the folder
part is replaced by the mission folder). Pick "flat" to have SAVE: used exactly as written.

Nothing already in Output moves when this changes. tidy() is the one-time "tidy my Output" button:
it only MOVES (never deletes), refuses to overwrite anything, and writes an undo list (undo()).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import date, datetime
from pathlib import Path

from .fsutil import atomic_write_text

MODES = ("date", "project", "flat")
INDEX = "filing.json"
TIDY_DIR = "tidy"                      # Output/.joe/tidy/tidy-<stamp>.json = undo lists
_DATED = re.compile(r"^\d{4}-\d{2}-\d{2} ")
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
# Top-level things in Output that are Joe's own and never get filed or tidied.
KEEP_TOP = ("Backups",)


def how(settings) -> str:
    v = (getattr(getattr(settings, "filing", None), "how", "") or "date").strip().lower()
    return v if v in MODES else "date"


def clean_name(text: str, limit: int = 60) -> str:
    """A folder name people can read: spaces and capitals kept; characters Windows refuses dropped."""
    s = _BAD.sub(" ", str(text or ""))
    s = " ".join(s.split()).strip(" .")[:limit].strip(" .")
    if s.lower().split(".")[0] in _RESERVED:
        s = "_" + s
    return s or "Mission"


def mission_title(mission) -> str:
    names = [j.name for j in getattr(mission, "jobs", [])]
    if not names:
        return "Mission"
    first = re.sub(r"\s*\((?:watch folder)\)\s*$", "", names[0])
    return first + (f" +{len(names) - 1}" if len(names) > 1 else "")


def mission_key(mission) -> str:
    ids = sorted(j.job_id for j in getattr(mission, "jobs", []))
    blob = (getattr(mission, "project", "") or "") + "|" + "|".join(ids)
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def as_written(job) -> bool:
    """Tasks that keep their SAVE: path whatever the filing choice: watch folders (they have a
    standing folder, Output/watch-<tool>) and anything the person asked to keep where it is."""
    save = (job.save or "").replace("\\", "/").lstrip("/")
    return bool(job.tool and save.startswith("watch-")) or save.lower().startswith("output/")


# ----------------------------------------------------------------------------- index
def _index_path(sb) -> Path:
    return sb.meta / INDEX


def load_index(sb) -> dict:
    try:
        d = json.loads(_index_path(sb).read_text(encoding="utf-8"))
        if isinstance(d, dict):
            d.setdefault("jobs", {})
            d.setdefault("missions", {})
            return d
    except (OSError, ValueError):
        pass
    return {"jobs": {}, "missions": {}}


def save_index(sb, d: dict) -> None:
    try:
        sb.meta.mkdir(parents=True, exist_ok=True)
        atomic_write_text(_index_path(sb), json.dumps(d, indent=1, ensure_ascii=False))
    except OSError:
        pass


def _rel(sb, p: Path) -> str:
    return str(p.relative_to(sb.output)).replace("\\", "/")


# ----------------------------------------------------------------------------- placing
def mission_folder(engine, mission) -> Path:
    """This mission's folder (made once per run; a rerun of the same mission gets its old one)."""
    cache = engine.__dict__.setdefault("_filing_folders", {})
    key = mission_key(mission)
    if key in cache:
        return cache[key]
    sb = engine.sb
    idx = load_index(sb)
    old = idx["missions"].get(key)
    folder = None
    if old and (sb.output / old).is_dir():
        folder = sb.output / old
    if folder is None:                                   # a task of it ran before: go back to that folder
        for j in mission.jobs:
            rel = idx["jobs"].get(j.job_id, {}).get("mission")
            if rel and (sb.output / rel).is_dir():
                folder = sb.output / rel
                break
    if folder is None:
        base = sb.output
        project = (mission.project or next((j.project for j in mission.jobs if j.project), "")).strip()
        if how(engine.s) == "project" and project:
            base = sb.output / clean_name(project, 50)
        name = f"{date.today():%Y-%m-%d} {clean_name(mission_title(mission), 50)}"
        folder, n = base / name, 2
        taken = set(idx["missions"].values())
        while folder.exists() and (_rel(sb, folder) in taken or any(folder.iterdir())):
            folder = base / f"{name} ({n})"
            n += 1
    folder.mkdir(parents=True, exist_ok=True)
    idx["missions"][key] = _rel(sb, folder)
    save_index(sb, idx)
    cache[key] = folder
    project = (mission.project or next((j.project for j in mission.jobs if j.project), "")).strip()
    if project:                                          # the project page lists this mission's folder
        from . import projects
        projects.add_mission(sb, project, _rel(sb, folder))
    return folder


def _version_file(target: Path) -> Path:
    cand, n = target, 2
    while cand.exists():
        cand = target.with_name(f"{target.stem} v{n}{target.suffix}")
        n += 1
    return cand


def _version_folder(base: Path) -> Path:
    if not base.exists() or not any(base.iterdir()):
        return base
    n = 2
    while (base / f"v{n}").exists() and any((base / f"v{n}").iterdir()):
        n += 1
    return base / f"v{n}"


def place(engine, job, kind: str) -> Path | None:
    """Where a new result goes. kind = "file" (writing, spreadsheets) or "folder" (pictures, video,
    tools). None = file it as written (flat filing, watch folders): the caller does what it always did."""
    if how(engine.s) == "flat" or as_written(job):
        return None
    sb = engine.sb
    mission = getattr(engine, "_mission", None)
    if mission is None or job not in getattr(mission, "jobs", []):
        from .mission import Mission
        mission = Mission(project=job.project, rules="", jobs=[job])
    idx = load_index(sb)
    leaf = (job.save or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or "task"
    stem, dot, ext = leaf.rpartition(".")
    if not dot or "/" in ext or len(ext) > 5:
        stem, ext = leaf, ""
    stem = stem or "task"
    prior = idx["jobs"].get(job.job_id, {}).get("place")
    prior_path = sb.output / prior if prior else None
    if kind == "file":
        ext = "." + ext if ext else ".md"
        if prior_path is not None and prior_path.is_file():           # run again: a version beside it
            target = _version_file(prior_path.with_name(f"{prior_path.stem}{ext}"))
        else:
            mf = mission_folder(engine, mission)
            home = mf if len(mission.jobs) == 1 else mf / clean_name(stem)
            home.mkdir(parents=True, exist_ok=True)
            target = _version_file(home / f"{stem}{ext}")
    else:
        if prior_path is not None and prior_path.is_dir():
            target = _version_folder(prior_path)
        else:
            mf = mission_folder(engine, mission)
            target = _version_folder(mf if len(mission.jobs) == 1 else mf / clean_name(stem))
        target.mkdir(parents=True, exist_ok=True)
    rec = idx["jobs"].get(job.job_id) or {}
    if not prior_path or not prior_path.exists():                     # first run: remember the original
        rec = {"place": _rel(sb, target), "mission": _rel(sb, mission_folder(engine, mission)),
               "name": job.name, "when": datetime.now().isoformat(timespec="seconds")}
    rec["latest"] = _rel(sb, target)
    idx = load_index(sb)                                              # mission_folder() may have saved
    idx["jobs"][job.job_id] = rec
    save_index(sb, idx)
    engine.__dict__.setdefault("_placed", {})[_norm(job.save)] = _rel(sb, target)
    return target


def _norm(rel: str) -> str:
    r = (rel or "").replace("\\", "/").strip().lstrip("/")
    if r.lower().startswith("output/"):
        r = r[7:]
    return r.rstrip("/").lower()


def translate_input(engine, rel: str) -> str:
    """INPUT: Output/notes/a.md written in the same mission as the task that SAVEs notes/a.md: point
    it at where that task really went (its mission folder). Anything else is returned unchanged."""
    placed = engine.__dict__.get("_placed") or {}
    n = _norm(rel)
    if n in placed:
        return "Output/" + placed[n]
    for save, actual in placed.items():                               # a folder task: Output/pics/001.png
        if save and n.startswith(save + "/"):
            tail = rel.replace("\\", "/").rstrip("/")[-(len(n) - len(save)):]
            return "Output/" + actual + tail
    return rel


# ----------------------------------------------------------------------------- tidy my Output
_RERUN = re.compile(r"^(?P<base>.+?)(?:[ _-]v(?P<v>\d+)|-(?:redo|retry|again)(?P<r>\d*)|[ _-]?(?<!\d)(?P<n>[2-9]))$", re.I)
_EXPLICIT_V = re.compile(r"[ _-]v\d+$", re.I)


def _base_name(name: str) -> tuple[str, int]:
    """'blurbs_v2' -> ('blurbs', 2); 'blurbs-redo' -> ('blurbs', 2); 'blurbs2' -> ('blurbs', 2)."""
    m = _RERUN.match(name)
    if not m or len(m.group("base")) < 3:
        return name, 1
    if m.group("v"):
        return m.group("base"), int(m.group("v"))
    if m.group("n"):
        return m.group("base"), int(m.group("n"))
    return m.group("base"), 2 + (int(m.group("r")) if m.group("r") else 0)


def _state_dates(sb) -> dict[str, str]:
    """Top-level Output name -> the date its task started (from Joe's run state)."""
    out: dict[str, str] = {}
    for p in (sb.meta / "state").glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rel = (d.get("output") or "").replace("\\", "/")
        when = (d.get("started") or d.get("finished") or "")[:10]
        if rel and re.match(r"\d{4}-\d{2}-\d{2}$", when):
            out.setdefault(rel.split("/", 1)[0], when)
    return out


def _skip_top(sb, p: Path, projects: set[str]) -> bool:
    n = p.name
    return (n.startswith((".", "_")) or n in KEEP_TOP or n.lower().startswith("watch-")
            or bool(_DATED.match(n)) or n in projects)


def tidy_plan(sb) -> list[dict]:
    """What tidy() would move: [{from, to, why}], nothing moved yet. Loose files that belong together
    (notes.md + notes.docx + notes.pdf) go into one folder; reruns (x_v2, x-redo, x2) go inside the
    original's folder as v2, v3..."""
    from . import projects as projects_mod
    out = sb.output
    if not out.is_dir():
        return []
    taken_projects = {clean_name(p) for p in projects_mod.names(sb)}
    dates = _state_dates(sb)
    items = [p for p in sorted(out.iterdir(), key=lambda p: p.name.lower()) if not _skip_top(sb, p, taken_projects)]
    groups: dict[str, list[tuple[Path, int]]] = {}
    for p in items:
        key = p.stem if p.is_file() else p.name
        base, ver = _base_name(key)
        groups.setdefault(base.lower(), []).append((p, ver))
    plan = []
    used: set[str] = set()
    for base_l, members in groups.items():
        # explicit numbers (x_v3) keep theirs; -redo / -retry / x2 take the next free one
        members.sort(key=lambda t: (t[1], 0 if _EXPLICIT_V.search(t[0].stem if t[0].is_file() else t[0].name) else 1,
                                    t[0].name.lower()))
        first = members[0][0]
        base = _base_name(first.stem if first.is_file() else first.name)[0]
        when = dates.get(first.name) or next((dates[m.name] for m, _ in members if m.name in dates), "")
        if not when:
            try:
                when = datetime.fromtimestamp(min(m.stat().st_mtime for m, _ in members)).strftime("%Y-%m-%d")
            except OSError:
                when = f"{date.today():%Y-%m-%d}"
        pretty = clean_name(base.replace("-", " ").replace("_", " ").strip().capitalize() or base, 50)
        folder = f"{when} {pretty}"
        n = 2
        while folder.lower() in used or (out / folder).exists():
            folder = f"{when} {pretty} ({n})"
            n += 1
        used.add(folder.lower())
        versions_seen: dict[int, int] = {}
        steps = []
        for p, ver in members:
            if p.is_dir():
                if ver <= 1 and not versions_seen.get(1):          # the original: it becomes the dated folder
                    versions_seen[1] = 1
                    steps.insert(0, {"from": p.name, "to": folder, "why": "task"})
                    continue
                if ver <= 1:
                    dest = f"{folder}/{p.name}"
                else:
                    v = max(ver, 2)
                    while versions_seen.get(v):
                        v += 1
                    versions_seen[v] = 1
                    dest = f"{folder}/v{v}"
                steps.append({"from": p.name, "to": dest, "why": "rerun" if ver > 1 else "task"})
            else:
                name = p.name if ver <= 1 else f"{base} v{ver}{p.suffix}"
                steps.append({"from": p.name, "to": f"{folder}/{name}", "why": "rerun" if ver > 1 else "file"})
        plan += steps
    # a lone folder "moved into itself" (folder name == dest) is fine: dest is a new dated name
    return plan


def tidy(sb, plan: list[dict] | None = None) -> dict:
    """Move the old Output into dated folders. Only moves; never deletes or overwrites. Writes an
    undo list (Output/.joe/tidy/tidy-<stamp>.json) and fixes Joe's own records so resume, reports,
    the Files tab, Joe Phone and the connector still find everything."""
    plan = tidy_plan(sb) if plan is None else plan
    out = sb.output
    moved, skipped = [], []
    for step in plan:
        src, dst = out / step["from"], out / step["to"]
        try:
            src.resolve().relative_to(out.resolve())
            dst.resolve().relative_to(out.resolve())
        except ValueError:
            skipped.append({**step, "why": "outside Output"})
            continue
        if not src.exists():
            skipped.append({**step, "why": "not there any more"})
            continue
        if dst.exists():
            skipped.append({**step, "why": "something is already there"})
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append({"from": step["from"], "to": step["to"]})
        except OSError as e:
            skipped.append({**step, "why": str(e)[:120]})
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    undo_file = ""
    if moved:
        d = sb.meta / TIDY_DIR
        d.mkdir(parents=True, exist_ok=True)
        undo_path = d / f"tidy-{stamp}.json"
        atomic_write_text(undo_path, json.dumps({"when": stamp, "moved": moved, "undone": False}, indent=1,
                                                ensure_ascii=False))
        txt = ["Joe tidied Output on " + datetime.now().strftime("%Y-%m-%d %H:%M") + ".",
               "Nothing was deleted. Each line: old place  ->  new place.",
               "Setup > General > HOW JOE FILES HIS WORK > UNDO puts everything back.", ""]
        txt += [f"{m['from']}  ->  {m['to']}" for m in moved]
        atomic_write_text(out / f"_TIDY_UNDO_{stamp}.txt", "\n".join(txt) + "\n")
        undo_file = undo_path.name
        _repoint(sb, moved)
    return {"ok": True, "moved": len(moved), "skipped": skipped, "undo": undo_file}


def _swap(rel: str, moved: list[dict]) -> str:
    r = (rel or "").replace("\\", "/")
    for m in moved:
        a, b = m["from"], m["to"]
        if r == a:
            return b
        if r.startswith(a + "/"):
            return b + r[len(a):]
    return rel


def _repoint(sb, moved: list[dict]) -> None:
    """After moving: Joe's run state, his filing record, project lists and reports point at the new places."""
    for p in (sb.meta / "state").glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        changed = False
        new = _swap(d.get("output", ""), moved)
        if new != d.get("output", ""):
            d["output"], changed = new, True
        mf = [_swap(x, moved) for x in d.get("media_files") or []]
        if mf != (d.get("media_files") or []):
            d["media_files"], changed = mf, True
        if changed:
            atomic_write_text(p, json.dumps(d, indent=1))
    idx = load_index(sb)
    for rec in idx["jobs"].values():
        for k in ("place", "latest", "mission"):
            if rec.get(k):
                rec[k] = _swap(rec[k], moved)
    idx["missions"] = {k: _swap(v, moved) for k, v in idx["missions"].items()}
    save_index(sb, idx)
    from . import projects as projects_mod
    projects_mod.repoint(sb, lambda r: _swap(r, moved))
    reports = [sb.output / "_REPORT.md"] + sorted((sb.meta / "reports").glob("REPORT_*.md"))
    for rp in reports:
        try:
            text = rp.read_text(encoding="utf-8")
        except OSError:
            continue
        new = text
        for m in sorted(moved, key=lambda m: -len(m["from"])):
            new = re.sub(r"(?<=[\s|(`])" + re.escape(m["from"]) + r"(?=[/\s|)`]|$)", m["to"].replace("\\", "\\\\"),
                         new)
        if new != text:
            atomic_write_text(rp, new)


def undo_lists(sb) -> list[dict]:
    out = []
    for p in sorted((sb.meta / TIDY_DIR).glob("tidy-*.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"file": p.name, "when": d.get("when", ""), "moved": len(d.get("moved", [])),
                    "undone": bool(d.get("undone"))})
    return out


def undo(sb, file: str = "") -> dict:
    """Put a tidy back: every move reversed, newest first. Still only moves; a place that's taken
    is left alone and listed."""
    lists = [x for x in undo_lists(sb) if not x["undone"]]
    if file:
        lists = [x for x in lists if x["file"] == Path(file).name]
    if not lists:
        return {"ok": False, "error": "There's no tidy to undo."}
    path = sb.meta / TIDY_DIR / lists[0]["file"]
    d = json.loads(path.read_text(encoding="utf-8"))
    out = sb.output
    back, skipped = [], []
    for m in reversed(d.get("moved", [])):
        src, dst = out / m["to"], out / m["from"]
        if not src.exists() or dst.exists():
            skipped.append(m)
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            back.append({"from": m["to"], "to": m["from"]})
        except OSError:
            skipped.append(m)
    # empty dated folders left behind by the undo (only empty ones; nothing with files is touched)
    for m in back:
        top = out / m["from"].split("/", 1)[0]
        try:
            for sub in sorted((x for x in top.rglob("*") if x.is_dir()), key=lambda x: -len(x.parts)):
                if not any(sub.iterdir()):
                    sub.rmdir()
            if top.is_dir() and not any(top.iterdir()):
                top.rmdir()
        except OSError:
            pass
    _repoint(sb, back)
    d["undone"] = True
    atomic_write_text(path, json.dumps(d, indent=1, ensure_ascii=False))
    return {"ok": True, "moved_back": len(back), "skipped": skipped}
