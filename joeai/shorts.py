"""Make shorts: a long video -> the best moments as vertical 9:16 clips with big captions.

How Joe does it (all on this PC, nothing uploaded):
1. FFmpeg pulls out the sound; Whisper (whisper.cpp or the voice add-on) writes down every word
   with its time.
2. The writing model reads the timed transcript in pieces and picks the moments that stand on
   their own (a hook in the first seconds, one complete thought, a clear ending), with a short
   title and a ready-to-post caption for each.
3. Each pick is moved to whole words and, when it can, to the end of a sentence.
4. For the crop, the vision model (when there is one) finds the speaker's face in a frame from
   the middle of each clip, so the 9:16 window follows the person instead of the middle.
5. FFmpeg cuts each clip at 1080x1920 and burns in word-by-word captions (Atkinson Hyperlegible
   Bold, easy to read) plus the title for the first seconds.
6. A shorts.md list (times, titles, why each was picked) and the social post files
   (social.py) are written next to the clips.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

W, H = 1080, 1920
WINDOW_WORDS = 1500          # transcript words the writing model reads at once

PICK_SYSTEM = """You are a video editor who finds the best moments in a long video for short vertical
clips (YouTube Shorts, TikTok, Reels). You only see a timed transcript. A good moment:
- makes sense on its own, with no earlier context needed
- grabs attention in the first 3 seconds (a question, a surprising claim, a strong opinion, a story start)
- holds one complete thought and ends cleanly
- is between {min_s} and {max_s} seconds long
Use only times that appear in the transcript. Never invent what is said.
Reply with JSON only: a list of objects
{{"start": seconds, "end": seconds, "score": 1-10, "title": "3-7 word hook title",
  "post": "one or two sentence caption for social media with 2-3 hashtags", "why": "short reason"}}"""


def _ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def windows(segments: list[dict], words_per: int = WINDOW_WORDS) -> list[str]:
    """The timed transcript in pieces the model can read: '[123.4] what was said' per line."""
    out, cur, n = [], [], 0
    for s in segments:
        line = f"[{s['s']:.1f}-{s['e']:.1f}] {s['t'].strip()}"
        cur.append(line)
        n += len(s["t"].split())
        if n >= words_per:
            out.append("\n".join(cur))
            cur, n = cur[-3:], sum(len(x.split()) for x in cur[-3:])      # small overlap
    if cur and (not out or len(cur) > 3):
        out.append("\n".join(cur))
    return out


def _num(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"\s*(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\s*$", str(v or ""))
    if m:
        return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def snap(start: float, end: float, words: list[dict], min_s: float, max_s: float) -> tuple[float, float] | None:
    """Move a pick to whole words, end it on a sentence when one ends close by, keep the length."""
    if not words:
        return (start, end) if end - start >= min_s * 0.6 else None
    first = next((w for w in words if w["e"] > start + 0.05), None)
    if not first:
        return None
    s = first["s"]
    inside = [w for w in words if w["s"] >= s and w["e"] <= end + 0.6]
    if not inside:
        return None
    e = inside[-1]["e"]
    if not re.search(r"[.!?]['\")]*$", inside[-1]["t"]):            # finish the sentence (up to 6 s more)
        for w in words:
            if w["s"] >= e and w["e"] <= e + 6 and w["e"] - s <= max_s:
                e = w["e"]
                if re.search(r"[.!?]['\")]*$", w["t"]):
                    break
    if e - s > max_s:                                              # too long: cut at the last sentence end
        ends = [w["e"] for w in words if s + min_s <= w["e"] <= s + max_s and re.search(r"[.!?]$", w["t"])]
        e = ends[-1] if ends else s + max_s
    if e - s < min_s * 0.6:
        return None
    return round(max(0.0, s - 0.15), 2), round(e + 0.25, 2)


def choose(picks: list[dict], words: list[dict], count: int, min_s: float, max_s: float) -> list[dict]:
    """Best-scoring picks that don't overlap, snapped to words, in time order."""
    good = []
    for p in picks:
        a, b = _num(p.get("start")), _num(p.get("end"))
        if a is None or b is None or b <= a:
            continue
        cut = snap(a, b, words, min_s, max_s)
        if not cut:
            continue
        try:
            score = float(p.get("score") or 5)
        except (TypeError, ValueError):
            score = 5.0
        good.append({**p, "start": cut[0], "end": cut[1], "score": score})
    good.sort(key=lambda p: -p["score"])
    out: list[dict] = []
    for p in good:
        if all(p["end"] <= q["start"] or p["start"] >= q["end"] for q in out):
            out.append(p)
        if len(out) >= count:
            break
    return sorted(out, key=lambda p: p["start"])


def _ass_text(t: str) -> str:
    return re.sub(r"[{}\\]", "", t).replace("\n", " ").strip()


def _ass_time(sec: float) -> str:
    sec = max(0.0, sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def captions(words: list[dict], start: float, end: float, title: str = "", per: int = 3) -> str:
    """An .ass subtitle file: a few words at a time, big and centered low; the title at the top
    for the first 3.5 seconds."""
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Atkinson Hyperlegible,92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,7,3,2,80,80,560,1
Style: Title,Atkinson Hyperlegible,74,&H0000E6FF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,3,18,0,8,70,70,190,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if title:
        lines.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(min(3.5, end - start))},Title,,0,0,0,,{_ass_text(title)}")
    inside = [w for w in words if w["s"] >= start - 0.05 and w["e"] <= end + 0.05 and w["t"].strip()]
    group: list[dict] = []
    for i, w in enumerate(inside):
        group.append(w)
        last = i == len(inside) - 1
        pause = not last and inside[i + 1]["s"] - w["e"] > 0.6
        if len(group) >= per or last or pause or re.search(r"[.!?,]$", w["t"]):
            a = group[0]["s"] - start
            b = (inside[i + 1]["s"] - start) if not last and not pause else (w["e"] - start + 0.3)
            text = _ass_text(" ".join(x["t"].strip() for x in group)).upper()
            lines.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Cap,,0,0,0,,{text}")
            group = []
    return head + "\n".join(lines) + "\n"


def crop_filter(src_w: int, src_h: int, center_x: float = 0.5, mode: str = "face") -> str:
    """FFmpeg filter that turns any video into 1080x1920. 'fit' keeps the whole picture with a
    blurred copy behind it; 'face'/'center' fill the frame with a 9:16 window."""
    if mode == "fit":
        return (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=30[bg];"
                f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    if src_w * 16 <= src_h * 9:                          # already tall: scale and crop the height
        return f"scale={W}:-2,crop={W}:{H}"
    cw = int(src_h * 9 / 16) // 2 * 2
    x = int(round(center_x * src_w - cw / 2))
    x = max(0, min(src_w - cw, x)) // 2 * 2
    return f"crop={cw}:{src_h}:{x}:0,scale={W}:{H}"


def face_center(boxes: list[tuple[float, float, float, float]]) -> float | None:
    """Middle of the biggest face, as a fraction of the width."""
    if not boxes:
        return None
    x, y, w, h = max(boxes, key=lambda b: b[2] * b[3])
    return min(1.0, max(0.0, x + w / 2))


# --------------------------------------------------------------------------- the tool
def run(engine, mission, job, st):
    from . import media, social
    from .doctor import ffmpeg_exe
    from .engine import PartFailed, Stopped
    from .fsutil import atomic_write_text
    from .makers import duration_s
    from .mission import slug
    from .tools import (WHISPER_CODES, _finish, _key, _to_wav, hear, hearing_model, hearing_ready,
                        option_value, chosen_options, parse_json_list, resolve_inputs, tool_dir,
                        whisper_language)

    files, problems = resolve_inputs(engine, job)
    for pr in problems:
        engine.log(f"  INPUT: {pr}")
    if not files:
        st.status, st.note = "failed", "no videos to cut; add one with INPUT: (a file in Inbox)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    ff = ffmpeg_exe(engine.s.comfy.ffmpeg)
    if not ff:
        st.status, st.note = "failed", "Make shorts needs FFmpeg (Setup > System check)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    if not hearing_ready(engine.s) and engine.voice is None:
        st.status, st.note = "failed", "Make shorts needs Joe's voice add-on or whisper.cpp (Setup > System check)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    opts = chosen_options(job)
    try:
        count = max(1, min(12, int(option_value(job, "count") or 5)))
    except ValueError:
        count = 5
    try:
        max_s = float(option_value(job, "length") or 45)
    except ValueError:
        max_s = 45.0
    max_s = max(15.0, min(90.0, max_s))
    min_s = max(10.0, max_s * 0.4)
    crop = option_value(job, "crop") or "face"
    lang = option_value(job, "language") or "english"
    if lang not in WHISPER_CODES and lang != "auto":
        lang = "english"
    model = hearing_model(engine.s.voice.stt_model, lang)
    folder = tool_dir(engine, job, st)
    work = engine.meta / "tmp" / "shorts"
    work.mkdir(parents=True, exist_ok=True)
    font_dir = work / "fonts"
    font_dir.mkdir(exist_ok=True)
    font = Path(__file__).parent / "ui" / "fonts" / "AtkinsonHyperlegible-Bold.ttf"
    if font.exists() and not (font_dir / font.name).exists():
        shutil.copy2(font, font_dir / font.name)
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"Starting '{job.name}': {len(files)} video(s), up to {count} shorts each, "
               f"{int(min_s)}-{int(max_s)} s, crop {crop} -> {st.output}")
    failed: list[str] = []
    import json
    from .picturetools import unique_stems
    keep = folder / ".shorts-done.json"         # what earlier (stopped) runs already made, for shorts.md
    try:
        done = json.loads(keep.read_text(encoding="utf-8"))
        posts, listing = list(done["posts"]), list(done["listing"])
    except (OSError, ValueError, KeyError, TypeError):
        posts, listing = [], [f"# Shorts: {job.name}", ""]
    bases = [it["stem"] for it in unique_stems([{"stem": slug(f.stem)} for f in files])]
    try:
        for vi, src in enumerate(files):
            key = _key(engine, src)
            if key in st.titles:
                continue
            if engine.stop.is_set():
                raise Stopped()
            engine._progress(f"{job.name}: {vi + 1}/{len(files)} {src.name}: listening")
            wav = _to_wav(ff, src, work / (bases[vi] + ".wav"), engine.log)
            if not wav:
                failed.append(f"{src.name}: couldn't read the sound")
                continue
            total = duration_s(ff, src)
            engine.log(f"  {src.name}: writing down every word ({_ts(total)} of video)...")
            r = hear(engine, wav, model, whisper_language(lang), words=True,
                     timeout=max(1800.0, total * 4 + 900))
            try:
                wav.unlink()
            except OSError:
                pass
            if not r.get("ok"):
                failed.append(f"{src.name}: {r.get('error', 'transcribing failed')}"[:200])
                continue
            segs, words = r.get("segments") or [], r.get("words") or []
            if not segs:
                failed.append(f"{src.name}: no speech heard")
                continue
            if total and total < min_s * 1.5:
                failed.append(f"{src.name}: too short to cut shorts from ({_ts(total)})")
                continue
            # 2. the writing model picks moments, a piece of the transcript at a time
            if not engine._text_ready(st):
                return st
            picks: list[dict] = []
            pieces = windows(segs)
            per_piece = max(2, -(-count * 2 // max(1, len(pieces))))
            system = PICK_SYSTEM.format(min_s=int(min_s), max_s=int(max_s))
            extra = (job.format.strip() + "\n") if job.format.strip() else ""
            for pi, piece in enumerate(pieces):
                if engine.stop.is_set():
                    raise Stopped()
                engine._progress(f"{job.name}: {src.name}: finding moments {pi + 1}/{len(pieces)}")
                try:
                    reply = engine._chat(job, pi, "shorts", system,
                                         f"Find up to {per_piece} of the best moments in this part of the video."
                                         f"\n{extra}\nTIMED TRANSCRIPT (seconds):\n{piece}", st)
                except PartFailed as e:
                    engine.log(f"  piece {pi + 1}: {e}")
                    continue
                picks += parse_json_list(reply.text) or []
            chosen = choose(picks, words, count, min_s, max_s)
            if not chosen:
                failed.append(f"{src.name}: no moments found that stand on their own")
                continue
            engine.log(f"  {src.name}: {len(chosen)} moment(s) picked")
            # 3. where's the face? (one frame from the middle of each clip)
            size = media.size_of(ff, src) or (1920, 1080)
            centers: dict[int, float] = {}
            if crop == "face" and size[0] * 16 > size[1] * 9:
                frames = []
                for n, c in enumerate(chosen):
                    fr = work / f"{bases[vi]}-mid-{n}.jpg"
                    if media._run([ff, "-y", "-ss", f"{(c['start'] + c['end']) / 2:.2f}", "-i", str(src),
                                   "-frames:v", "1", "-q:v", "3", str(fr)]) and fr.exists():
                        frames.append((n, fr))
                if frames:
                    from .picturetools import find_faces
                    found = find_faces(engine, job, st, [f for _, f in frames])
                    for n, fr in frames:
                        fc = face_center(found.get(fr) or [])
                        if fc is not None:
                            centers[n] = fc
                        try:
                            fr.unlink()
                        except OSError:
                            pass
            # 4. cut each clip
            base = bases[vi]
            listing += [f"## {src.name}", ""]
            for n, c in enumerate(chosen, 1):
                if engine.stop.is_set():
                    raise Stopped()
                engine._progress(f"{job.name}: {src.name}: cutting short {n}/{len(chosen)}")
                name = f"{base}-short-{n:02d}.mp4"
                vf = crop_filter(size[0], size[1], centers.get(n - 1, 0.5), "fit" if crop == "fit" else crop)
                title = str(c.get("title") or "").strip()[:60] if "title" in opts else ""
                if "captions" in opts or title:
                    ass = work / f"{base}-{n:02d}.ass"
                    ass.write_text(captions(words if "captions" in opts else [], c["start"], c["end"], title),
                                   encoding="utf-8")
                    vf += f",subtitles={ass.name}:fontsdir=fonts"
                cmd = [ff, "-y", "-ss", f"{c['start']:.2f}", "-to", f"{c['end']:.2f}", "-i", str(src)]
                if crop == "fit":
                    cmd += ["-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "0:a?"]
                else:
                    cmd += ["-vf", vf]
                cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(folder / name)]
                ok = _ffmpeg_in(work, cmd)
                if not ok or not (folder / name).exists():
                    failed.append(f"{src.name}: short {n} couldn't be cut")
                    continue
                st.media_files.append(name)
                st.items += 1
                post = str(c.get("post") or "").strip()
                if post:
                    posts.append({"title": title or f"Short {n}", "text": post, "media": [name]})
                listing += [f"{n}. **{title or 'Short ' + str(n)}** ({_ts(c['start'])}-{_ts(c['end'])}, "
                            f"{int(c['end'] - c['start'])} s) -> {name}",
                            f"   Why: {str(c.get('why') or '').strip()}"
                            + (f"\n   Post: {post}" if post else ""), ""]
                engine._record(job=job.job_id, part=n, kind="shorts", model=getattr(engine, "text_model", ""),
                               ok=True, seconds=round(c["end"] - c["start"], 1))
            st.titles.append(key)
            engine._save_state(job, st)
            try:
                atomic_write_text(keep, json.dumps({"posts": posts, "listing": listing}))
            except OSError:
                pass
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {len(files)} video(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    if len(listing) > 2:
        atomic_write_text(folder / "shorts.md", "\n".join(listing).rstrip() + "\n")
        if "shorts.md" not in st.media_files:
            st.media_files.append("shorts.md")
    if posts and "posts" in opts:
        for f in social.write(folder, "shorts", posts):
            if f.name not in st.media_files:
                st.media_files.append(f.name)
    keep.unlink(missing_ok=True)
    return _finish(engine, job, st, len(files), failed)


def _ffmpeg_in(cwd: Path, cmd: list[str]) -> bool:
    """Run FFmpeg from the work folder, so the subtitle file and fonts need no path escaping."""
    import subprocess
    from .system import no_window_flags
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, timeout=3600, creationflags=no_window_flags())
        return p.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
