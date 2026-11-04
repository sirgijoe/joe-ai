"""Joe's tools: ready-made jobs that work on the person's own files (recordings, photos,
documents) instead of writing from scratch.

Every tool is reached three ways, all running the same code here:
  1. Just ask: the "What do you need?" box writes `TYPE: <tool id>` tasks (describe.py).
  2. The Tools tab (F7): a card per tool opens a short form (drop files, pick options, RUN).
  3. Missions: `TASK: Meeting notes  TYPE: transcribe  INPUT: tools/meeting.mp3`.

A tool task reads its files from Inbox (INPUT: files or folders), saves into a folder under
Output, and resumes file by file if a run stops. OPTIONS picks extras (comma-separated).

The registry below also lists planned tools so the Tools tab can show what's coming; only
tools with `ready=True` can run.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .fsutil import atomic_write_text
from .items import count_words, find_flags

if TYPE_CHECKING:                                    # pragma: no cover
    from .engine import Engine, JobState
    from .mission import Job, Mission

AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wma", ".amr")
VIDEO_IN_EXT = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv", ".3gp")
UPLOAD_MAX_BYTES = 8 * 1024 ** 3                  # 8 GB per file for the Tools form


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    default: bool = True
    hint: str = ""


@dataclass(frozen=True)
class Tool:
    id: str
    name: str                   # card title, plain words
    group: str                  # Writing | Pictures | Video | Audio | Files
    blurb: str                  # one line on the card
    accepts: tuple[str, ...] = ()
    options: tuple[Option, ...] = ()
    needs: tuple[str, ...] = ()          # voice | ollama | ffmpeg | comfy | vision
    ready: bool = False
    help: str = ""                       # shown in the form
    plan_hint: str = ""                  # one line for the describe planner
    examples: tuple[str, ...] = field(default_factory=tuple)


TOOLS: dict[str, Tool] = {t.id: t for t in (
    Tool("transcribe", "Transcribe a recording", "Audio",
         "Turn audio or video into text, subtitles and short notes.",
         accepts=AUDIO_EXT + VIDEO_IN_EXT,
         options=(Option("subtitles", "Subtitles file (.srt)", True,
                         "For video players and YouTube."),
                  Option("notes", "Notes: summary, key points, to-dos", True,
                         "Written by the writing model from the transcript.")),
         needs=("voice", "ffmpeg"), ready=True,
         help="English recordings for now. Uses the Hearing setting (Setup > Voice & Talk): "
              "Most accurate is slower but makes fewer mistakes. Runs on the processor, so it "
              "can work while pictures are drawing. Roughly real time on Balanced.",
         plan_hint="Transcribe: TYPE: transcribe, INPUT: the recording file(s) from the list "
                   "below, OPTIONS: subtitles, notes (leave out what they don't want). No CHUNKS.",
         examples=("Turn my meeting recording into notes", "Make subtitles for this video")),
    Tool("read-aloud", "Read a document aloud", "Audio",
         "Turn writing into an MP3 you can listen to.", needs=("voice",)),
    Tool("proofread", "Proofread my writing", "Writing",
         "Fix spelling and grammar, with a list of every change.", needs=("ollama",)),
    Tool("translate", "Translate", "Writing",
         "Make a copy of finished text in another language.", needs=("ollama",)),
    Tool("ask-files", "Ask my files", "Writing",
         "Answers and summaries from a folder of your documents.", needs=("ollama",)),
    Tool("tidy-sheet", "Tidy a spreadsheet", "Files",
         "Fix duplicates, spelling and categories in a CSV.", needs=("ollama",)),
    Tool("photo-batch", "Resize and convert photos", "Files",
         "Shrink, convert, rename or watermark a folder of photos.", needs=("ffmpeg",)),
    Tool("read-scans", "Read scans and receipts", "Files",
         "Pull the text out of scans, receipts and forms.", needs=("vision",)),
    Tool("photo-listing", "Listings from photos", "Pictures",
         "Titles, descriptions, tags and alt text from product photos.", needs=("vision",)),
    Tool("sort-photos", "Sort my photos", "Pictures",
         "Tag and sort a folder of pictures by what's in them.", needs=("vision",)),
    Tool("remove-bg", "Remove background and upscale", "Pictures",
         "Clean, sharp product shots.", needs=("comfy",)),
    Tool("edit-picture", "Edit a picture by asking", "Pictures",
         "\"Swap the background\", \"remove the cup\".", needs=("comfy",)),
    Tool("restore-photo", "Restore old photos", "Pictures",
         "Fix scratches and faces, add color.", needs=("comfy",)),
    Tool("animate-photo", "Animate a photo", "Video",
         "Turn one of your photos into a short clip.", needs=("comfy",)),
    Tool("music", "Music and sound effects", "Audio",
         "Background music and short jingles.", needs=("comfy",)),
)}
GROUPS = ("Writing", "Pictures", "Video", "Audio", "Files")


def ready_ids() -> tuple[str, ...]:
    return tuple(t.id for t in TOOLS.values() if t.ready)


def is_tool(type_: str) -> bool:
    return type_ in TOOLS


def catalog() -> list[dict]:
    """What the Tools tab shows."""
    return [{"id": t.id, "name": t.name, "group": t.group, "blurb": t.blurb, "ready": t.ready,
             "accepts": list(t.accepts), "help": t.help, "examples": list(t.examples),
             "options": [{"key": o.key, "label": o.label, "default": o.default, "hint": o.hint}
                         for o in t.options]}
            for t in TOOLS.values()]


def planner_lines() -> str:
    return "\n".join(f"- {t.plan_hint}" for t in TOOLS.values() if t.ready and t.plan_hint)


def chosen_options(job: "Job") -> set[str]:
    tool = TOOLS[job.type]
    if job.options:
        return {o for o in job.options if any(o == x.key for x in tool.options)}
    return {o.key for o in tool.options if o.default}


# --------------------------------------------------------------------------- inputs
def inbox_media(sb, kinds: tuple[str, ...] = AUDIO_EXT + VIDEO_IN_EXT, limit: int = 40) -> list[str]:
    """Recordings waiting in Inbox (newest first), as INPUT paths, for the describe planner."""
    out = []
    try:
        files = [p for p in sb.inbox.rglob("*") if p.is_file() and p.suffix.lower() in kinds]
    except OSError:
        return []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[:limit]:
        out.append(str(p.relative_to(sb.inbox)).replace("\\", "/"))
    return out


def resolve_inputs(engine: "Engine", job: "Job") -> tuple[list[Path], list[str]]:
    """INPUT entries -> files this tool accepts (folders are expanded). Returns (files, problems)."""
    from .sandbox import SandboxError
    tool = TOOLS[job.type]
    files: list[Path] = []
    problems: list[str] = []
    for rel in job.inputs:
        try:
            p = engine.sb.resolve(rel, base="Inbox")
        except SandboxError as e:
            problems.append(f"{rel}: {e}")
            continue
        if p.is_dir():
            found = sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in tool.accepts)
            if not found:
                problems.append(f"{rel}: no files Joe can use in that folder")
            files.extend(found)
        elif p.is_file():
            if p.suffix.lower() in tool.accepts:
                files.append(p)
            else:
                problems.append(f"{rel}: {p.suffix or 'that kind of file'} isn't something this tool reads")
        else:
            problems.append(f"{rel}: not found in Inbox")
    seen: set[Path] = set()
    unique = [f for f in files if not (f in seen or seen.add(f))]
    return unique, problems


def tool_dir(engine: "Engine", job: "Job", st: "JobState") -> Path:
    """The task's output folder; resuming reuses it, a new run never mixes with an old one."""
    if st.output and st.titles:
        p = engine.sb.resolve(st.output)
        p.mkdir(parents=True, exist_ok=True)
        return p
    target = engine.sb.resolve(job.save)
    if target.suffix:
        target = target.with_suffix("")
    cand, n = target, 2
    while cand.exists() and any(cand.iterdir()):
        cand = target.with_name(f"{target.name}_v{n}")
        n += 1
    cand.mkdir(parents=True, exist_ok=True)
    st.output = str(cand.relative_to(engine.sb.output)).replace("\\", "/")
    return cand


# --------------------------------------------------------------------------- run
def run(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    fn = {"transcribe": run_transcribe}.get(job.type)
    if not fn:
        st.status, st.note = "failed", f"the {TOOLS[job.type].name} tool isn't built yet"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    return fn(engine, mission, job, st)


def _finish(engine: "Engine", job: "Job", st: "JobState", total: int, failed: list[str]) -> "JobState":
    from dataclasses import asdict  # noqa: F401  (keeps the import local like the engine)
    done = len(st.titles)
    st.parts_total = total
    st.parts_done = done
    st.status = "done" if done == total and not failed else ("partial" if done else "failed")
    if failed:
        st.note = "; ".join(failed)[:400]
    st.finished = datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"Finished '{job.name}': {done} of {total} file(s)" + (f" ({st.note})" if failed else ""))
    return st


# --------------------------------------------------------------------------- transcribe
NOTES_SYSTEM = """You write clear notes from a transcript of a recording. Use only what is said in
the transcript. Never invent names, numbers, dates or decisions; if something is unclear, write
[CHECK]. Plain, friendly English. Markdown headings and bullet points."""
NOTES_FORMAT = """Write:
## Summary
3-6 sentences.
## Key points
Bullet points.
## Decisions
Bullet points, or "None mentioned."
## To-dos
Bullet points with who and when if said, or "None mentioned."
"""
NOTES_CHUNK_WORDS = 2500


def _ts(seconds: float, srt: bool = False) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    if srt:
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def transcript_text(segments: list[dict], title: str) -> str:
    """Readable transcript: a [mm:ss] stamp at the start of each paragraph. A new paragraph
    starts after a pause of 2+ seconds or about 120 words."""
    out = [f"# {title}", ""]
    para: list[str] = []
    start = 0.0
    last_end = None
    words = 0
    for seg in segments:
        text = (seg.get("t") or "").strip()
        if not text:
            continue
        gap = seg["s"] - last_end if last_end is not None else 0
        if para and (gap >= 2.0 or words >= 120):
            out += [f"[{_ts(start)}] " + " ".join(para), ""]
            para, words = [], 0
        if not para:
            start = seg["s"]
        para.append(text)
        words += len(text.split())
        last_end = seg["e"]
    if para:
        out += [f"[{_ts(start)}] " + " ".join(para), ""]
    return "\n".join(out)


def srt_text(segments: list[dict]) -> str:
    blocks = []
    n = 0
    for seg in segments:
        text = (seg.get("t") or "").strip()
        if not text:
            continue
        n += 1
        end = max(seg["e"], seg["s"] + 0.5)
        blocks.append(f"{n}\n{_ts(seg['s'], True)} --> {_ts(end, True)}\n{text}\n")
    return "\n".join(blocks)


def _to_wav(ffmpeg: str | None, src: Path, dest: Path, log) -> Path | None:
    """16 kHz mono WAV for Whisper. A .wav goes straight through when there's no FFmpeg."""
    if not ffmpeg:
        return src if src.suffix.lower() == ".wav" else None
    from .system import no_window_flags
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        p = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1",
                            "-ar", "16000", "-c:a", "pcm_s16le", str(dest)],
                           capture_output=True, text=True, timeout=7200,
                           creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError) as e:
        log(f"  FFmpeg couldn't read {src.name}: {e}")
        return None
    if p.returncode != 0 or not dest.exists():
        log(f"  FFmpeg couldn't read {src.name}: {(p.stderr or '').strip()[-200:]}")
        return None
    return dest


def _wav_seconds(p: Path) -> float:
    try:
        return max(0.0, (p.stat().st_size - 44) / 32000)       # 16 kHz, 16-bit, mono
    except OSError:
        return 0.0


def _notes(engine: "Engine", job: "Job", st: "JobState", title: str, transcript: str) -> str:
    """Notes from the transcript; long recordings are noted in pieces, then combined."""
    words = transcript.split()
    pieces = [" ".join(words[i:i + NOTES_CHUNK_WORDS])
              for i in range(0, len(words), NOTES_CHUNK_WORDS)] or [""]
    extra = (job.format.strip() + "\n") if job.format.strip() else ""
    rules = (job.rules.strip() + "\n") if job.rules.strip() else ""
    if len(pieces) == 1:
        r = engine._chat(job, 0, "transcribe-notes", NOTES_SYSTEM + "\n" + rules,
                         f"Recording: {title}\n\n{NOTES_FORMAT}{extra}\nTRANSCRIPT:\n{pieces[0]}", st)
        return r.text.strip()
    partial = []
    for i, piece in enumerate(pieces):
        engine._progress(f"{job.name}: notes for {title}, piece {i + 1}/{len(pieces)}")
        r = engine._chat(job, i, "transcribe-notes", NOTES_SYSTEM + "\n" + rules,
                         f"Recording: {title} (piece {i + 1} of {len(pieces)})\n"
                         "Write bullet-point notes of everything important in this piece.\n\n"
                         f"TRANSCRIPT PIECE:\n{piece}", st)
        partial.append(r.text.strip())
    r = engine._chat(job, len(pieces), "transcribe-notes", NOTES_SYSTEM + "\n" + rules,
                     f"Recording: {title}\nThese are notes from each piece of one long recording, "
                     f"in order. Combine them.\n\n{NOTES_FORMAT}{extra}\nNOTES:\n" + "\n\n".join(partial), st)
    return r.text.strip()


def run_transcribe(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .addons import VoiceWorker, voice_python
    from .doctor import ffmpeg_exe
    from .engine import PartFailed, Stopped
    from .mission import slug

    files, problems = resolve_inputs(engine, job)
    for pr in problems:
        engine.log(f"  INPUT: {pr}")
    if not files:
        st.status, st.note = "failed", ("no recordings to transcribe" + (f" ({problems[0]})" if problems else
                                        "; add them with INPUT: (files or a folder in Inbox)"))
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    if not Path(voice_python()).exists() and engine.voice is None:
        st.status, st.note = "failed", "transcribing needs Joe's voice add-on (Setup > System check)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    ffmpeg = ffmpeg_exe(engine.s.comfy.ffmpeg)
    if not ffmpeg and any(f.suffix.lower() != ".wav" for f in files):
        engine.log("  FFmpeg isn't installed, so only .wav recordings can be read "
                   "(Setup > System check installs it).")
    folder = tool_dir(engine, job, st)
    opts = chosen_options(job)
    worker = engine.voice or VoiceWorker(engine.log)
    model = engine.s.voice.stt_model or "base.en"
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}': {len(files)} recording(s) "
               f"-> {st.output} (hearing: {model})")
    notes_ok = None                                    # checked once, only if notes are wanted
    failed: list[str] = []
    tmp = engine.meta / "tmp"
    try:
        for i, src in enumerate(files):
            key = str(src.relative_to(engine.sb.inbox)).replace("\\", "/")
            if key in st.titles:
                continue                                # done in an earlier run
            if engine.stop.is_set():
                raise Stopped()
            engine._progress(f"{job.name}: {i + 1}/{len(files)} {src.name}")
            engine.log(f"  {i + 1}/{len(files)} {src.name}: reading the sound...")
            wav = _to_wav(ffmpeg, src, tmp / (slug(src.stem) + ".wav"), engine.log)
            if not wav:
                failed.append(f"{src.name}: couldn't read the sound")
                continue
            secs = _wav_seconds(wav)
            engine.log(f"  {src.name}: transcribing about {max(1, round(secs / 60))} min of sound...")
            t0 = datetime.now()
            r = worker.call({"cmd": "transcribe", "audio": str(wav), "stt_model": model},
                            timeout=max(900.0, secs * 4 + 600))
            if wav != src:
                try:
                    wav.unlink()
                except OSError:
                    pass
            if not r.get("ok"):
                failed.append(f"{src.name}: {r.get('error', 'transcribing failed')}"[:200])
                engine.log(f"  {src.name}: {r.get('error', 'transcribing failed')}")
                continue
            segs = r.get("segments") or []
            stem = slug(src.stem) or f"recording-{i + 1}"
            body = transcript_text(segs, src.stem)
            atomic_write_text(folder / f"{stem}.txt", body)
            made = [f"{stem}.txt"]
            if "subtitles" in opts:
                atomic_write_text(folder / f"{stem}.srt", srt_text(segs))
                made.append(f"{stem}.srt")
            words = sum(count_words(s.get("t", "")) for s in segs)
            took = (datetime.now() - t0).total_seconds()
            engine._record(job=job.job_id, part=i + 1, kind="transcribe", model=model, ok=True,
                           seconds=round(took, 1), audio_seconds=round(secs, 1), words=words)
            if "notes" in opts and words:
                if notes_ok is None:
                    notes_ok = engine._text_ready(st)
                    if not notes_ok:
                        st.status, st.note = "running", ""
                        engine.log("  Notes skipped: the writing model isn't available.")
                if notes_ok:
                    try:
                        notes = _notes(engine, job, st, src.stem,
                                       " ".join(s.get("t", "").strip() for s in segs))
                        atomic_write_text(folder / f"{stem}-notes.md", f"# Notes: {src.stem}\n\n{notes}\n")
                        made.append(f"{stem}-notes.md")
                        st.flags.extend({"item": src.stem, "flag": f} for f in find_flags(notes))
                    except PartFailed as e:
                        failed.append(f"{src.name}: notes skipped ({e})")
            st.titles.append(key)
            st.media_files.extend(made)
            st.items += 1
            st.words += words
            engine._save_state(job, st)
            engine.log(f"  {src.name}: {words} words in {round(took / 60, 1)} min -> {', '.join(made)}")
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {len(files)} recording(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    return _finish(engine, job, st, len(files), failed)


# --------------------------------------------------------------------------- uploads
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def upload_target(sb, tool_id: str, name: str) -> Path:
    """Where a file dropped on a tool's form goes: Inbox/tools/<tool>/<name> (never overwrites)."""
    folder = sb.inbox / "tools" / tool_id
    folder.mkdir(parents=True, exist_ok=True)
    clean = _BAD.sub("_", Path(name or "file").name).strip(" .")[:120] or "file"
    target = folder / clean
    stem, ext, n = target.stem, target.suffix, 2
    while target.exists():
        target = folder / f"{stem}_{n}{ext}"
        n += 1
    sb.check(target)
    return target


def mission_for(tool_id: str, files: list[str], options: list[str], name: str = "",
                extra: str = "") -> str:
    """The mission a Tools-tab form runs (also shown under ADVANCED)."""
    tool = TOOLS[tool_id]
    task = (name or tool.name).replace("\n", " ").strip()[:80]
    lines = [f"TASK: {task}  TYPE: {tool.id}", "INPUT: " + ", ".join(files)]
    if tool.options:
        lines.append("OPTIONS: " + (", ".join(options) if options else "none"))
    if extra.strip():
        lines.append("FORMAT: " + extra.strip().replace("\n", " "))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- planning
# Rough minutes of sound per MB, to guess run time before a file is opened.
_MIN_PER_MB = {".wav": 0.5, ".flac": 1 / 5, ".mp4": 1 / 8, ".mov": 1 / 10, ".mkv": 1 / 8,
               ".webm": 1 / 6, ".avi": 1 / 10, ".m4v": 1 / 8, ".wmv": 1 / 8, ".3gp": 1 / 3}


def plan_info(engine_sb, job: "Job", speeds: dict) -> dict:
    """For App.check(): files found, a time guess, and problems that would stop the task."""
    from .sandbox import SandboxError
    tool = TOOLS[job.type]
    files: list[Path] = []
    problems: list[str] = []
    for rel in job.inputs:
        try:
            p = engine_sb.resolve(rel, base="Inbox")
        except SandboxError as e:
            problems.append(f"{rel}: {e}")
            continue
        if p.is_dir():
            files += [f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in tool.accepts]
        elif p.is_file() and p.suffix.lower() in tool.accepts:
            files.append(p)
        else:
            problems.append(f"{rel}: not found in Inbox, or not a kind of file this tool reads")
    secs = 0.0
    if job.type == "transcribe":
        for f in files:
            try:
                mb = f.stat().st_size / 1e6
            except OSError:
                continue
            audio_min = mb * _MIN_PER_MB.get(f.suffix.lower(), 1.0)
            secs += audio_min * 60 * speeds.get("transcribe", 0.8)
            if "notes" in chosen_options(job):
                secs += max(1, audio_min / 20) * speeds.get("part", 25.0)
    return {"files": len(files), "seconds": secs, "problems": problems}


def needs_problem(settings, job: "Job") -> str:
    """Why this tool can't run on this PC yet ('' = fine)."""
    tool = TOOLS[job.type]
    if "voice" in tool.needs:
        from .addons import voice_python
        if not Path(voice_python()).exists():
            return (f"Task '{job.name}': {tool.name.lower()} needs Joe's voice add-on first. "
                    "Setup (F10) > System check > \"Joe's voice\" > SET UP.")
    return ""
