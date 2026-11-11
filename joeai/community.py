"""Add-ons from other people (Setup > Add-ons): new tools, starter packs, picture workflows and
themes that plug into Joe without changing his code.

An add-on is a folder (or a .zip of one) with an addon.json, kept in <Joe's folder>/Add-ons/<id>/.
docs/ADDONS.md is the guide for people who make them. The rules that keep you safe:

- Nothing in an add-on does anything until YOU turn it on, after Joe shows what it adds and, for a
  tool, the exact program and command line it runs.
- Packs, workflows and themes are data. Joe checks them like his own (a workflow must pass the same
  check as one you import; a theme is only checked colors and a font from a safe list).
- A tool runs a program on your files: a program you already have (like ImageMagick) or one inside
  the add-on. That program can do anything a program can, so only turn on tools from people you
  trust. Joe runs it without a command shell, on copies of your files, with a time limit, and only
  keeps what it writes into the task's own folder.
- If an add-on's files change after you turned it on, Joe turns it off again until you look at it
  and say yes again.
- AI never turns an add-on on, and plans can only use tools you already turned on.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .fsutil import atomic_write_text

FOLDER = "Add-ons"
STATE = "_enabled.json"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
GROUPS = ("Writing", "Pictures", "Video", "Audio", "Files")
MAX_ZIP = 200_000_000           # uncompressed bytes
MAX_FILES = 2000
PLACEHOLDER = re.compile(r"\{(input|output|outdir|stem|ext|name|text|addon|option:[a-z0-9-]+|flag:[a-z0-9-]+:[^{}]*)\}")
JOE_PROGRAMS = ("joe:ffmpeg", "joe:python")   # the FFmpeg and the private Python Joe already uses
TOOL_PREFIX = "x-"              # add-on tools are TYPE: x-<id> so they never clash with Joe's own


class AddonError(ValueError):
    pass


# --------------------------------------------------------------------------- reading add-ons
def root(sb) -> Path:
    p = sb.root / FOLDER
    p.mkdir(parents=True, exist_ok=True)
    return p


def _state(sb) -> dict:
    try:
        d = json.loads((root(sb) / STATE).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(sb, d: dict) -> None:
    atomic_write_text(root(sb) / STATE, json.dumps(d, indent=1))


def _inside(base: Path, rel: str) -> Path:
    if not rel or rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel) or ".." in re.split(r"[\\/]", rel):
        raise AddonError(f"'{rel}' must be a file inside the add-on")
    p = (base / rel).resolve()
    try:
        p.relative_to(base.resolve())
    except ValueError:
        raise AddonError(f"'{rel}' points outside the add-on") from None
    return p


def _s(v, n: int = 300) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(v or "")).strip()[:n]


def read(folder: Path) -> dict:
    """addon.json, checked. Raises AddonError with a plain reason."""
    try:
        data = json.loads((folder / "addon.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AddonError("no addon.json in it") from None
    except (OSError, ValueError) as e:
        raise AddonError(f"addon.json can't be read ({e})") from None
    if not isinstance(data, dict):
        raise AddonError("addon.json must be one JSON object")
    aid = str(data.get("id", "")).strip().lower()
    if not ID_RE.match(aid):
        raise AddonError("its id must be 2-40 small letters, numbers or dashes (like magick-tools)")
    a = {"id": aid, "name": _s(data.get("name") or aid, 60), "version": _s(data.get("version"), 20),
         "author": _s(data.get("author"), 80), "about": _s(data.get("about"), 600),
         "homepage": _s(data.get("homepage"), 200), "license": _s(data.get("license"), 40),
         "tools": [], "packs": [], "workflows": [], "themes": [], "folder": folder}
    if a["homepage"] and not re.match(r"^https://", a["homepage"]):
        a["homepage"] = ""
    for kind, ext in (("packs", ".txt"), ("workflows", ".json"), ("themes", ".json")):
        for rel in data.get(kind) or []:
            p = _inside(folder, str(rel))
            if not p.is_file() or p.suffix.lower() != ext:
                raise AddonError(f"{kind}: {rel} isn't a {ext} file in the add-on")
            a[kind].append(p)
    seen = set()
    for t in data.get("tools") or []:
        if not isinstance(t, dict):
            raise AddonError("each tool must be a JSON object")
        tid = str(t.get("id", "")).strip().lower()
        if not ID_RE.match(tid) or tid in seen:
            raise AddonError(f"tool id '{tid}' must be 2-40 small letters, numbers or dashes, and different from the others")
        seen.add(tid)
        prog = str(t.get("program", "")).strip()
        args = t.get("args") or []
        if not prog or not isinstance(args, list) or not all(isinstance(x, str) for x in args):
            raise AddonError(f"tool {tid}: needs a program and an args list of words")
        accepts = tuple(sorted({("." + str(e).lower().lstrip(".")) for e in (t.get("accepts") or []) if str(e).strip()}))
        if not accepts:
            raise AddonError(f"tool {tid}: accepts must list the kinds of file it reads (like [\".png\", \".jpg\"])")
        opts = []
        for o in t.get("options") or []:
            key = str(o.get("key", "")).strip().lower() if isinstance(o, dict) else ""
            if not ID_RE.match(key):
                raise AddonError(f"tool {tid}: an option key must be small letters, numbers or dashes")
            choices = [(str(c[0]).strip().lower(), _s(c[1], 40)) for c in (o.get("choices") or [])
                       if isinstance(c, (list, tuple)) and len(c) == 2 and re.match(r"^[a-z0-9.%-]{1,20}$", str(c[0]).strip().lower())]
            opts.append({"key": key, "label": _s(o.get("label") or key, 50), "default": bool(o.get("default", False)),
                         "hint": _s(o.get("hint"), 200), "choices": choices,
                         "value": str(o.get("value") or (choices[0][0] if choices else "")).lower()})
        for x in args:
            for m in re.finditer(r"\{[^{}]*\}", x):
                if not PLACEHOLDER.fullmatch(m.group(0)):
                    raise AddonError(f"tool {tid}: {m.group(0)} isn't a placeholder Joe knows (see docs/ADDONS.md)")
        out = str(t.get("output") or "{stem}-" + tid + ".{ext}")
        if "/" in out or "\\" in out or ".." in out:
            raise AddonError(f"tool {tid}: output must be a plain file name")
        group = str(t.get("group") or "Files").title()
        a["tools"].append({
            "id": tid, "type": f"{TOOL_PREFIX}{tid}", "name": _s(t.get("name") or tid, 50),
            "group": group if group in GROUPS else "Files", "blurb": _s(t.get("blurb"), 160),
            "help": _s(t.get("help"), 800), "examples": [_s(x, 80) for x in (t.get("examples") or [])][:3],
            "accepts": accepts, "options": opts, "program": prog, "args": list(args), "output": out,
            "timeout": max(10, min(int(t.get("timeout") or 600), 6 * 3600)),
            "text": bool(t.get("text")), "text_label": _s(t.get("text_label"), 50)})
    if not (a["tools"] or a["packs"] or a["workflows"] or a["themes"]):
        raise AddonError("it doesn't add anything (no tools, packs, workflows or themes)")
    return a


def program_path(a: dict, tool: dict) -> tuple[Path | None, bool]:
    """(where the program is, inside the add-on?). None when it isn't installed on this PC."""
    prog = tool["program"]
    if prog == "joe:python":
        import sys
        return Path(sys.executable), False
    if prog == "joe:ffmpeg":
        from .doctor import ffmpeg_exe
        from .config import Settings
        found = ffmpeg_exe(Settings.load().comfy.ffmpeg)
        return (Path(found) if found else None), False
    if prog.startswith("joe:"):
        return None, False
    if "/" in prog or "\\" in prog:
        try:
            p = _inside(a["folder"], prog)
        except AddonError:
            return None, True
        return (p if p.is_file() else None), True
    found = shutil.which(prog)
    return (Path(found) if found else None), False


def fingerprint(a: dict) -> str:
    """Changes when addon.json or anything in the add-on folder changes."""
    h = hashlib.sha256()
    base = a["folder"]
    for p in sorted(base.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(base)).replace("\\", "/").encode())
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def scan(sb) -> list[dict]:
    """Every add-on folder, with its state: on, off, changed (turned off), or broken."""
    st = _state(sb)
    out = []
    for folder in sorted(p for p in root(sb).iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        try:
            a = read(folder)
        except AddonError as e:
            out.append({"id": folder.name, "name": folder.name, "state": "broken", "problem": str(e), "folder": folder})
            continue
        rec = st.get(a["id"]) or {}
        a["state"] = "off"
        if rec.get("on"):
            a["state"] = "on" if rec.get("fp") == fingerprint(a) else "changed"
        out.append(a)
    return out


def describe(a: dict) -> dict:
    """What Setup > Add-ons shows (plain data, nothing secret)."""
    if a.get("state") == "broken":
        return {"id": a["id"], "name": a["name"], "state": "broken", "problem": a["problem"]}
    tools = []
    for t in a["tools"]:
        p, inside = program_path(a, t)
        tools.append({"name": t["name"], "type": t["type"], "blurb": t["blurb"], "accepts": list(t["accepts"]),
                      "program": str(p) if p else t["program"], "installed": bool(p), "inside": inside,
                      "command": " ".join([t["program"]] + t["args"])})
    return {"id": a["id"], "name": a["name"], "version": a["version"], "author": a["author"], "about": a["about"],
            "homepage": a["homepage"], "license": a["license"], "state": a["state"], "tools": tools,
            "packs": [p.name for p in a["packs"]], "workflows": [p.name for p in a["workflows"]],
            "themes": [p.name for p in a["themes"]]}


# --------------------------------------------------------------------------- turning on and off
def _copies(sb, a: dict) -> list[tuple[Path, Path]]:
    """(from, to) for the add-on's data files, named so they're easy to spot as the add-on's."""
    pairs = []
    for p in a["packs"]:
        pairs.append((p, sb.missions / "Packs" / f"{a['id']}--{p.name}"))
    for p in a["workflows"]:
        pairs.append((p, sb.workflows / f"{a['id']}--{p.name}"))
    for p in a["themes"]:
        pairs.append((p, sb.themes / f"{a['id']}--{p.name}"))
    return pairs


def _check_workflow(p: Path) -> str:
    from . import comfy as comfy_mod
    try:
        g = comfy_mod.parse_template(p.read_text(encoding="utf-8", errors="replace"), p.stem)
    except Exception as e:                       # noqa: BLE001 (any parse problem = refuse it)
        return f"{p.name}: {e}"
    return comfy_mod.check_template(g) or ""


def enable(sb, aid: str, on: bool, log=print) -> dict:
    found = {a["id"]: a for a in scan(sb)}
    a = found.get(aid)
    if a is None:
        return {"ok": False, "error": "That add-on isn't in the Add-ons folder any more."}
    if a.get("state") == "broken":
        return {"ok": False, "error": f"That add-on can't be used: {a['problem']}"}
    st = _state(sb)
    pairs = _copies(sb, a)
    if on:
        for p in a["workflows"]:
            problem = _check_workflow(p)
            if problem:
                return {"ok": False, "error": f"A picture workflow in it didn't pass Joe's check: {problem}"}
        for src, dst in pairs:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        st[aid] = {"on": True, "fp": fingerprint(a), "when": datetime.now().isoformat(timespec="minutes"),
                   "copies": [str(d.relative_to(sb.root)).replace("\\", "/") for _, d in pairs]}
        log(f"Add-on turned on: {a['name']}" + (f" ({len(a['tools'])} tool(s))" if a["tools"] else ""))
    else:
        for rel in (st.get(aid) or {}).get("copies", []):
            try:
                (sb.root / rel).unlink()
            except OSError:
                pass
        st.pop(aid, None)
        log(f"Add-on turned off: {a['name']}")
    _save_state(sb, st)
    refresh(sb)
    return {"ok": True}


def remove(sb, aid: str, log=print) -> dict:
    if not ID_RE.match(aid or ""):
        return {"ok": False, "error": "unknown add-on"}
    enable(sb, aid, False, log=lambda *_: None)
    folder = root(sb) / aid
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)
    st = _state(sb)
    st.pop(aid, None)
    _save_state(sb, st)
    refresh(sb)
    log(f"Add-on removed: {aid}")
    return {"ok": True}


def install_zip(sb, data: bytes, log=print) -> dict:
    """A .zip of an add-on into Add-ons/<id>/ (it stays off). Safe unpacking: no paths outside
    the folder, no links, size and count limits."""
    import io
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return {"ok": False, "error": "That isn't a .zip file."}
    infos = [i for i in z.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_ZIP:
        return {"ok": False, "error": "That add-on is too big (over 200 MB or 2000 files)."}
    names = [i.filename.replace("\\", "/") for i in infos]
    if any(n.startswith("/") or re.match(r"^[A-Za-z]:", n) or ".." in n.split("/") for n in names):
        return {"ok": False, "error": "That .zip has files that would land outside the add-on folder. Joe won't open it."}
    if any((i.external_attr >> 16) & 0o170000 == 0o120000 for i in infos):
        return {"ok": False, "error": "That .zip has links in it. Joe won't open it."}
    top = ""
    if "addon.json" not in names:
        heads = {n.split("/")[0] for n in names}
        if len(heads) == 1 and f"{next(iter(heads))}/addon.json" in names:
            top = next(iter(heads)) + "/"
        else:
            return {"ok": False, "error": "No addon.json in that .zip, so it isn't a Joe add-on."}
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        for i, n in zip(infos, names):
            if not n.startswith(top):
                continue
            rel = n[len(top):]
            if not rel:
                continue
            dst = (t / rel).resolve()
            dst.relative_to(t.resolve())
            dst.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
        try:
            a = read(t)
        except AddonError as e:
            return {"ok": False, "error": f"That add-on can't be used: {e}"}
        dest = root(sb) / a["id"]
        was_on = (_state(sb).get(a["id"]) or {}).get("on")
        if dest.exists():
            enable(sb, a["id"], False, log=lambda *_: None)
            shutil.rmtree(dest)
        shutil.copytree(t, dest)
    refresh(sb)
    log(f"Add-on added (off until you turn it on): {a['name']}")
    return {"ok": True, "id": a["id"], "name": a["name"], "replaced": bool(was_on),
            "say": f"Added {a['name']}. It stays off until you look at what it does and turn it on."}


# --------------------------------------------------------------------------- tools in Joe's Tools tab
_registered: set[str] = set()
_by_type: dict[str, tuple[dict, dict]] = {}


def refresh(sb) -> None:
    """Put the tools of add-ons that are on into Joe's tool list (and take the others out)."""
    from . import tools as tools_mod
    for typ in list(_registered):
        tools_mod.TOOLS.pop(typ, None)
    _registered.clear()
    _by_type.clear()
    for a in scan(sb):
        if a.get("state") != "on":
            continue
        for t in a["tools"]:
            if t["type"] in tools_mod.TOOLS:
                continue
            opts = tuple(tools_mod.Option(o["key"], o["label"], o["default"], o["hint"],
                                          tuple(tuple(c) for c in o["choices"]), o["value"]) for o in t["options"])
            ex = ", ".join(t["accepts"])
            tools_mod.TOOLS[t["type"]] = tools_mod.Tool(
                t["type"], t["name"], t["group"], t["blurb"] or f"From the add-on {a['name']}.",
                accepts=t["accepts"], options=opts, ready=True,
                help=(t["help"] + "\n\n" if t["help"] else "") + f"An add-on tool from {a['name']}"
                     + (f" by {a['author']}" if a["author"] else "") + f". It runs: {t['program']}.",
                plan_hint=(f"Add-on tool '{t['name']}' ({t['blurb'] or 'from ' + a['name']}): TYPE: {t['type']}, "
                           f"INPUT: the file(s) ({ex})"
                           + (f", OPTIONS: {', '.join(o['key'] + (' ' + '|'.join(c[0] for c in o['choices']) if o['choices'] else '') for o in t['options'])}" if t["options"] else "")
                           + (", FORMAT: what they asked for" if t["text"] else "") + ". No CHUNKS."),
                examples=tuple(t["examples"]), extra_label=t["text_label"] if t["text"] else "")
            _registered.add(t["type"])
            _by_type[t["type"]] = (a, t)


def is_addon_tool(typ: str) -> bool:
    return typ in _by_type


_JOE_PATH = re.compile(r"^\{(?:input|outdir|output|addon)\}")


def command_line(tool: dict, program: Path, src: Path, outdir: Path, opts: set[str], values: dict, text: str,
                 addon_dir: Path | None = None) -> list[str]:
    stem, ext = src.stem, src.suffix.lstrip(".")
    out_name = tool["output"].replace("{stem}", stem).replace("{ext}", ext).replace("{name}", src.name)
    out_name = re.sub(r"\{option:([a-z0-9-]+)\}", lambda m: values.get(m.group(1), ""), out_name)
    out_name = re.sub(r"[\\/:*?\"<>|]", "_", out_name) or f"{stem}-out.{ext}"
    cmd = [str(program)] + (["-I"] if tool["program"] == "joe:python" else [])
    for x in tool["args"]:
        tmpl = x
        flag = re.fullmatch(r"\{flag:([a-z0-9-]+):([^{}]*)\}", x)
        if flag:                                   # a tick box: the words only when it's ticked
            if flag.group(1) in opts:
                cmd += [w for w in flag.group(2).split(" ") if w]
            continue
        x = x.replace("{input}", str(src)).replace("{outdir}", str(outdir)).replace("{output}", str(outdir / out_name))
        x = x.replace("{stem}", stem).replace("{ext}", ext).replace("{name}", src.name).replace("{text}", text)
        x = x.replace("{addon}", str(addon_dir) if addon_dir else "")
        x = re.sub(r"\{option:([a-z0-9-]+)\}", lambda m: values.get(m.group(1), ""), x)
        if x.startswith("-") and not tmpl.startswith("-"):
            # a typed text, a file name or a choice filled in here must never turn into an option
            # for the program (like "--output=..." or "-rf"): refuse instead of guessing
            raise ValueError(f"the words given for {tmpl} start with '-', which the program would read "
                             "as a switch; start them with something else")
        lead = x[:1]
        if lead in ("/", "@") and not tmpl.startswith(lead) and not _JOE_PATH.match(tmpl):
            # the same for "/" (a switch for many Windows programs, like /Q) and "@" (ImageMagick and
            # others read the rest as a file name and use that file's contents). Joe's own paths
            # ({input}, {output}...) are absolute and may start with "/" on Mac and Linux: those are fine.
            raise ValueError(f"the words given for {tmpl} start with '{lead}', which the program could read "
                             + ("as a switch" if lead == "/" else "as 'read this file'")
                             + "; start them with something else")
        cmd.append(x)
    return cmd


def run(engine, mission, job, st):
    """Run an add-on tool on each INPUT file: copies in, the program, results out."""
    from .engine import Stopped
    from .tools import _finish, _key, chosen_options, option_value, resolve_inputs, tool_dir
    a, tool = _by_type[job.type]
    program, _inside_addon = program_path(a, tool)
    if program is None:
        st.status = "failed"
        st.note = (f"this add-on tool needs the program '{tool['program']}', which isn't on this PC"
                   + (f" (see {a['homepage']})" if a["homepage"] else ""))
        engine.log(f"'{job.name}' failed: {st.note}")
        engine._save_state(job, st)
        return st
    files, problems = resolve_inputs(engine, job)
    for p in problems:
        engine.log(f"  INPUT: {p}")
    if not files:
        st.status, st.note = "failed", "no files to work on (put them in the Inbox)"
        engine.log(f"'{job.name}' failed: {st.note}")
        engine._save_state(job, st)
        return st
    folder = tool_dir(engine, job, st)
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"Starting '{job.name}' (add-on tool {tool['name']} from {a['name']}) -> {st.output}")
    opts = chosen_options(job)
    values = {o["key"]: option_value(job, o["key"]) for o in tool["options"] if o["choices"]}
    text = (job.format or "").strip()[:2000] if tool["text"] else ""
    failed = []
    try:
        for src in files:
            if engine.stop.is_set():
                raise Stopped()
            key = _key(engine, src)
            if key in st.titles:
                continue
            engine._progress(f"{job.name}: {src.name}")
            with tempfile.TemporaryDirectory() as tmp:
                work, outdir = Path(tmp) / "in", Path(tmp) / "out"
                work.mkdir()
                outdir.mkdir()
                copy = work / src.name                   # the program never touches your original
                shutil.copy2(src, copy)
                try:
                    cmd = command_line(tool, program, copy, outdir, opts, values, text, a["folder"])
                except ValueError as e:
                    failed.append(f"{src.name}: {e}")
                    engine.log(f"  {src.name}: {e}")
                    continue
                try:
                    r = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                       timeout=tool["timeout"], stdin=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                except subprocess.TimeoutExpired:
                    failed.append(f"{src.name}: took longer than {tool['timeout']} s")
                    continue
                except OSError as e:
                    failed.append(f"{src.name}: couldn't start the program ({e})")
                    continue
                if r.returncode != 0:
                    tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or ["no message"]
                    failed.append(f"{src.name}: the program said: {tail[0][:200]}")
                    engine.log(f"  {src.name}: exit {r.returncode}: {tail[0][:200]}")
                    continue
                made = []
                for p in sorted(outdir.rglob("*")):
                    if p.is_file():
                        rel = p.relative_to(outdir)
                        dst = folder / rel
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(p), dst)
                        made.append(str(rel).replace("\\", "/"))
                if not made:
                    failed.append(f"{src.name}: the program finished but made no file")
                    continue
            st.titles.append(key)
            st.media_files.extend(made)
            st.items += 1
            engine._save_state(job, st)
            engine.log(f"  {src.name} -> {', '.join(made)}")
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} file(s)"
        engine._save_state(job, st)
        return st
    return _finish(engine, job, st, len(files), failed)
