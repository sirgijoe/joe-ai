"""Sound, picture and video helpers on the Tools tab (2.1), all done with FFmpeg on this PC:

- clean-audio: background noise, hum and uneven volume in a recording (or a video's sound).
- social-graphic: a picture with your exact words on it, at each social site's size. The words are
  placed by FFmpeg (never drawn by AI), so they're never misspelled.
- privacy-blur: faces, license plates, house numbers and screens blurred before posting. The vision
  model finds them; FFmpeg blurs them. The person checks the result: nothing found is never "safe".
- tidy-speech: "um", "uh" and long pauses cut out of a recording or talking video, from a word-by-word
  transcript. A list of every cut is saved.
- edit-words: edit a recording or talking video by its words (like Descript). First run: Joe writes what
  was said as plain text. Delete the words you don't want, put the edited text back in the Inbox with the
  video, run it again: the deleted words are cut out of the video.
- dub-video: a video (or recording) heard, translated line by line, saved as subtitles in the new
  language and, for languages Joe's voice speaks, a voice-over placed at each line's time over the
  original sound turned down.

Originals are never changed.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .fsutil import atomic_write_text

if TYPE_CHECKING:
    from .engine import Engine, JobState
    from .mission import Job, Mission

AV_TOOLS = ("clean-audio", "social-graphic", "privacy-blur", "tidy-speech", "edit-words", "dub-video", "memory-voice",
            "b-roll")

# --------------------------------------------------------------------------- clean a recording
STRENGTH = {"light": -18, "normal": -25, "strong": -35}       # afftdn noise floor (dB)


def clean_filter(strength: str = "normal", hum: bool = False, level: bool = True) -> str:
    """The FFmpeg audio filter: rumble cut, optional mains hum (50 and 60 Hz plus harmonics),
    FFT noise reduction, then even loudness (-16 LUFS, the podcast/YouTube level)."""
    f = ["highpass=f=70"]
    if hum:
        for base in (50, 60):
            f += [f"bandreject=f={base * k}:width_type=q:w=30" for k in (1, 2, 3)]
    f.append(f"afftdn=nf={STRENGTH.get(strength, -25)}:tn=1")
    if level:
        f.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    return ",".join(f)


def clean_command(ffmpeg: str, src: Path, out: Path, afilter: str, video: bool) -> list[str]:
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src), "-af", afilter]
    ext = out.suffix.lower()
    if video:
        cmd += ["-map", "0:v?", "-map", "0:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    elif ext == ".mp3":
        cmd += ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]
    elif ext in (".m4a", ".aac"):
        cmd += ["-vn", "-c:a", "aac", "-b:a", "192k"]
    elif ext == ".flac":
        cmd += ["-vn", "-c:a", "flac"]
    else:
        cmd += ["-vn", "-c:a", "pcm_s16le"]
    return cmd + [str(out)]


# --------------------------------------------------------------------------- social graphics
SIZES = {
    "ig-post": ("Instagram post (square)", 1080, 1080),
    "ig-portrait": ("Instagram portrait", 1080, 1350),
    "story": ("Story / Reel / TikTok", 1080, 1920),
    "fb-post": ("Facebook / link post", 1200, 630),
    "fb-cover": ("Facebook cover", 1640, 624),
    "x-post": ("X (Twitter) post", 1600, 900),
    "yt-thumb": ("YouTube thumbnail", 1280, 720),
    "pinterest": ("Pinterest pin", 1000, 1500),
    "flyer": ("Flyer (US Letter, print)", 2550, 3300),
    "flyer-a4": ("Flyer (A4, print)", 2480, 3508),
}
COLORS = {"dark": "0x1f2933", "white": "0xffffff", "navy": "0x1d3557", "green": "0x2d6a4f",
          "red": "0x9d0208", "purple": "0x5a189a", "teal": "0x006d77", "warm": "0xe76f51"}


def wrap(text: str, width_chars: int) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        words, line = para.split(), ""
        for w in words:
            if line and len(line) + 1 + len(w) > width_chars:
                out.append(line)
                line = w
            else:
                line = (line + " " + w).strip()
        out.append(line)
    return out


def layout(text: str, w: int, h: int) -> tuple[list[str], list[str], int, int]:
    """(headline lines, other lines, headline font size, small font size) for a w x h picture.
    First line of the person's words = the headline; the rest is smaller."""
    lines = [ln.strip() for ln in re.split(r"\n|\s+\|\s+", (text or "").strip())]
    head, rest = (lines[0] if lines else ""), "\n".join(ln for ln in lines[1:] if ln)
    short = min(w, h)
    big = max(28, int(short * (0.10 if len(head) < 25 else 0.075)))
    small = max(18, int(big * 0.45))
    usable = w * 0.86
    head_lines = wrap(head, max(8, int(usable / (big * 0.55))))
    rest_lines = wrap(rest, max(12, int(usable / (small * 0.52)))) if rest else []
    while (len(head_lines) * big * 1.2 + len(rest_lines) * small * 1.35) > h * 0.6 and big > 28:
        big, small = int(big * 0.88), max(18, int(small * 0.9))
        head_lines = wrap(head, max(8, int(usable / (big * 0.55))))
        rest_lines = wrap(rest, max(12, int(usable / (small * 0.52)))) if rest else []
    return head_lines, rest_lines, big, small


def graphic_command(ffmpeg: str, photo: Path | None, out: Path, w: int, h: int, text_files: list[tuple[Path, int, int]],
                    font: Path, color: str, place: str) -> list[str]:
    """One FFmpeg call: the photo cropped to fill the size (or a plain color), a dark band so the
    words stay readable, then each line of words, centered."""
    from .tools import _ff_path
    if photo:
        cmd = [ffmpeg, "-y", "-v", "error", "-i", str(photo)]
        chain = f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    else:
        cmd = [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={COLORS.get(color, color)}:s={w}x{h}:d=1"]
        chain = "[0:v]setsar=1"
    total = sum(int(sz * (1.25 if big else 1.35)) for _, sz, big in text_files)
    pad = int(min(w, h) * 0.06)
    top = {"top": pad * 2, "middle": (h - total) // 2}.get(place, h - total - pad * 2)
    if photo:
        band_y = max(0, top - pad)
        chain += f",drawbox=x=0:y={band_y}:w=iw:h={min(h - band_y, total + pad * 2)}:color=black@0.55:t=fill"
    ink = "0x1f2933" if (not photo and color == "white") else "white"
    y = top
    for f, size, big in text_files:
        chain += (f",drawtext=fontfile={_ff_path(font)}:textfile={_ff_path(f)}:expansion=none:fontsize={size}:fontcolor={ink}"
                  f":x=(w-text_w)/2:y={y}" + (":shadowcolor=black@0.6:shadowx=2:shadowy=2" if photo else ""))
        y += int(size * (1.25 if big else 1.35))
    return cmd + ["-filter_complex", chain, "-frames:v", "1", "-q:v", "2", str(out)]


def bundled_font(bold: bool = True) -> Path | None:
    p = Path(__file__).parent / "ui" / "fonts" / f"AtkinsonHyperlegible-{'Bold' if bold else 'Regular'}.ttf"
    return p if p.is_file() else None


# --------------------------------------------------------------------------- privacy blur
BLUR_KINDS = {"faces": "faces (every person's face, even small or in the background)",
              "plates": "vehicle license plates",
              "addresses": "house numbers, street signs with the address, mail or packages with addresses",
              "screens": "computer and phone screens, and documents or papers with readable writing",
              "kids": "children (their whole body)"}
BLUR_SYSTEM = ("You find private things in a photo so they can be blurred before it's posted online. Be "
               "generous: it's better to blur too much than to miss something. Reply with ONLY JSON.")
BLUR_ASK = ('Find every one of these in the picture: {what}. Reply with ONLY JSON: {{"boxes": [{{"kind": "faces", '
            '"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}}]}} where x, y are the top-left corner and w, h the size, all '
            'as fractions of the picture width/height from 0 to 1. Nothing found: {{"boxes": []}}.')


def parse_boxes(raw: str, kinds: set[str]) -> list[dict]:
    m = re.search(r"\{.*\}", re.sub(r"(?s)<think>.*?</think>", "", raw or ""), re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return []
    out = []
    for b in (data.get("boxes") or []) if isinstance(data, dict) else []:
        try:
            x, y, w, h = (float(b[k]) for k in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError):
            continue
        if max(x, y, w, h) > 1.5:                       # given in pixels/percent: not trustworthy
            continue
        if w <= 0 or h <= 0:
            continue
        kind = str(b.get("kind", "")).lower()
        if kinds and kind and kind not in kinds:
            continue
        out.append({"kind": kind or "?", "x": max(0.0, x), "y": max(0.0, y), "w": min(w, 1 - max(0.0, x)),
                    "h": min(h, 1 - max(0.0, y))})
    return out


def blur_command(ffmpeg: str, src: Path, out: Path, boxes: list[dict], size: tuple[int, int],
                 grow: float = 0.15) -> list[str]:
    """Each box (a little bigger, to be safe) blurred hard enough that nothing can be read back."""
    W, H = size
    parts, last = [], "0:v"
    for i, b in enumerate(boxes):
        bw, bh = b["w"] * W, b["h"] * H
        x = max(0, int(b["x"] * W - bw * grow))
        y = max(0, int(b["y"] * H - bh * grow))
        w = min(W - x, int(bw * (1 + 2 * grow))) // 2 * 2 or 2
        h = min(H - y, int(bh * (1 + 2 * grow))) // 2 * 2 or 2
        r = max(4, min(w, h) // 4)
        parts.append(f"[{last}]split[b{i}a][b{i}b];[b{i}b]crop={w}:{h}:{x}:{y},boxblur={r}:3[b{i}c];"
                     f"[b{i}a][b{i}c]overlay={x}:{y}[o{i}]")
        last = f"o{i}"
    graph = ";".join(parts) if parts else "[0:v]null[o]"
    tail = f"[{last}]" if parts else "[o]"
    return [ffmpeg, "-y", "-v", "error", "-i", str(src), "-filter_complex", graph, "-map", tail,
            "-map_metadata", "-1", "-frames:v", "1", "-q:v", "2", str(out)]


# --------------------------------------------------------------------------- tidy speech
FILLERS = {"um", "umm", "uh", "uhh", "uhm", "erm", "er", "ah", "hmm", "mm", "mhm"}


def cut_plan(words: list[dict], fillers: bool = True, pause: float = 1.0, keep: float = 0.35) -> list[tuple[float, float, str]]:
    """(start, end, why) spans to remove: filler words, and the part of any silence longer than
    `pause` seconds beyond a short natural gap (`keep`). words = [{"t", "s", "e"}] as Joe's hearing gives them."""
    cuts: list[tuple[float, float, str]] = []
    prev_end = None
    for wd in words:
        try:
            s, e = float(wd.get("s", wd.get("start"))), float(wd.get("e", wd.get("end")))
        except (TypeError, ValueError):
            continue
        text = re.sub(r"[^\w']", "", str(wd.get("t", wd.get("word", "")))).lower()
        if prev_end is not None and pause and s - prev_end > pause:
            cuts.append((prev_end + keep / 2, s - keep / 2, f"pause {s - prev_end:.1f} s"))
        if fillers and text in FILLERS:
            cuts.append((s, e, f'"{text}"'))
        prev_end = e
    return merge_cuts(cuts)


def merge_cuts(cuts: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    """Sorted, with overlapping or touching cuts joined (their reasons kept)."""
    cuts = sorted(cuts)
    merged: list[list] = []
    for a, b, why in cuts:
        if b - a < 0.05:
            continue
        if merged and a <= merged[-1][1] + 0.05:
            merged[-1][1] = max(merged[-1][1], b)
            merged[-1][2] += f" + {why}"
        else:
            merged.append([a, b, why])
    return [(round(a, 3), round(b, 3), w) for a, b, w in merged]


def keep_spans(cuts: list[tuple[float, float, str]], length: float) -> list[tuple[float, float]]:
    out, t = [], 0.0
    for a, b, _ in cuts:
        if a > t:
            out.append((t, a))
        t = max(t, b)
    if length > t:
        out.append((t, length))
    return [(round(a, 3), round(b, 3)) for a, b in out if b - a > 0.02]


def tidy_command(ffmpeg: str, src: Path, out: Path, keep: list[tuple[float, float]], video: bool) -> list[str]:
    """Keep only the kept parts, joined with a tiny fade so the cuts don't click."""
    sel = "+".join(f"between(t,{a},{b})" for a, b in keep) or "1"
    af = f"aselect='{sel}',asetpts=N/SR/TB"
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src)]
    if video:
        cmd += ["-vf", f"select='{sel}',setpts=N/FRAME_RATE/TB", "-af", af, "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "20", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-af", af, "-vn"] + (["-c:a", "libmp3lame", "-q:a", "2"] if out.suffix.lower() == ".mp3" else [])
    return cmd + [str(out)]


# --------------------------------------------------------------------------- edit by the words
WORDS_HEAD = ("# What was said in {name}",
              "# Delete any words you want cut out of the video, then save this file. Don't retype or add words:",
              "# Joe can only cut, not say new things. Lines starting with # are ignored.",
              "# Then put this file in Joe's Inbox together with {name} and run 'Edit by the words' again.")


def _token(t: str) -> str:
    return re.sub(r"[^\w']", "", str(t)).lower()


def words_text(words: list[dict], name: str, per_line: int = 14) -> str:
    """What was said, a short line at a time (easy to delete from), with a new paragraph at long pauses."""
    out = [h.format(name=name) for h in WORDS_HEAD] + [""]
    line: list[str] = []
    prev = None
    for wd in words:
        t = str(wd.get("t", wd.get("word", ""))).strip()
        if not t:
            continue
        s = float(wd.get("s", wd.get("start", 0)) or 0)
        if line and (len(line) >= per_line or (prev is not None and s - prev > 1.5)):
            out.append(" ".join(line))
            if prev is not None and s - prev > 1.5:
                out.append("")
            line = []
        line.append(t)
        prev = float(wd.get("e", wd.get("end", s)) or s)
    if line:
        out.append(" ".join(line))
    return "\n".join(out) + "\n"


def edited_tokens(text: str) -> list[str]:
    body = "\n".join(x for x in (text or "").splitlines() if not x.lstrip().startswith("#"))
    return [t for t in (_token(x) for x in body.split()) if t]


def word_cuts(words: list[dict], edited: str, length: float) -> tuple[list[tuple[float, float, str]], list[str]]:
    """(cuts, notes): the words deleted from the edited text become cuts, with the gap after them, so the
    next word follows naturally. Changed or added words can't be said by Joe: they're kept as spoken and noted."""
    import difflib
    timed = []
    for wd in words:
        try:
            timed.append((_token(wd.get("t", wd.get("word", ""))), float(wd.get("s", wd.get("start"))),
                          float(wd.get("e", wd.get("end"))), str(wd.get("t", wd.get("word", ""))).strip()))
        except (TypeError, ValueError):
            continue
    timed = [w for w in timed if w[0]]
    orig = [w[0] for w in timed]
    new = edited_tokens(edited)
    cuts: list[tuple[float, float, str]] = []
    notes: list[str] = []
    sm = difflib.SequenceMatcher(a=orig, b=new, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "delete":
            a = timed[i1][1]
            b = timed[i2][1] - 0.08 if i2 < len(timed) else length
            if i1 > 0:
                a = max(a - 0.04, timed[i1 - 1][2] + 0.04)
            gone = " ".join(w[3] for w in timed[i1:i2])
            cuts.append((round(a, 3), round(max(b, timed[i2 - 1][2]), 3), f'"{gone[:60]}"'))
        elif op == "replace":
            notes.append(f"Changed words kept as spoken (Joe can only cut): "
                         f"'{' '.join(w[3] for w in timed[i1:i2])[:60]}' -> '{' '.join(new[j1:j2])[:60]}'")
        elif op == "insert":
            notes.append(f"Added words ignored (Joe can only cut): '{' '.join(new[j1:j2])[:60]}'")
    return merge_cuts(cuts), notes


# --------------------------------------------------------------------------- dub a video
# Joe's voice (Kokoro) speaks these; other languages get translated subtitles only.
DUB_VOICES = {"english": ("en-us", "am_adam", "af_heart"), "spanish": ("es", "em_alex", "ef_dora"),
              "french": ("fr-fr", "ff_siwis", "ff_siwis"), "italian": ("it", "im_nicola", "if_sara"),
              "portuguese": ("pt-br", "pm_alex", "pf_dora"), "hindi": ("hi", "hm_omega", "hf_alpha")}
DUB_SYSTEM = ("You translate video subtitles. Keep each line's meaning, short enough to read (or say) in the "
              "same time. Keep names, numbers and brands. Never add or drop lines. Reply with ONLY the numbered lines.")
DUB_ASK = "Translate each numbered line into {lang}. Reply with the same numbers, one line each, like '3| text'.\n\n{lines}"


def srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def make_srt(segs: list[dict]) -> str:
    out = []
    for i, sg in enumerate(segs, 1):
        out += [str(i), f"{srt_time(sg['s'])} --> {srt_time(sg['e'])}", sg["t"].strip(), ""]
    return "\n".join(out)


def parse_numbered(raw: str, n: int) -> dict[int, str]:
    got: dict[int, str] = {}
    for ln in re.sub(r"(?s)<think>.*?</think>", "", raw or "").splitlines():
        m = re.match(r"^\s*(?:\[(\d{1,4})\]\s*[|.):-]?|(\d{1,4})\s*[|.):-])\s*(.+)$", ln)
        k = int(m.group(1) or m.group(2)) if m else 0
        if m and 1 <= k <= n and m.group(3).strip():
            got[k] = m.group(3).strip()
    return got


def place_voice(parts: list[tuple[float, Path]], length: float, dest: Path) -> None:
    """One WAV as long as the video with each spoken line starting at its time (24 kHz, 16-bit mono).
    A line that would run into the next one starts right after it instead of on top of it."""
    import wave
    rate, width = 24000, 2
    total = int(length * rate) + rate
    buf = bytearray(total * width)
    free_at = 0
    for start, wav in parts:
        with wave.open(str(wav), "rb") as w:
            if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, width, rate):
                continue
            data = w.readframes(w.getnframes())
        at = max(int(start * rate) * width, free_at)
        end = min(len(buf), at + len(data))
        buf[at:end] = data[:end - at]
        free_at = end
    with wave.open(str(dest), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(bytes(buf))


def _dub(engine, job, st, ffmpeg, src: Path, stem: str, folder: Path) -> list[str]:
    import tempfile
    from .addons import voice_python
    from .engine import PartFailed
    from .tools import (VIDEO_IN_EXT, _to_wav, chosen_options, hear, hearing_model, language_name, option_value,
                        whisper_language)
    lang = option_value(job, "to")
    if not lang:
        raise RuntimeError("pick the language to dub into")
    name = language_name(lang)
    opts = chosen_options(job)
    video = src.suffix.lower() in VIDEO_IN_EXT
    heard = option_value(job, "language") or "english"
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        wav = _to_wav(ffmpeg, src, tmpd / "a.wav", engine.log)
        if not wav:
            raise RuntimeError("couldn't read the sound")
        length = media_seconds(ffmpeg, src)
        try:
            got = hear(engine, wav, hearing_model(engine.s.voice.stt_model, heard), whisper_language(heard),
                       timeout=max(900.0, length * 4 + 600))
        except Exception as e:                                   # noqa: BLE001
            raise RuntimeError(f"couldn't hear it: {e}") from e
        segs = [{"s": float(x.get("s", 0)), "e": float(x.get("e", 0)), "t": str(x.get("t", "")).strip()}
                for x in (got.get("segments") or []) if str(x.get("t", "")).strip()]
        if not segs:
            raise RuntimeError("no speech heard in it")
        out_segs, unsure = [], 0
        for a in range(0, len(segs), 40):
            batch = segs[a:a + 40]
            lines = "\n".join(f"{i + 1}| {sg['t']}" for i, sg in enumerate(batch))
            try:
                r = engine._chat(job, a // 40, "dub", DUB_SYSTEM, DUB_ASK.format(lang=name, lines=lines), st)
            except PartFailed as e:
                raise RuntimeError(str(e)) from e
            got_lines = parse_numbered(r.text, len(batch))
            for i, sg in enumerate(batch):
                t = got_lines.get(i + 1)
                if not t:
                    unsure += 1
                    t = sg["t"] + " [CHECK]"
                out_segs.append({**sg, "t": t})
        srt = folder / f"{stem}-{lang}.srt"
        atomic_write_text(srt, make_srt(out_segs))
        made = [srt.name]
        if unsure:
            st.flags.append({"item": src.name, "flag": f"[CHECK] {unsure} line(s) weren't translated (kept as heard)"})
        if "voice" not in opts:
            return made
        if lang not in DUB_VOICES:
            st.flags.append({"item": src.name, "flag": f"[CHECK] Joe's voice can't speak {name} yet: subtitles only"})
            engine.log(f"  Joe's voice can't speak {name} yet, so {src.name} gets {name} subtitles only.")
            return made
        if not Path(voice_python()).exists() and engine.voice is None:
            raise RuntimeError("the voice-over needs Joe's voice add-on (Setup > System check)")
        from .addons import VoiceWorker
        worker = engine.voice or VoiceWorker(engine.log)
        code, male, female = DUB_VOICES[lang]
        voice = female if option_value(job, "voice-of") == "woman" else male
        parts = []
        for i, sg in enumerate(out_segs):
            if engine.stop.is_set():
                from .engine import Stopped
                raise Stopped()
            text = sg["t"].replace("[CHECK]", "").strip()
            if not text:
                continue
            w = tmpd / f"v{i:04d}.wav"
            engine._progress(f"{job.name}: {name} voice, line {i + 1}/{len(out_segs)}")
            r = worker.call({"cmd": "tts", "text": text, "out": str(w), "voice": voice, "speed": 1.0, "lang": code},
                            timeout=max(300.0, len(text) * 0.5))
            if not r.get("ok") or not w.exists():
                raise RuntimeError(r.get("error") or "the voice didn't make any sound")
            slot = (out_segs[i + 1]["s"] if i + 1 < len(out_segs) else length) - sg["s"]
            have = media_seconds(ffmpeg, w) or 0
            if slot > 0.5 and have > slot * 1.08:                   # too long for its spot: speak a bit faster
                fast = tmpd / f"v{i:04d}f.wav"
                tempo = min(1.5, have / slot)
                if not _ff([ffmpeg, "-y", "-v", "error", "-i", str(w), "-filter:a", f"atempo={tempo:.3f}",
                            "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(fast)], 120):
                    w = fast
            parts.append((sg["s"], w))
        track = tmpd / "voice.wav"
        place_voice(parts, length or (out_segs[-1]["e"] + 2), track)
        keep = {"low": 0.15, "half": 0.4, "off": 0.0}.get(option_value(job, "original") or "low", 0.15)
        if video:
            out = folder / f"{stem}-{lang}.mp4"
            graph = (f"[0:a]volume={keep}[o];[1:a]aresample=48000[v];[o][v]amix=inputs=2:normalize=0:duration=first[a]"
                     if keep else "[1:a]aresample=48000[a]")
            cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src), "-i", str(track), "-i", str(srt),
                   "-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-map", "2:s", "-c:v", "copy",
                   "-c:a", "aac", "-b:a", "192k", "-c:s", "mov_text", "-metadata:s:s:0", f"language={code[:2]}",
                   "-shortest", str(out)]
        else:
            out = folder / f"{stem}-{lang}.mp3"
            graph = (f"[0:a]volume={keep}[o];[1:a]aresample=44100[v];[o][v]amix=inputs=2:normalize=0:duration=first[a]"
                     if keep else "[1:a]aresample=44100[a]")
            cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src), "-i", str(track), "-filter_complex", graph,
                   "-map", "[a]", "-c:a", "libmp3lame", "-q:a", "2", str(out)]
        err = _ff(cmd)
        if err:
            raise RuntimeError(err)
        made.insert(0, out.name)
        st.flags.append({"item": src.name, "flag": f"[CHECK] machine-translated {name} voice-over: have someone who "
                                                   "speaks it listen before you publish"})
    return made


# --------------------------------------------------------------------------- a voice to remember
def voice_sample_command(ffmpeg: str, src: Path, out: Path, seconds: int = 25) -> list[str]:
    """A family recording (audio or video) -> a clean voice sample for copying a voice: sound only,
    light noise cleanup, silences dropped, up to `seconds` long, 24 kHz mono 16-bit."""
    af = ("highpass=f=70,afftdn=nf=-20:tn=1,silenceremove=start_periods=1:start_threshold=-45dB:"
          "stop_periods=-1:stop_duration=0.5:stop_threshold=-45dB,loudnorm=I=-18:TP=-2")
    return [ffmpeg, "-y", "-v", "error", "-i", str(src), "-vn", "-af", af, "-t", str(seconds), "-ar", "24000",
            "-ac", "1", "-c:a", "pcm_s16le", str(out)]


def prepare_voice_sample(ffmpeg: str, src: Path, out: Path) -> str:
    return _ff(voice_sample_command(ffmpeg, src, out), 600)


MEMORY_NOTE = ("This recording was made by AI from a recording of {name}, for the family's own listening. It is not "
               "a real recording of them. The voice program (Chatterbox) also hides an inaudible watermark in it "
               "that marks it as AI-made. Please don't share it as if it were real.\n")


def _memory(engine, job, st, ffmpeg, src: Path, stem: str, folder: Path) -> list[str]:
    import tempfile
    from . import addons
    from .tools import document_text, merge_wavs, speech_pieces, to_mp3
    who = job.format.strip()
    ref = addons.memory_ref(who)
    if not ref:
        have = ", ".join(v["name"] for v in addons.memory_voices()) or "none yet"
        raise RuntimeError(f"no voice called '{who}' (made so far: {have}). Make one in Setup > Voice & Talk > "
                           "A voice to remember")
    name = next((v["name"] for v in addons.memory_voices() if v["id"] == addons.memory_slug(who)), who)
    try:
        text = document_text(src, engine.log)
    except (ValueError, OSError) as e:
        raise RuntimeError(str(e)) from e
    if not text.strip():
        raise RuntimeError("no words in it")
    worker = getattr(engine, "clone", None) or addons.VoiceWorker(
        engine.log, python=str(addons.clone_python()), script=Path(addons.__file__).with_name("clone_worker.py"))
    wavs = []
    with tempfile.TemporaryDirectory() as tmp:
        pieces = speech_pieces(text, 3500)
        for i, piece in enumerate(pieces):
            if engine.stop.is_set():
                from .engine import Stopped
                raise Stopped()
            engine._progress(f"{job.name}: {src.name}, part {i + 1}/{len(pieces)} in {name}'s voice")
            w = Path(tmp) / f"p{i:04d}.wav"
            r = worker.call({"cmd": "tts", "text": piece, "out": str(w), "ref": str(ref)},
                            timeout=max(900.0, len(piece) * 1.5))
            if not r.get("ok") or not w.exists():
                raise RuntimeError(r.get("error") or "the voice didn't make any sound")
            wavs.append(w)
        merged = Path(tmp) / "all.wav"
        merge_wavs(wavs, merged)
        label = f"{src.stem} ({name}'s voice, AI)"
        base = f"{stem}-{addons.memory_slug(name)}-voice"
        if to_mp3(ffmpeg, merged, folder / f"{base}.mp3", label, engine.log):
            made = [f"{base}.mp3"]
        else:
            import shutil as _sh
            _sh.copy(merged, folder / f"{base}.wav")
            made = [f"{base}.wav"]
    atomic_write_text(folder / "About this recording.txt", MEMORY_NOTE.format(name=name))
    return made + ["About this recording.txt"]


# --------------------------------------------------------------------------- auto B-roll
BROLL_SYSTEM = ("You are a video editor adding B-roll (cutaway clips) over a talking video. Pick a clip only where "
                "it clearly matches what's being said. Leave most lines on the speaker. Reply with ONLY JSON.")
BROLL_ASK = ('The speaker\'s lines (number, time, words):\n{lines}\n\nClips you can use:\n{clips}\n\nPick at most '
             '{most} lines to cover with a matching clip; never two lines in a row. Reply with ONLY JSON: '
             '[{{"line": 3, "clip": "exact clip name"}}]. No good match: [].')


def broll_spans(picks: list[dict], segs: list[dict], clips: dict[str, float], length: float,
                most_share: float = 0.35) -> list[tuple[float, float, str]]:
    """Picks -> (start, end, clip) spans: 2-6 s each, inside the video, never overlapping, never on the
    first 2 seconds, and at most `most_share` of the video covered."""
    out: list[tuple[float, float, str]] = []
    covered, last_end, last_line = 0.0, 2.0, -9
    for p in sorted(picks, key=lambda x: int(x.get("line", 0)) if str(x.get("line", "")).isdigit() else 0):
        try:
            i = int(p.get("line")) - 1
        except (TypeError, ValueError):
            continue
        name = str(p.get("clip", ""))
        if not (0 <= i < len(segs)) or name not in clips or i - last_line < 2:    # never two lines in a row
            continue
        a = max(segs[i]["s"], last_end)
        dur = min(6.0, max(2.0, segs[i]["e"] - segs[i]["s"]))
        if clips[name] > 0:
            dur = min(dur, clips[name])
        b = min(a + dur, length - 0.5)
        if b - a < 1.5 or covered + (b - a) > length * most_share:
            continue
        out.append((round(a, 2), round(b, 2), name))
        covered += b - a
        last_end, last_line = b + 0.5, i
    return out


def broll_command(ffmpeg: str, main: Path, spans: list[tuple[float, float, str]], files: dict[str, Path],
                  size: tuple[int, int], out: Path, photo_ext: tuple[str, ...]) -> list[str]:
    W, H = size
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(main)]
    graph, last = [], "0:v"
    for k, (a, b, name) in enumerate(spans, 1):
        f = files[name]
        dur = b - a
        if f.suffix.lower() in photo_ext:
            cmd += ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(f)]
        else:
            cmd += ["-i", str(f)]
        graph.append(f"[{k}:v]trim=0:{dur:.2f},setpts=PTS-STARTPTS+{a:.2f}/TB,scale={W}:{H}:force_original_aspect_ratio=increase,"
                     f"crop={W}:{H},setsar=1,format=yuv420p[c{k}]")
        graph.append(f"[{last}][c{k}]overlay=0:0:eof_action=pass:enable='between(t,{a:.2f},{b:.2f})'[m{k}]")
        last = f"m{k}"
    graph.append(f"[{last}]format=yuv420p[vout]")
    return cmd + ["-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "0:a?", "-c:v", "libx264",
                  "-preset", "veryfast", "-crf", "20", "-c:a", "copy", str(out)]


def _broll(engine, job, st, ffmpeg, src: Path, stem: str, folder: Path) -> list[str]:
    import tempfile
    from .engine import PartFailed
    from .tools import PHOTO_EXT, _to_wav, hear, hearing_model, option_value, resolve_inputs, whisper_language
    files, _ = resolve_inputs(engine, job)
    clips_f = [f for f in files if f != src]
    if not clips_f:
        raise RuntimeError("add the clips or photos to use as B-roll, together with the talking video")
    size = picture_size(ffmpeg, src)
    length = media_seconds(ffmpeg, src)
    if not size or not length:
        raise RuntimeError("couldn't read the video")
    names = {f.stem: f for f in clips_f}
    clip_len = {n: (0.0 if f.suffix.lower() in PHOTO_EXT else media_seconds(ffmpeg, f)) for n, f in names.items()}
    heard = option_value(job, "language") or "english"
    with tempfile.TemporaryDirectory() as tmp:
        wav = _to_wav(ffmpeg, src, Path(tmp) / "a.wav", engine.log)
        if not wav:
            raise RuntimeError("couldn't read the sound")
        try:
            got = hear(engine, wav, hearing_model(engine.s.voice.stt_model, heard), whisper_language(heard),
                       timeout=max(900.0, length * 4 + 600))
        except Exception as e:                                   # noqa: BLE001
            raise RuntimeError(f"couldn't hear it: {e}") from e
    segs = [{"s": float(x.get("s", 0)), "e": float(x.get("e", 0)), "t": str(x.get("t", "")).strip()}
            for x in (got.get("segments") or []) if str(x.get("t", "")).strip()]
    if not segs:
        raise RuntimeError("no speech heard in it")
    desc = "\n".join(f"- {n} ({'photo' if clip_len[n] == 0 else f'{clip_len[n]:.0f} s clip'}; name words: "
                     f"{re.sub(r'[_-]+', ' ', n)})" for n in names)
    picks: list[dict] = []
    for a in range(0, len(segs), 60):
        lines = "\n".join(f"{a + i + 1}. [{sg['s']:.0f}s] {sg['t']}" for i, sg in enumerate(segs[a:a + 60]))
        try:
            r = engine._chat(job, a // 60, "b-roll", BROLL_SYSTEM,
                             BROLL_ASK.format(lines=lines, clips=desc, most=max(1, len(segs[a:a + 60]) // 3)), st)
        except PartFailed as e:
            raise RuntimeError(str(e)) from e
        from .tools import parse_json_list
        picks += parse_json_list(r.text) or []
    share = {"few": 0.2, "some": 0.35, "lots": 0.5}.get(option_value(job, "amount") or "some", 0.35)
    spans = broll_spans(picks, segs, clip_len, length, share)
    L = [f"# B-roll: {src.name}", ""]
    if not spans:
        L += ["Joe didn't find a clip that clearly matches anything said, so the video wasn't changed. Clip and "
              "photo names help Joe match them: name them for what they show (like 'kiln-firing.mp4')."]
        atomic_write_text(folder / f"{stem}-broll.md", "\n".join(L) + "\n")
        return [f"{stem}-broll.md"]
    out = folder / f"{stem}-broll.mp4"
    err = _ff(broll_command(ffmpeg, src, spans, names, size, out, PHOTO_EXT))
    if err:
        raise RuntimeError(err)
    L += [f"{len(spans)} cutaway(s), {sum(b - a for a, b, _ in spans):.0f} s of {length:.0f} s. The sound stays the "
          "speaker's. Your original wasn't changed.", ""]
    L += [f"- {a:6.1f}-{b:6.1f} s: {n}" for a, b, n in spans]
    atomic_write_text(folder / f"{stem}-broll.md", "\n".join(L) + "\n")
    return [out.name, f"{stem}-broll.md"]


# --------------------------------------------------------------------------- run
def _ff(cmd: list[str], timeout: float = 3600) -> str:
    """Run FFmpeg; '' = fine, else its error in a line."""
    from .system import no_window_flags
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)[:300]
    return "" if r.returncode == 0 else (r.stderr or "FFmpeg failed").strip().splitlines()[-1][:300]


def media_seconds(ffmpeg: str, src: Path) -> float:
    from .system import no_window_flags
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(src)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60, creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def picture_size(ffmpeg: str, src: Path) -> tuple[int, int] | None:
    from .system import no_window_flags
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(src)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60, creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", r.stderr or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def run(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .doctor import ffmpeg_exe
    from .engine import Stopped
    from .tools import TOOLS, _finish, _key, resolve_inputs, tool_dir, unique_stem

    tid = job.type
    files, problems = resolve_inputs(engine, job)
    for pr in problems:
        engine.log(f"  INPUT: {pr}")
    if not files and tid != "social-graphic":
        st.status, st.note = "failed", "no files to work on; add them with INPUT: (files or a folder in Inbox)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    if tid == "social-graphic" and not job.format.strip():
        st.status, st.note = "failed", "type the words for the picture in the box (first line = the headline)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    ffmpeg = ffmpeg_exe(engine.s.comfy.ffmpeg)
    if not ffmpeg:
        st.status, st.note = "failed", f"{TOOLS[tid].name.lower()} needs FFmpeg (Setup > System check installs it)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    if tid == "privacy-blur":
        from .tools import find_vision_model
        if not engine.services.handoff("text"):
            st.status, st.note = "failed", "Ollama is not running and could not be started"
            engine.log(st.note)
            return st
        engine._vision_model = find_vision_model(engine) or ""
        if not engine._vision_model:
            st.status, st.note = "failed", ("this needs a vision model (one that can look at pictures). "
                                            "Setup (F10) > System check offers a free one")
            engine.log(f"'{job.name}' failed: {st.note}")
            return st
    if tid == "memory-voice":
        from . import addons
        if not addons.clone_ready() and getattr(engine, "clone", None) is None:
            st.status, st.note = "failed", ("this needs the voice-copy add-on (Setup > System check > \"sound like me\" > "
                                            "SET UP; NVIDIA card)")
            engine.log(f"'{job.name}' failed: {st.note}")
            return st
        if not job.format.strip():
            st.status, st.note = "failed", "type whose voice to use in the box (the name you gave it in Setup)"
            engine.log(f"'{job.name}' failed: {st.note}")
            return st
    if tid == "dub-video" and not engine._text_ready(st):
        engine._save_state(job, st)
        return st
    if tid == "b-roll":
        from .tools import VIDEO_IN_EXT
        if not any(f.suffix.lower() in VIDEO_IN_EXT for f in files):
            st.status, st.note = "failed", "add the talking video (and the clips or photos to cut to)"
            engine.log(f"'{job.name}' failed: {st.note}")
            return st
        if not engine._text_ready(st):
            engine._save_state(job, st)
            return st
    if tid in ("tidy-speech", "edit-words", "dub-video", "b-roll"):
        from .tools import hearing_ready
        if not hearing_ready(engine.s) and engine.voice is None:
            st.status, st.note = "failed", "this needs Joe's hearing (Setup > System check > voice add-on)"
            engine.log(f"'{job.name}' failed: {st.note}")
            return st
    folder = tool_dir(engine, job, st)
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}' ({TOOLS[tid].name}) -> {st.output}")
    failed: list[str] = []
    fn = {"clean-audio": _clean, "social-graphic": _graphic, "privacy-blur": _blur, "tidy-speech": _tidy,
          "edit-words": _edit_words, "dub-video": _dub, "memory-voice": _memory, "b-roll": _broll}[tid]
    work = files if (files or tid != "social-graphic") else [None]
    if tid == "edit-words":                              # the recordings; the edited text files go with them
        from .tools import AUDIO_EXT, VIDEO_IN_EXT
        work = [f for f in files if f.suffix.lower() in VIDEO_IN_EXT + AUDIO_EXT]
        if not work:
            st.status, st.note = "failed", "add the recording or video (and your edited words file, if you have one)"
            engine.log(f"'{job.name}' failed: {st.note}")
            engine._save_state(job, st)
            return st
        engine._edit_texts = [f for f in files if f.suffix.lower() in (".txt", ".md")]
    if tid == "b-roll":                                  # one result: the talking video (the longest one)
        from .tools import VIDEO_IN_EXT
        work = [max((f for f in files if f.suffix.lower() in VIDEO_IN_EXT), key=lambda f: media_seconds(ffmpeg, f))]
    try:
        for i, src in enumerate(work):
            if engine.stop.is_set():
                raise Stopped()
            key = _key(engine, src) if src else "graphic"
            if key in st.titles:
                continue
            stem = unique_stem(files, files.index(src)) if src else "graphic"
            engine._progress(f"{job.name}: {src.name if src else 'graphic'}")
            try:
                made = fn(engine, job, st, ffmpeg, src, stem, folder)
            except RuntimeError as e:
                failed.append(f"{src.name if src else 'graphic'}: {e}"[:200])
                engine.log(f"  {src.name if src else 'graphic'}: {e}")
                continue
            st.titles.append(key)
            st.media_files.extend(made)
            st.items += 1
            engine._save_state(job, st)
            engine.log(f"  {src.name if src else 'graphic'} -> {', '.join(made)}")
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} file(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    return _finish(engine, job, st, len(work), failed)


def _clean(engine, job, st, ffmpeg, src: Path, stem: str, folder: Path) -> list[str]:
    from .tools import VIDEO_IN_EXT, chosen_options, option_value
    opts = chosen_options(job)
    video = src.suffix.lower() in VIDEO_IN_EXT
    ext = src.suffix.lower() if (video or src.suffix.lower() in (".mp3", ".wav", ".m4a", ".flac")) else ".mp3"
    if video and ext not in (".mp4", ".mov", ".mkv", ".m4v"):
        ext = ".mp4"
    out = folder / f"{stem}-clean{ext}"
    err = _ff(clean_command(ffmpeg, src, out, clean_filter(option_value(job, "strength") or "normal",
                                                            "hum" in opts, "level" in opts), video))
    if err:
        raise RuntimeError(err)
    return [out.name]


def _graphic(engine, job, st, ffmpeg, src: Path | None, stem: str, folder: Path) -> list[str]:
    import tempfile
    from .system import font_file
    from .tools import option_value, option_values
    sizes = option_values(job, "size") or ["ig-post"]
    font = bundled_font(True) or font_file()
    if not font:
        raise RuntimeError("no font found on this computer")
    made = []
    with tempfile.TemporaryDirectory() as tmp:
        for size in sizes:
            if size not in SIZES:
                continue
            _, w, h = SIZES[size]
            head, rest, big, small = layout(job.format, w, h)
            files = []
            for n, (line, sz, isbig) in enumerate([(ln, big, True) for ln in head] + [(ln, small, False) for ln in rest]):
                f = Path(tmp) / f"l{size}{n}.txt"
                f.write_text(line or " ", encoding="utf-8")
                files.append((f, sz, isbig))
            out = folder / f"{stem}-{size}.{'png' if not src else 'jpg'}"
            said = any(t.startswith("place ") for t in job.options)
            place = option_value(job, "place") if said else ("bottom" if src else "middle")
            err = _ff(graphic_command(ffmpeg, src, out, w, h, files, font, option_value(job, "color") or "dark",
                                      place), 300)
            if err:
                raise RuntimeError(err)
            made.append(out.name)
    if not made:
        raise RuntimeError("no known size picked")
    return made


def _blur(engine, job, st, ffmpeg, src: Path, stem: str, folder: Path) -> list[str]:
    import json as _json
    from .tools import _look, option_values, picture_b64
    kinds = set(option_values(job, "blur")) or {"faces", "plates", "addresses", "screens"}
    size = picture_size(ffmpeg, src)
    if not size:
        raise RuntimeError("couldn't read that picture")
    try:
        img = picture_b64(ffmpeg, src, engine.meta / "tmp" / f"blur-{job.job_id}.jpg", 1536)
    except (ValueError, OSError) as e:
        raise RuntimeError(str(e)) from e
    what = "; ".join(BLUR_KINDS[k] for k in BLUR_KINDS if k in kinds)
    o = _look(engine, job, st, len(st.titles), "privacy-blur", BLUR_SYSTEM, BLUR_ASK.format(what=what), img,
              job.__dict__.get("_vision_model", "") or getattr(engine, "_vision_model", ""))
    if o is None:
        raise RuntimeError("the vision model didn't answer in the right form, so nothing was blurred")
    boxes = parse_boxes(_json.dumps(o), kinds)
    out = folder / f"{stem}-blurred{'.png' if src.suffix.lower() == '.png' else '.jpg'}"
    err = _ff(blur_command(ffmpeg, src, out, boxes, size), 300)
    if err:
        raise RuntimeError(err)
    found: dict[str, int] = {}
    for bx in boxes:
        found[bx["kind"]] = found.get(bx["kind"], 0) + 1
    line = ", ".join(f"{n} {k}" for k, n in found.items()) or "nothing found"
    st.flags.append({"item": src.name, "flag": f"[CHECK] blurred: {line}. Look at the picture before posting: "
                                               "AI can miss things."})
    return [out.name]


def _hear_words(engine, job, ffmpeg, src: Path) -> list[dict]:
    """Every word with its start and end time (Joe's hearing, word by word)."""
    import tempfile
    from .tools import _to_wav, hear, hearing_model, option_value, whisper_language
    with tempfile.TemporaryDirectory() as tmp:
        wav = _to_wav(ffmpeg, src, Path(tmp) / "a.wav", engine.log)
        if not wav:
            raise RuntimeError("couldn't read the sound")
        lang = option_value(job, "language") or "english"
        model = hearing_model(engine.s.voice.stt_model, lang)
        try:
            got = hear(engine, wav, model, whisper_language(lang), words=True,
                       timeout=max(900.0, media_seconds(ffmpeg, src) * 4 + 600))
        except Exception as e:                                   # noqa: BLE001 (hearing add-on trouble)
            raise RuntimeError(f"couldn't hear it: {e}") from e
    words = got.get("words") or []
    if not words:
        raise RuntimeError("no words heard in it")
    return words


def _edit_words(engine, job, st, ffmpeg, src: Path, stem: str, folder: Path) -> list[str]:
    """No edited text yet: write what was said. With one: cut the deleted words out."""
    from .tools import VIDEO_IN_EXT, chosen_options, option_value
    texts = getattr(engine, "_edit_texts", []) or []
    mine = [t for t in texts if t.stem.lower().startswith(src.stem.lower())]
    text = mine[0] if mine else (texts[0] if len(texts) == 1 else None)
    words = _hear_words(engine, job, ffmpeg, src)
    if text is None:
        name = f"{stem}-words.txt"
        atomic_write_text(folder / name, words_text(words, src.name))
        return [name]
    edited = text.read_text(encoding="utf-8", errors="replace")
    if not edited_tokens(edited):
        raise RuntimeError(f"{text.name} has no words left in it (to cut everything, just don't use the video)")
    video = src.suffix.lower() in VIDEO_IN_EXT
    length = media_seconds(ffmpeg, src) or float(words[-1].get("e", 0)) + 1
    cuts, notes = word_cuts(words, edited, length)
    opts = chosen_options(job)
    if "fillers" in opts or "pauses" in opts:
        cuts = merge_cuts(cuts + cut_plan(words, "fillers" in opts,
                                          float(option_value(job, "pause") or 1.0) if "pauses" in opts else 0))
    keep = keep_spans(cuts, length)
    ext = ".mp4" if video else (".mp3" if src.suffix.lower() == ".mp3" else ".wav")
    out = folder / f"{stem}-edited{ext}"
    if cuts:
        err = _ff(tidy_command(ffmpeg, src, out, keep, video))
        if err:
            raise RuntimeError(err)
    saved = sum(b - a for a, b, _ in cuts)
    L = [f"# Edited by the words: {src.name}", "", f"Using {text.name}: {len(cuts)} cut(s), {saved:.1f} seconds shorter "
         f"({length:.0f} s -> {length - saved:.0f} s). Your original wasn't changed.", ""]
    L += [f"- {a:8.2f}-{b:8.2f} s: {why}" for a, b, why in cuts] or ["No words were deleted, so nothing was cut."]
    if notes:
        L += ["", "## Not done"] + [f"- {n}" for n in notes]
    L += ["", "Watch it through once: a cut can land a little early or late when words run together."]
    atomic_write_text(folder / f"{stem}-cuts.md", "\n".join(L) + "\n")
    return ([out.name] if cuts else []) + [f"{stem}-cuts.md"]


def _tidy(engine, job, st, ffmpeg, src: Path, stem: str, folder: Path) -> list[str]:
    from .tools import VIDEO_IN_EXT, chosen_options, option_value
    opts = chosen_options(job)
    video = src.suffix.lower() in VIDEO_IN_EXT
    pause = float(option_value(job, "pause") or 1.0)
    words = _hear_words(engine, job, ffmpeg, src)
    length = media_seconds(ffmpeg, src) or float(words[-1].get("e", 0)) + 1
    cuts = cut_plan(words, "fillers" in opts, pause if "pauses" in opts else 0)
    keep = keep_spans(cuts, length)
    ext = src.suffix.lower() if video else (".mp3" if src.suffix.lower() == ".mp3" else ".wav")
    if video:
        ext = ".mp4"
    out = folder / f"{stem}-tidy{ext}"
    if cuts:
        err = _ff(tidy_command(ffmpeg, src, out, keep, video))
        if err:
            raise RuntimeError(err)
    saved = sum(b - a for a, b, _ in cuts)
    L = [f"# Tidied: {src.name}", "", f"{len(cuts)} cut(s), {saved:.1f} seconds shorter "
         f"({length:.0f} s -> {length - saved:.0f} s). Your original wasn't changed.", ""]
    L += [f"- {a:8.2f}-{b:8.2f} s: {why}" for a, b, why in cuts] or ["Nothing to cut."]
    L += ["", "Listen through once: a cut 'um' can sometimes be a real word ('um' in another language)."]
    atomic_write_text(folder / f"{stem}-cuts.md", "\n".join(L) + "\n")
    return ([out.name] if cuts else []) + [f"{stem}-cuts.md"]
