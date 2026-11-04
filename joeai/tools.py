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
DOC_EXT = (".txt", ".md", ".markdown", ".docx", ".pdf", ".html", ".htm")
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")
LANGUAGES = (("spanish", "Spanish"), ("french", "French"), ("german", "German"),
             ("italian", "Italian"), ("portuguese", "Portuguese"), ("dutch", "Dutch"),
             ("polish", "Polish"), ("russian", "Russian"), ("ukrainian", "Ukrainian"),
             ("greek", "Greek"), ("turkish", "Turkish"), ("arabic", "Arabic"), ("hebrew", "Hebrew"),
             ("hindi", "Hindi"), ("bengali", "Bengali"), ("chinese", "Chinese (Simplified)"),
             ("japanese", "Japanese"), ("korean", "Korean"), ("vietnamese", "Vietnamese"),
             ("thai", "Thai"), ("indonesian", "Indonesian"), ("tagalog", "Tagalog"),
             ("swahili", "Swahili"), ("english", "English"))
UPLOAD_MAX_BYTES = 8 * 1024 ** 3                  # 8 GB per file for the Tools form


@dataclass(frozen=True)
class Option:
    """A tick box (OPTIONS: subtitles), or with `choices` a pick-one list written as
    'key value' (OPTIONS: size 1600). `value` is the choice used when nothing is said."""
    key: str
    label: str
    default: bool = True
    hint: str = ""
    choices: tuple[tuple[str, str], ...] = ()       # (value, plain label)
    value: str = ""
    multi: bool = False                              # several picks allowed ("to spanish, to french")
    required: bool = False                           # at least one pick needed (no default)


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
    extra_hint: str = ""                 # placeholder for the form's "Anything else?" box
    mark: bool = False                   # takes WATERMARK: (text or a logo .png), only if asked


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
         "Turn writing into an MP3 you can listen to.",
         accepts=DOC_EXT,
         options=(Option("chapters", "One track per chapter", False,
                         "Splits at headings like '# Title' or 'Chapter 3'. Handy for long documents."),),
         needs=("voice", "ffmpeg"), ready=True,
         help="Uses Joe's voice and speed from Setup > Voice & Talk (your own copied voice isn't "
              "used here yet). Runs on the processor, so it can work while pictures are drawing. "
              "Without FFmpeg Joe saves WAV files (much bigger) instead of MP3. Reading PDFs needs "
              "Joe's voice add-on. Long books take a while: a stopped run picks up where it left off.",
         plan_hint="Read aloud (document -> MP3): TYPE: read-aloud, INPUT: the document file(s) "
                   "from the list below, OPTIONS: chapters (only if they want one track per "
                   "chapter, else none). No CHUNKS.",
         examples=("Read my short story aloud as an MP3", "Turn this guide into an audiobook"),
         extra_hint="optional, e.g. skip the table of contents"),
    Tool("proofread", "Proofread my writing", "Writing",
         "Fix spelling and grammar, with a list of every change.",
         accepts=DOC_EXT,
         options=(Option("clarity", "Also suggest clearer wording", False,
                         "Off: only real mistakes (spelling, grammar, punctuation). On: also "
                         "awkward or unclear sentences."),
                  Option("copy", "Corrected copy", True,
                         "A fixed copy next to the change list. Your original file is never changed.")),
         needs=("ollama",), ready=True,
         help="Joe lists every change with the before and after, so nothing is changed silently, "
              "and your original file is never touched. Word files come back as a text copy "
              "(plus a Word copy if Pandoc is installed); formatting like fonts isn't kept. "
              "Reading PDFs needs Joe's voice add-on.",
         plan_hint="Proofread (spelling/grammar with a change list): TYPE: proofread, INPUT: the "
                   "document file(s) from the list below, OPTIONS: copy, plus clarity only if "
                   "they want wording suggestions too. No CHUNKS.",
         examples=("Proofread my cover letter", "Check the grammar in my newsletter"),
         extra_hint="optional, e.g. British spelling, keep the casual tone"),
    Tool("translate", "Translate", "Writing",
         "Make a copy of finished text in another language.",
         accepts=DOC_EXT,
         options=(Option("to", "Into", hint="Pick one or more. Each language gets its own copy.",
                         choices=LANGUAGES, multi=True, required=True),),
         needs=("ollama",), ready=True,
         help="Translated by the writing model on this PC, so nothing leaves it. Quality depends "
              "on the model: big languages work best. Anything Joe isn't sure about is marked "
              "[CHECK]. Have someone who speaks the language read it before you publish it. Your "
              "original is never changed. Word files come back as text (plus Word with Pandoc).",
         plan_hint="Translate finished writing: TYPE: translate, INPUT: the document file(s) from "
                   "the list below, OPTIONS: to <language> for each language (e.g. to spanish, to "
                   "french). Languages: " + ", ".join(v for v, _ in LANGUAGES) + ". No CHUNKS.",
         examples=("Translate my menu into Spanish", "Make French and German copies of this flyer"),
         extra_hint="optional, e.g. formal tone, Latin American Spanish"),
    Tool("ask-files", "Ask my files", "Writing",
         "Answers and summaries from a folder of your documents.", needs=("ollama",)),
    Tool("tidy-sheet", "Tidy a spreadsheet", "Files",
         "Fix duplicates, spelling and categories in a CSV.", needs=("ollama",)),
    Tool("photo-batch", "Resize and convert photos", "Files",
         "Shrink, convert, rename or watermark a folder of photos.",
         accepts=PHOTO_EXT,
         options=(Option("size", "Longest side", hint="Photos are only ever made smaller, never stretched.",
                         choices=(("keep", "Keep the size"), ("800", "Small: 800 px (email, chat)"),
                                  ("1200", "Medium: 1200 px"), ("1600", "Web: 1600 px (shops, sites)"),
                                  ("2400", "Large: 2400 px")), value="1600"),
                  Option("format", "Save as", hint="JPG: photos, small files. WebP: smaller still, "
                         "for websites. PNG: sharp edges and see-through backgrounds, big files.",
                         choices=(("same", "Same as now"), ("jpg", "JPG"), ("webp", "WebP"),
                                  ("png", "PNG")), value="same"),
                  Option("rename", "Rename in order (name-01, name-02...)", False,
                         "Uses the job name. Off: each photo keeps its own name."),
                  Option("corner", "Watermark spot", hint="Only used when you give a watermark.",
                         choices=(("bottom-right", "Bottom right"), ("bottom-left", "Bottom left"),
                                  ("top-right", "Top right"), ("top-left", "Top left"),
                                  ("center", "Middle")), value="bottom-right")),
         needs=("ffmpeg",), ready=True, mark=True,
         help="Your originals are never changed: new copies go in Output. A watermark is only "
              "added if you type one (or pick a logo .png); it's faint, in the spot you choose. "
              "Hidden photo details like the camera and GPS location are left out of the copies. "
              "Needs FFmpeg (Setup > System check). iPhone HEIC photos aren't supported yet: save "
              "them as JPG first.",
         plan_hint="Resize/convert photos: TYPE: photo-batch, INPUT: the photo file(s) or folder "
                   "from the list below, OPTIONS: size 800|1200|1600|2400|keep, format "
                   "same|jpg|webp|png, rename (only if asked), corner bottom-right|bottom-left|"
                   "top-right|top-left|center (only with a watermark). WATERMARK: the exact text, "
                   "ONLY if they asked for a watermark. No CHUNKS.",
         examples=("Shrink my product photos for the website", "Convert these photos to JPG"),
         extra_hint=""),
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
             "needs": list(t.needs), "extra_hint": t.extra_hint, "mark": t.mark,
             "options": [{"key": o.key, "label": o.label, "default": o.default, "hint": o.hint,
                          "choices": [list(c) for c in o.choices], "value": o.value, "multi": o.multi}
                         for o in t.options]}
            for t in TOOLS.values()]


def planner_lines() -> str:
    return "\n".join(f"- {t.plan_hint}" for t in TOOLS.values() if t.ready and t.plan_hint)


def option_ok(tool: Tool, token: str) -> bool:
    """Is this OPTIONS entry one the tool knows ('none', a tick box, or 'key value')?"""
    if token == "none":
        return True
    key, _, val = token.partition(" ")
    for o in tool.options:
        if o.key == key:
            return (val in {c[0] for c in o.choices}) if o.choices else not val
    return False


def missing_required(tool: Tool, tokens: list[str]) -> str:
    """A plain problem when a must-pick option (like the language) wasn't given ('' = fine)."""
    for o in tool.options:
        if o.required and not any(t.partition(" ")[0] == o.key and t.partition(" ")[2] for t in tokens):
            if tool.id == "translate":
                return "say which language to translate into, e.g. OPTIONS: to spanish (on the Tools tab, tick a language)"
            return f"pick a {o.label.lower()} (OPTIONS: {o.key} ...)"
    return ""


def options_help(tool: Tool) -> str:
    out = []
    for o in tool.options:
        out.append(f"{o.key} {'|'.join(c[0] for c in o.choices)}" if o.choices else o.key)
    return ", ".join(out + ["none"])


def chosen_options(job: "Job") -> set[str]:
    """Tick boxes that are on. With no OPTIONS line, each box's default is used."""
    tool = TOOLS[job.type]
    boxes = [o for o in tool.options if not o.choices]
    if job.options:
        return {t for t in job.options if any(t == o.key for o in boxes)}
    return {o.key for o in boxes if o.default}


def option_values(job: "Job", key: str) -> list[str]:
    """Every pick for a several-picks option ('to' -> ['spanish', 'french']), in order."""
    out = []
    for t in job.options:
        k, _, v = t.partition(" ")
        if k == key and v and v not in out:
            out.append(v)
    return out


def option_value(job: "Job", key: str) -> str:
    """The pick for a pick-one option ('size' -> '1600'), or its default."""
    for t in job.options:
        k, _, v = t.partition(" ")
        if k == key and v:
            return v
    return next((o.value for o in TOOLS[job.type].options if o.key == key), "")


# --------------------------------------------------------------------------- inputs
def tool_exts() -> tuple[str, ...]:
    """Every kind of file a ready tool reads."""
    return tuple(sorted({e for t in TOOLS.values() if t.ready for e in t.accepts}))


def inbox_media(sb, kinds: tuple[str, ...] | None = None, limit: int = 40) -> list[str]:
    """Files waiting in Inbox that tools can use (newest first), as INPUT paths, for the
    describe planner. `kinds` narrows it (default: everything a ready tool reads)."""
    kinds = kinds or tool_exts()
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
    fn = {"transcribe": run_transcribe, "read-aloud": run_read_aloud,
          "proofread": run_proofread, "photo-batch": run_photo_batch,
          "translate": run_translate}.get(job.type)
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


# --------------------------------------------------------------------------- documents
DOC_LIMIT = 3_000_000                 # characters read from one document (a whole book)
RAW_TEXT_EXT = (".txt", ".md", ".markdown")


def document_text(src: Path, log) -> str:
    """All the words in a document. Plain text and Markdown come back exactly as written
    (so a proofread copy changes nothing but the fixes); Word, PDF and web pages are
    read with the same code as Talk attachments. Raises ValueError if it can't be read."""
    if src.suffix.lower() in RAW_TEXT_EXT:
        raw = src.read_bytes()
        if b"\x00" in raw[:4096]:
            raise ValueError("that file isn't plain text")
        return raw.decode("utf-8-sig", "replace").replace("\r\n", "\n")
    from .attach import extract
    return extract(src, log, limit=DOC_LIMIT)["text"]


def _guess_words(f: Path) -> int:
    """A quick word count for time guesses, without reading the whole document."""
    try:
        size = f.stat().st_size
    except OSError:
        return 0
    ext = f.suffix.lower()
    if ext == ".docx":
        try:
            from .attach import _docx_text
            return count_words(_docx_text(f))
        except Exception:                               # noqa: BLE001 (a guess only)
            return size // 20
    if ext == ".pdf":
        return max(200, size // 60)
    if ext in (".html", ".htm"):
        return size // 12
    return size // 6


# --------------------------------------------------------------------------- read aloud
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+|www\.\S+")
_FLAG = re.compile(r"\[(?:CHECK|TODO|TK)\b[^\]]*\]", re.I)
_BULLET = re.compile(r"^([-*+•]|\d+[.)])\s+")
_CHAPTER = re.compile(r"^(?:#{1,2}[ \t]+\S[^\n]*|(?:chapter|part)[ \t]+(?:\d+|[ivxlc]+|one|two|three|four|"
                      r"five|six|seven|eight|nine|ten|eleven|twelve)\b[^\n]{0,80})$", re.I | re.M)
SPEECH_PIECE = 4500                   # characters per call to the voice helper (it takes 6000)
LISTEN_WPM = 160                      # words per minute of speech, for time guesses


def speakable(text: str) -> str:
    """Writing -> words worth saying: no Markdown symbols, links, code blocks or [CHECK]
    marks; titles and list lines end with a full stop so the voice pauses."""
    text = re.sub(r"(?s)```.*?```", " ", text)
    out: list[str] = []
    for line in text.splitlines():
        ln = line.strip()
        if not ln:
            out.append("")
            continue
        if re.fullmatch(r"[-*_=|:+\s]{3,}", ln):        # rules and table separator lines
            continue
        heading = bool(re.match(r"#{1,6}\s", ln))
        ln = re.sub(r"^#{1,6}\s*", "", ln)
        ln = re.sub(r"^>\s*", "", ln)
        listed = bool(_BULLET.match(ln))
        ln = _BULLET.sub("", ln)
        if ln.count("|") >= 2:                           # a table row: say the cells
            ln = ", ".join(c.strip() for c in ln.strip("|").split("|") if c.strip())
            listed = True
        ln = _MD_LINK.sub(r"\1", ln)
        ln = _URL.sub("", ln)
        ln = _FLAG.sub("", ln)
        ln = re.sub(r"[*`~]+|(?<!\w)_+|_+(?!\w)", "", ln)
        ln = re.sub(r"\s{2,}", " ", ln).strip()
        if not ln:
            continue
        if (heading or listed) and ln[-1] not in ".!?:;,":
            ln += "."
        out += ["", ln, ""] if heading else [ln]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def speech_pieces(text: str, size: int = SPEECH_PIECE) -> list[str]:
    """Paragraphs grouped into pieces the voice helper can say in one go."""
    out: list[str] = []
    cur = ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        while len(para) > size:                          # a huge paragraph: cut at a sentence
            cut = max(para.rfind(". ", 0, size), para.rfind("? ", 0, size), para.rfind("! ", 0, size))
            if cut < size // 3:
                cut = para.rfind(" ", 0, size)
            if cut <= 0:
                cut = size - 1
            if cur:
                out.append(cur)
                cur = ""
            out.append(para[:cut + 1].strip())
            para = para[cut + 1:].strip()
        if cur and len(cur) + len(para) + 2 > size:
            out.append(cur)
            cur = para
        else:
            cur = (cur + "\n\n" + para).strip()
    if cur:
        out.append(cur)
    return out


def split_sections(text: str) -> list[tuple[str, str]]:
    """(title, text) per chapter, split at '# Title' / '## Title' / 'Chapter 3' lines.
    Fewer than two such lines = one section."""
    marks = [m.start() for m in _CHAPTER.finditer(text)]
    if len(marks) < 2:
        return [("", text)]
    out = []
    if text[:marks[0]].strip():
        out.append(("Opening", text[:marks[0]]))
    for a, b in zip(marks, marks[1:] + [len(text)]):
        part = text[a:b]
        out.append((part.splitlines()[0].lstrip("#").strip(), part))
    return out


def _wav_ok(p: Path) -> bool:
    try:
        return p.stat().st_size > 44
    except OSError:
        return False


def merge_wavs(parts: list[Path], dest: Path, pause: float = 0.45) -> float:
    """Join WAV pieces (same format) with a short pause between them. Returns seconds."""
    import wave
    fmt = None
    frames = 0
    with wave.open(str(dest), "wb") as out:
        for i, p in enumerate(parts):
            with wave.open(str(p), "rb") as w:
                f = (w.getnchannels(), w.getsampwidth(), w.getframerate())
                if fmt is None:
                    fmt = f
                    out.setnchannels(f[0])
                    out.setsampwidth(f[1])
                    out.setframerate(f[2])
                elif f != fmt:
                    raise ValueError(f"{p.name} is a different kind of WAV")
                if i:
                    gap = int(fmt[2] * pause)
                    out.writeframes(b"\x00" * gap * fmt[0] * fmt[1])
                    frames += gap
                n = w.getnframes()
                out.writeframes(w.readframes(n))
                frames += n
    return frames / fmt[2] if fmt else 0.0


def to_mp3(ffmpeg: str, wav: Path, mp3: Path, title: str, log) -> bool:
    from .system import no_window_flags
    try:
        p = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(wav), "-codec:a", "libmp3lame",
                            "-q:a", "4", "-metadata", f"title={title[:120]}",
                            "-metadata", "artist=Read aloud by Joe", str(mp3)],
                           capture_output=True, text=True, timeout=3600,
                           creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError) as e:
        log(f"  FFmpeg couldn't make the MP3: {e}")
        return False
    if p.returncode != 0 or not mp3.exists():
        log(f"  FFmpeg couldn't make the MP3: {(p.stderr or '').strip()[-200:]}")
        return False
    return True


def _voice_missing(engine: "Engine", job: "Job", st: "JobState", what: str) -> bool:
    from .addons import voice_python
    if not Path(voice_python()).exists() and engine.voice is None:
        st.status, st.note = "failed", f"{what} needs Joe's voice add-on (Setup > System check)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return True
    return False


def _no_files(engine: "Engine", job: "Job", st: "JobState", what: str) -> "JobState | None":
    files, problems = resolve_inputs(engine, job)
    for pr in problems:
        engine.log(f"  INPUT: {pr}")
    if files:
        return None
    st.status, st.note = "failed", (f"no {what}" + (f" ({problems[0]})" if problems else
                                    "; add them with INPUT: (files or a folder in Inbox)"))
    engine.log(f"'{job.name}' failed: {st.note}")
    return st


def run_read_aloud(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    import hashlib
    import shutil
    import wave

    from .addons import VOICES, VoiceWorker
    from .doctor import ffmpeg_exe
    from .engine import Stopped
    from .mission import slug

    if (bad := _no_files(engine, job, st, "documents to read")) is not None:
        return bad
    if _voice_missing(engine, job, st, "reading aloud"):
        return st
    files, _ = resolve_inputs(engine, job)
    ffmpeg = ffmpeg_exe(engine.s.comfy.ffmpeg)
    if not ffmpeg:
        engine.log("  FFmpeg isn't installed, so Joe saves WAV files (much bigger) instead of MP3 "
                   "(Setup > System check installs it).")
    folder = tool_dir(engine, job, st)
    opts = chosen_options(job)
    worker = engine.voice or VoiceWorker(engine.log)
    v = engine.s.voice
    voice = v.voice if v.voice in VOICES else "am_adam"
    if v.voice == "mine":
        engine.log(f"  Your own voice isn't used for reading aloud yet, so Joe reads with {voice}.")
    speed = float(v.speed or 1.0)
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}': {len(files)} document(s) "
               f"-> {st.output} (voice: {voice})")
    failed: list[str] = []
    work = engine.meta / "tmp" / "read-aloud" / job.job_id
    try:
        for i, src in enumerate(files):
            key = str(src.relative_to(engine.sb.inbox)).replace("\\", "/")
            if key in st.titles:
                continue
            if engine.stop.is_set():
                raise Stopped()
            engine._progress(f"{job.name}: {i + 1}/{len(files)} {src.name}")
            try:
                raw = document_text(src, engine.log)
            except (ValueError, OSError) as e:
                failed.append(f"{src.name}: {e}"[:200])
                engine.log(f"  {src.name}: {e}")
                continue
            sections = split_sections(raw) if "chapters" in opts else [("", raw)]
            plan = [(title, pcs) for title, body in sections if (pcs := speech_pieces(speakable(body)))]
            if not plan:
                failed.append(f"{src.name}: no words to read")
                engine.log(f"  {src.name}: no words to read")
                continue
            total = sum(len(p) for _, p in plan)
            words = sum(count_words(x) for _, p in plan for x in p)
            engine.log(f"  {i + 1}/{len(files)} {src.name}: {words} words, about "
                       f"{max(1, round(words / LISTEN_WPM))} min of listening"
                       + (f" in {len(plan)} tracks" if len(plan) > 1 else ""))
            stem = slug(src.stem) or f"document-{i + 1}"
            sig = hashlib.sha1(f"{raw}|{voice}|{speed}|{sorted(opts)}".encode("utf-8", "replace")).hexdigest()[:10]
            tmp = work / f"{stem}-{sig}"                 # finished pieces survive a stop
            tmp.mkdir(parents=True, exist_ok=True)
            t0 = datetime.now()
            made: list[str] = []
            audio = 0.0
            n = 0
            broke = ""
            for si, (title, pcs) in enumerate(plan):
                wavs = []
                for pi, text in enumerate(pcs):
                    if engine.stop.is_set():
                        raise Stopped()
                    n += 1
                    w = tmp / f"s{si + 1:03d}-p{pi + 1:04d}.wav"
                    if not _wav_ok(w):
                        engine._progress(f"{job.name}: {src.name}, piece {n}/{total}")
                        r = worker.call({"cmd": "tts", "text": text, "out": str(w), "voice": voice,
                                         "speed": speed}, timeout=max(600.0, len(text) * 0.5))
                        if not r.get("ok") or not _wav_ok(w):
                            broke = r.get("error") or "the voice didn't make any sound"
                            break
                    wavs.append(w)
                if broke:
                    break
                name = stem if len(plan) == 1 else \
                    f"{stem}-{si + 1:02d}" + (f"-{slug(title)[:40]}" if slug(title) else "")
                merged = tmp / f"{name}.wav"
                try:
                    audio += merge_wavs(wavs, merged)
                except (OSError, ValueError, EOFError, wave.Error) as e:
                    broke = f"couldn't join the pieces: {e}"
                    break
                label = (title or src.stem) if len(plan) > 1 else src.stem
                if ffmpeg and to_mp3(ffmpeg, merged, folder / f"{name}.mp3", label, engine.log):
                    made.append(f"{name}.mp3")
                else:
                    shutil.move(str(merged), str(folder / f"{name}.wav"))
                    made.append(f"{name}.wav")
            if broke:
                failed.append(f"{src.name}: {broke}"[:200])
                engine.log(f"  {src.name}: {broke}")
                continue                                 # pieces kept: a re-run carries on
            took = (datetime.now() - t0).total_seconds()
            engine._record(job=job.job_id, part=i + 1, kind="read-aloud", model=f"kokoro:{voice}",
                           ok=True, seconds=round(took, 1), audio_seconds=round(audio, 1), words=words)
            shutil.rmtree(tmp, ignore_errors=True)
            st.titles.append(key)
            st.media_files.extend(made)
            st.items += 1
            st.words += words
            engine._save_state(job, st)
            engine.log(f"  {src.name}: {round(audio / 60, 1)} min of speech in {round(took / 60, 1)} min "
                       f"-> {', '.join(made)}")
    except Stopped:
        st.status, st.note = "stopped", (f"stopped after {len(st.titles)} of {len(files)} document(s); "
                                         "finished pieces are kept, so the next run carries on")
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    return _finish(engine, job, st, len(files), failed)


# --------------------------------------------------------------------------- proofread
PROOF_SYSTEM = """You are a careful proofreader. You fix real mistakes only: spelling, grammar,
punctuation, wrong or missing words, repeated words.{clarity} You never rewrite the writing in
your own style: keep the writer's voice, tone, word choices, spelling style and formatting.
Never add facts. Reply with ONLY a JSON array, nothing before or after it."""
PROOF_CLARITY = (" You may also fix sentences that are confusing or awkward, changing as few "
                 "words as you can.")
PROOF_ASK = """Proofread the text between <<< and >>>.
For each fix, give one object:
  {"find": "the exact words from the text, copied exactly, enough words to be unique",
   "replace": "the corrected words",
   "why": "a few plain words, e.g. spelling"}
If something might be wrong but you aren't sure, put the same words in find and replace and say
why in "why". If there is nothing to fix, reply [].
"""
PROOF_WORDS = 600                     # words per model call
MAX_FIND = 400                        # longer "find"s are rewrites, not fixes: never applied


def proof_chunks(text: str, words: int = PROOF_WORDS) -> list[str]:
    """Paragraph groups of about `words` words; "".join(chunks) == text exactly."""
    bits = re.split(r"(\n[ \t]*\n)", text)
    out: list[str] = []
    cur, n = "", 0
    for b in bits:
        w = count_words(b)
        if cur and n + w > words and b.strip():
            out.append(cur)
            cur, n = "", 0
        cur += b
        n += w
    if cur:
        out.append(cur)
    return out


def parse_changes(raw: str) -> list[dict] | None:
    """The model's JSON list of fixes, or None if the reply isn't one."""
    import json
    raw = re.sub(r"(?s)<think>.*?</think>", "", raw or "")
    raw = re.sub(r"```[\w-]*", "", raw)
    a, b = raw.find("["), raw.rfind("]")
    if a < 0 or b < a:
        return None
    try:
        arr = json.loads(raw[a:b + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(arr, list):
        return None
    return [{"find": o["find"], "replace": o["replace"], "why": str(o.get("why") or "").strip()[:120]}
            for o in arr if isinstance(o, dict) and isinstance(o.get("find"), str)
            and isinstance(o.get("replace"), str) and o["find"].strip()]


def apply_changes(text: str, changes: list[dict], first_par: int = 1) -> tuple[str, list, list, list]:
    """Apply exact-match fixes. Returns (text, applied, noted, missed); each change gets a
    paragraph number ("par"). Nothing is changed that isn't on the applied list."""
    applied, noted, missed = [], [], []
    for c in changes:
        f, r = c["find"], c["replace"]
        pos = text.find(f)
        par = first_par + (len(re.findall(r"\n[ \t]*\n", text[:pos])) if pos >= 0 else 0)
        c = dict(c, par=par if pos >= 0 else 0)
        if f == r:
            noted.append(c)
        elif len(f) > MAX_FIND:
            missed.append(dict(c, reason="too much to change at once"))
        elif pos < 0:
            missed.append(dict(c, reason="couldn't find those exact words"))
        else:
            text = text[:pos] + r + text[pos + len(f):]
            applied.append(c)
    return text, applied, noted, missed


def _q(s: str) -> str:
    s = " ".join(s.split())
    return "“" + (s if len(s) <= 300 else s[:297] + "...") + "”"


def changes_report(title: str, applied: list, noted: list, missed: list, copy_name: str,
                   skipped: list[int]) -> str:
    n = len(applied)
    lines = [f"# Proofread: {title}", "",
             f"{n} change{'' if n == 1 else 's'}. Your original file was not changed."
             + (f" The corrected copy is {copy_name}." if copy_name and n else ""), ""]
    if skipped:
        lines += [f"Joe couldn't check part(s) {', '.join(map(str, skipped))} of this document "
                  "(the model's answer didn't make sense). Those parts are unchanged.", ""]
    lines += ["## Changes", ""]
    lines += [f"{i}. Paragraph {c['par']}" + (f" ({c['why']})" if c["why"] else "") +
              f": {_q(c['find'])} → {_q(c['replace'])}" for i, c in enumerate(applied, 1)] or ["None needed."]
    if noted:
        lines += ["", "## Worth a look (not changed)", ""]
        lines += [f"- " + (f"Paragraph {c['par']}: " if c["par"] else "") + _q(c["find"]) +
                  (f": {c['why']}" if c["why"] else "") for c in noted]
    if missed:
        lines += ["", "## Suggestions Joe couldn't apply (check these yourself)", ""]
        lines += [f"- {_q(c['find'])} → {_q(c['replace'])}" + (f" ({c['why']})" if c["why"] else "") +
                  f": {c['reason']}" for c in missed]
    return "\n".join(lines) + "\n"


def run_proofread(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .addons import export_document, pandoc_exe
    from .engine import PartFailed, Stopped
    from .mission import slug

    if (bad := _no_files(engine, job, st, "documents to proofread")) is not None:
        return bad
    files, _ = resolve_inputs(engine, job)
    if not engine._text_ready(st):
        engine._save_state(job, st)
        return st
    folder = tool_dir(engine, job, st)
    opts = chosen_options(job)
    system = PROOF_SYSTEM.replace("{clarity}", PROOF_CLARITY if "clarity" in opts else "")
    if job.rules.strip():
        system += "\n" + job.rules.strip()
    wish = f"The writer asked: {job.format.strip()}\n" if job.format.strip() else ""
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}': {len(files)} document(s) "
               f"-> {st.output}" + (" (also clearer wording)" if "clarity" in opts else ""))
    failed: list[str] = []
    try:
        for i, src in enumerate(files):
            key = str(src.relative_to(engine.sb.inbox)).replace("\\", "/")
            if key in st.titles:
                continue
            if engine.stop.is_set():
                raise Stopped()
            try:
                text = document_text(src, engine.log)
            except (ValueError, OSError) as e:
                failed.append(f"{src.name}: {e}"[:200])
                engine.log(f"  {src.name}: {e}")
                continue
            if not text.strip():
                failed.append(f"{src.name}: no words to check")
                continue
            chunks = proof_chunks(text)
            words = count_words(text)
            engine.log(f"  {i + 1}/{len(files)} {src.name}: {words} words in {len(chunks)} part(s)")
            fixed: list[str] = []
            applied, noted, missed, skipped = [], [], [], []
            par = 1
            for ci, chunk in enumerate(chunks):
                if engine.stop.is_set():
                    raise Stopped()
                engine._progress(f"{job.name}: {src.name}, part {ci + 1}/{len(chunks)}")
                changes = None
                if chunk.strip():
                    ask = f"{wish}{PROOF_ASK}\n<<<\n{chunk.strip()}\n>>>"
                    try:
                        for attempt in range(2):
                            r = engine._chat(job, ci, "proofread", system, ask if not attempt else
                                             ask + "\n\nReply with ONLY the JSON array.", st)
                            changes = parse_changes(r.text)
                            if changes is not None:
                                break
                            st.retries += 1
                    except PartFailed as e:
                        engine.log(f"  {src.name} part {ci + 1}: {e}")
                    if changes is None:
                        skipped.append(ci + 1)
                        changes = []
                new, a, nt, m = apply_changes(chunk, changes, par)
                fixed.append(new)
                applied += a
                noted += nt
                missed += m
                par += len(re.findall(r"\n[ \t]*\n", chunk))
            stem = slug(src.stem) or f"document-{i + 1}"
            ext = src.suffix.lower() if src.suffix.lower() in RAW_TEXT_EXT else ".md"
            made = []
            copy_name = ""
            if "copy" in opts:
                copy_name = f"{stem}-proofread{ext}"
                atomic_write_text(folder / copy_name, "".join(fixed))
                made.append(copy_name)
                if src.suffix.lower() == ".docx":
                    pandoc = pandoc_exe(engine.s.pandoc)
                    if pandoc:
                        made += [p.name for p in export_document(folder / copy_name, ["docx"], pandoc, engine.log)]
                    else:
                        engine.log("  Pandoc isn't installed, so the corrected copy is text, not Word.")
            atomic_write_text(folder / f"{stem}-changes.md",
                              changes_report(src.stem, applied, noted, missed, copy_name, skipped))
            made.insert(0, f"{stem}-changes.md")
            st.flags.extend({"item": src.stem, "flag": f"[CHECK] {c['why'] or 'worth a look'}: {c['find'][:80]}"}
                            for c in noted[:20])
            if skipped:
                failed.append(f"{src.name}: couldn't check part(s) {', '.join(map(str, skipped))}")
            st.titles.append(key)
            st.media_files.extend(made)
            st.items += 1
            st.words += words
            engine._save_state(job, st)
            engine.log(f"  {src.name}: {len(applied)} change(s), {len(noted)} to look at, "
                       f"{len(missed)} not applied -> {', '.join(made)}")
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {len(files)} document(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    return _finish(engine, job, st, len(files), failed)


# --------------------------------------------------------------------------- photo batch
MARK_OPACITY = 0.55                   # watermarks are faint: there to claim, not to ruin the photo


def jpeg_orientation(p: Path) -> int:
    """The EXIF 'which way is up' number (1-8) from a JPEG, or 1. Phones store photos
    sideways and set this, so copies must be turned the same way."""
    import struct
    try:
        with open(p, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                return 1
            while True:
                head = f.read(4)
                if len(head) < 4 or head[0] != 0xFF:
                    return 1
                marker, size = head[1], struct.unpack(">H", head[2:])[0]
                if marker == 0xE1:
                    data = f.read(size - 2)
                    if not data.startswith(b"Exif\x00\x00"):
                        continue
                    t = data[6:]
                    e = "<" if t[:2] == b"II" else ">"
                    off = struct.unpack(e + "I", t[4:8])[0]
                    n = struct.unpack(e + "H", t[off:off + 2])[0]
                    for i in range(n):
                        ent = t[off + 2 + i * 12: off + 14 + i * 12]
                        if struct.unpack(e + "H", ent[:2])[0] == 0x0112:
                            v = struct.unpack(e + "H", ent[8:10])[0]
                            return v if 1 <= v <= 8 else 1
                    return 1
                if marker in (0xDA, 0xD9):                  # picture data starts: no EXIF
                    return 1
                f.seek(size - 2, 1)
    except (OSError, struct.error, IndexError):
        return 1


_TURN = {2: "hflip", 3: "hflip,vflip", 4: "vflip", 5: "transpose=0", 6: "transpose=1",
         7: "transpose=3", 8: "transpose=2"}


def image_size(ffmpeg: str, p: Path) -> tuple[int, int] | None:
    from .system import no_window_flags
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-noautorotate", "-i", str(p)], capture_output=True,
                           text=True, timeout=60, creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", r.stderr or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def fit_size(w: int, h: int, longest: int | None) -> tuple[int, int]:
    """Shrink so the longest side is at most `longest` (never enlarge)."""
    if not longest or max(w, h) <= longest:
        return w, h
    k = longest / max(w, h)
    return max(1, round(w * k)), max(1, round(h * k))


def _ff_path(p: Path | str) -> str:
    """A path inside an FFmpeg filter: forward slashes, ':' and quotes escaped."""
    s = str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return f"'{s}'"


def _spot(corner: str, w: str, h: str, m: str) -> tuple[str, str]:
    """x, y expressions for a mark of size w x h with margin m."""
    x = {"left": m, "right": f"W-{w}-{m}"}.get(corner.split("-")[-1], f"(W-{w})/2")
    y = {"top": m, "bottom": f"H-{h}-{m}"}.get(corner.split("-")[0], f"(H-{h})/2")
    return x, y


def photo_command(ffmpeg: str, src: Path, dest: Path, size: tuple[int, int], turn: int,
                  fmt: str, mark_text_file: Path | None, logo: Path | None, font: Path | None,
                  corner: str) -> list[str]:
    """One FFmpeg call: turn the right way up, shrink, flatten see-through parts onto white
    for JPG, add a faint watermark if asked, leave hidden details (GPS, camera) out."""
    W, H = size
    cmd = [ffmpeg, "-y", "-v", "error", "-noautorotate", "-i", str(src)]
    chain = [f"[0:v]{_TURN[turn] + ',' if turn in _TURN else ''}scale={W}:{H}:flags=lanczos,format=rgba[a]"]
    last, n = "a", 1
    if fmt == "jpg":                                       # no see-through in JPG: white behind
        cmd += ["-f", "lavfi", "-i", f"color=c=white:s={W}x{H}:d=1"]
        chain.append(f"[{n}:v][{last}]overlay=format=auto,format=rgba[b]")
        last, n = "b", n + 1
    m = max(8, round(min(W, H) / 40))
    if logo:
        cmd += ["-i", str(logo)]
        lw = max(16, round(min(W, H) * 0.22))
        x, y = _spot(corner, "w", "h", str(m))
        chain.append(f"[{n}:v]scale={lw}:-1,format=rgba,colorchannelmixer=aa={MARK_OPACITY}[lg]")
        chain.append(f"[{last}][lg]overlay=x={x}:y={y}[c]")
        last, n = "c", n + 1
    elif mark_text_file and font:
        fs = max(12, round(min(W, H) / 20))
        x, y = _spot(corner, "tw", "th", str(m))
        chain.append(f"[{last}]drawtext=fontfile={_ff_path(font)}:textfile={_ff_path(mark_text_file)}"
                     f":expansion=none:fontsize={fs}:fontcolor=white@{MARK_OPACITY}:borderw={max(1, fs // 14)}"
                     f":bordercolor=black@{MARK_OPACITY * 0.6}:x={x}:y={y}[c]")
        last = "c"
    pix = {"jpg": "yuvj444p", "png": "rgba", "webp": "yuva420p"}.get(fmt, "rgba")
    if fmt == "bmp":
        pix = "bgr24"
    elif fmt == "tiff":
        pix = "rgba"
    chain.append(f"[{last}]format={pix}[out]")
    cmd += ["-filter_complex", ";".join(chain), "-map", "[out]", "-map_metadata", "-1",
            "-frames:v", "1", "-update", "1"]
    if fmt == "jpg":
        cmd += ["-q:v", "2"]
    elif fmt == "webp":
        cmd += ["-c:v", "libwebp", "-quality", "82"]
    elif fmt == "png":
        cmd += ["-compression_level", "9"]
    return cmd + [str(dest)]


def run_photo_batch(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .doctor import ffmpeg_exe
    from .engine import Stopped
    from .mission import slug
    from .sandbox import SandboxError
    from .system import font_file, no_window_flags

    if (bad := _no_files(engine, job, st, "photos to work on")) is not None:
        return bad
    files, _ = resolve_inputs(engine, job)
    ffmpeg = ffmpeg_exe(engine.s.comfy.ffmpeg)
    if not ffmpeg:
        st.status, st.note = "failed", "photo tools need FFmpeg (Setup > System check installs it)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    size_opt = option_value(job, "size")
    longest = int(size_opt) if size_opt.isdigit() else None
    fmt_opt = option_value(job, "format")
    corner = option_value(job, "corner") or "bottom-right"
    opts = chosen_options(job)
    logo = None
    text_file = None
    font = None
    mark = job.watermark.strip()
    if mark:
        if mark.lower().endswith(".png"):
            try:
                logo = engine.sb.resolve(mark, base="Inbox")
            except SandboxError:
                logo = None
            if not logo or not logo.is_file():
                st.status, st.note = "failed", f"the watermark logo {mark} isn't in Inbox"
                engine.log(f"'{job.name}' failed: {st.note}")
                return st
            files = [f for f in files if f != logo]           # the logo isn't one of the photos
        else:
            font = font_file()
            if not font:
                engine.log("  No font found on this computer, so the watermark text is left off.")
    folder = tool_dir(engine, job, st)
    if mark and not logo and font:
        text_file = engine.meta / "tmp" / f"mark-{job.job_id}.txt"
        text_file.parent.mkdir(parents=True, exist_ok=True)
        text_file.write_text(mark, encoding="utf-8")
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}': {len(files)} photo(s) -> {st.output} "
               f"({'keep size' if not longest else f'{longest} px'}, {fmt_opt}"
               + (f", watermark {corner}" if mark else "") + ")")
    failed: list[str] = []
    used = {p.name.lower() for p in folder.iterdir()} if folder.exists() else set()
    base = slug(job.name) or "photo"
    t0 = datetime.now()
    try:
        for i, src in enumerate(files):
            key = str(src.relative_to(engine.sb.inbox)).replace("\\", "/")
            if key in st.titles:
                continue
            if engine.stop.is_set():
                raise Stopped()
            engine._progress(f"{job.name}: {i + 1}/{len(files)} {src.name}")
            ext = src.suffix.lower().lstrip(".")
            fmt = {"jpeg": "jpg", "tif": "tiff"}.get(ext, ext) if fmt_opt == "same" else fmt_opt
            stem = f"{base}-{i + 1:0{max(2, len(str(len(files))))}d}" if "rename" in opts \
                else (slug(src.stem) or f"photo-{i + 1}")
            name, n = f"{stem}.{fmt}", 2
            while name.lower() in used:
                name, n = f"{stem}_{n}.{fmt}", n + 1
            dims = image_size(ffmpeg, src)
            if not dims:
                failed.append(f"{src.name}: couldn't open the picture")
                engine.log(f"  {src.name}: couldn't open the picture")
                continue
            turn = jpeg_orientation(src) if ext in ("jpg", "jpeg") else 1
            w, h = (dims[1], dims[0]) if turn >= 5 else dims
            out = fit_size(w, h, longest)
            cmd = photo_command(ffmpeg, src, folder / name, out, turn, fmt, text_file, logo, font, corner)
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                   creationflags=no_window_flags())
                ok = p.returncode == 0 and (folder / name).exists()
                err = (p.stderr or "").strip().splitlines()[-1:] if not ok else []
            except (OSError, subprocess.SubprocessError) as e:
                ok, err = False, [str(e)]
            if not ok:
                failed.append(f"{src.name}: {(err or ['FFmpeg failed'])[0][:160]}")
                engine.log(f"  {src.name}: FFmpeg failed: {(err or ['?'])[0][:200]}")
                continue
            used.add(name.lower())
            before, after = src.stat().st_size, (folder / name).stat().st_size
            st.titles.append(key)
            st.media_files.append(name)
            st.items += 1
            engine._save_state(job, st)
            engine.log(f"  {src.name} ({dims[0]}x{dims[1]}, {before // 1024} KB) -> {name} "
                       f"({out[0]}x{out[1]}, {after // 1024} KB)")
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {len(files)} photo(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    finally:
        if text_file:
            try:
                text_file.unlink()
            except OSError:
                pass
    engine._record(job=job.job_id, part=1, kind="photo-batch", model="ffmpeg", ok=True,
                   seconds=round((datetime.now() - t0).total_seconds(), 1), photos=len(st.titles))
    return _finish(engine, job, st, len(files), failed)


# --------------------------------------------------------------------------- translate
TRANSLATE_SYSTEM = """You are a careful translator. Translate the writer's text into {lang}.
Keep the meaning, tone and formatting exactly: the same paragraphs, Markdown headings, lists,
bold and tables. Keep names, brands, numbers, prices, dates, email addresses and links as they
are. Never add, explain or leave anything out. If a phrase can't be translated well (a joke,
an idiom, a word you don't know), translate it as well as you can and put [CHECK] right after it.
Reply with ONLY the translation."""
TRANSLATE_ASK = "Translate the text between <<< and >>> into {lang}.\n\n<<<\n{text}\n>>>"
TRANSLATE_WORDS = 400                 # words per model call (translations run long)
_PREAMBLE = re.compile(r"^\s*(?:sure|here(?:'s| is)|translation|okay|ok)\b[^\n]{0,80}:\s*\n", re.I)


def clean_translation(raw: str) -> str:
    """The model's reply without thinking, fences, a 'Here is the translation:' line or
    the <<< >>> marks it was shown."""
    t = re.sub(r"(?s)<think>.*?</think>", "", raw or "")
    t = _PREAMBLE.sub("", t.strip(), count=1)
    t = re.sub(r"^\s*```[\w-]*\n|\n```\s*$", "", t.strip())
    t = re.sub(r"^\s*<<<\s*\n?|\n?\s*>>>\s*$", "", t)
    return t.strip()


def language_name(v: str) -> str:
    return dict(LANGUAGES).get(v, v.capitalize())


def translation_note(lang: str, model: str) -> str:
    return (f"> Translated into {lang} by Joe on this computer ({model or 'the writing model'}). "
            "Machine translations make mistakes: have someone who speaks the language check it "
            "before you publish it. Unsure bits are marked [CHECK].\n\n")


def run_translate(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .addons import export_document, pandoc_exe
    from .engine import PartFailed, Stopped
    from .mission import slug

    if (bad := _no_files(engine, job, st, "documents to translate")) is not None:
        return bad
    files, _ = resolve_inputs(engine, job)
    langs = option_values(job, "to")
    if not langs:
        st.status, st.note = "failed", "no language picked (OPTIONS: to spanish)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    if not engine._text_ready(st):
        engine._save_state(job, st)
        return st
    folder = tool_dir(engine, job, st)
    wish = f"The writer asked: {job.format.strip()}\n" if job.format.strip() else ""
    total = len(files) * len(langs)
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}': {len(files)} document(s) into "
               f"{', '.join(language_name(x) for x in langs)} -> {st.output}")
    failed: list[str] = []
    model = getattr(engine, "text_model", "") or engine.s.ollama.text_model
    try:
        for i, src in enumerate(files):
            rel = str(src.relative_to(engine.sb.inbox)).replace("\\", "/")
            todo = [x for x in langs if f"{rel} -> {x}" not in st.titles]
            if not todo:
                continue
            try:
                text = document_text(src, engine.log)
            except (ValueError, OSError) as e:
                failed += [f"{src.name}: {e}"[:200]]
                engine.log(f"  {src.name}: {e}")
                continue
            if not text.strip():
                failed.append(f"{src.name}: no words to translate")
                continue
            chunks = proof_chunks(text, TRANSLATE_WORDS)
            words = count_words(text)
            stem = slug(src.stem) or f"document-{i + 1}"
            ext = src.suffix.lower() if src.suffix.lower() in RAW_TEXT_EXT else ".md"
            for lang in todo:
                if engine.stop.is_set():
                    raise Stopped()
                name = language_name(lang)
                system = TRANSLATE_SYSTEM.replace("{lang}", name)
                if job.rules.strip():
                    system += "\n" + job.rules.strip()
                engine.log(f"  {src.name} -> {name}: {words} words in {len(chunks)} part(s)")
                out: list[str] = []
                broke = ""
                for ci, chunk in enumerate(chunks):
                    if engine.stop.is_set():
                        raise Stopped()
                    body = chunk.strip()
                    if not body:
                        out.append(chunk)
                        continue
                    lead = chunk[:len(chunk) - len(chunk.lstrip())]
                    trail = chunk[len(chunk.rstrip()):]
                    engine._progress(f"{job.name}: {src.name} -> {name}, part {ci + 1}/{len(chunks)}")
                    got = ""
                    try:
                        for attempt in range(2):
                            ask = wish + TRANSLATE_ASK.format(lang=name, text=body)
                            if attempt:
                                ask += "\n\nReply with ONLY the translated text, nothing else."
                            r = engine._chat(job, ci, "translate", system, ask, st)
                            got = clean_translation(r.text)
                            # far shorter than the text = something left out (by letters, not
                            # words: Chinese and Japanese don't put spaces between words)
                            if got and len(got) >= len(body) * 0.2:
                                break
                            st.retries += 1
                    except PartFailed as e:
                        broke = str(e)
                        break
                    if not got:
                        broke = f"part {ci + 1} came back empty"
                        break
                    out.append(lead + got + trail)
                if broke:
                    failed.append(f"{src.name} -> {name}: {broke}"[:200])
                    engine.log(f"  {src.name} -> {name}: {broke}")
                    continue
                done = "".join(out)
                fname = f"{stem}-{slug(lang)}{ext}"
                atomic_write_text(folder / fname, translation_note(name, model) + done
                                  + ("" if done.endswith("\n") else "\n"))
                made = [fname]
                if src.suffix.lower() == ".docx":
                    pandoc = pandoc_exe(engine.s.pandoc)
                    if pandoc:
                        made += [p.name for p in export_document(folder / fname, ["docx"], pandoc, engine.log)]
                flags = find_flags(done)
                st.flags.extend({"item": f"{src.stem} ({name})", "flag": f} for f in flags[:30])
                st.titles.append(f"{rel} -> {lang}")
                st.media_files.extend(made)
                st.items += 1
                st.words += count_words(done)
                engine._save_state(job, st)
                engine.log(f"  {src.name} -> {name}: {', '.join(made)}"
                           + (f" ({len(flags)} [CHECK] mark(s) to look at)" if flags else ""))
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {total} translation(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    return _finish(engine, job, st, total, failed)


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
                extra: str = "", mark: str = "") -> str:
    """The mission a Tools-tab form runs (also shown under ADVANCED)."""
    tool = TOOLS[tool_id]
    task = (name or tool.name).replace("\n", " ").strip()[:80]
    lines = [f"TASK: {task}  TYPE: {tool.id}", "INPUT: " + ", ".join(files)]
    if tool.options:
        lines.append("OPTIONS: " + (", ".join(options) if options else "none"))
    if extra.strip():
        lines.append("FORMAT: " + extra.strip().replace("\n", " "))
    if mark.strip() and tool.mark:
        lines.append("WATERMARK: " + " ".join(mark.split())[:120])
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
    elif job.type == "read-aloud":
        for f in files:
            secs += _guess_words(f) / LISTEN_WPM * 60 * speeds.get("read-aloud", 0.5)
    elif job.type == "translate":
        n_lang = max(1, len(option_values(job, "to")))
        for f in files:
            secs += max(1, -(-_guess_words(f) // TRANSLATE_WORDS)) * n_lang * speeds.get("part", 25.0) * 1.3
    elif job.type == "photo-batch":
        mark = job.watermark.strip().lower()
        files = [f for f in files if not (mark.endswith(".png") and
                                          str(f).replace("\\", "/").lower().endswith(mark))]
        secs += len(files) * speeds.get("photo", 1.5)
    elif job.type == "proofread":
        for f in files:
            secs += max(1, -(-_guess_words(f) // PROOF_WORDS)) * speeds.get("part", 25.0)
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
