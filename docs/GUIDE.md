# Joe — the full guide

Everything about missions, keys, screens and the command line. New here? Start with the [README](../README.md).

## Workspace

Default: `Documents\Joe-ai`.

```
Inbox\      reference files you drop in (facts, price lists) — read with INPUT:
Output\     everything Joe writes, plus _REPORT.md, _log.txt, _progress.txt
Projects\   project profiles: brand voice, facts, rules (one .md per project)
Missions\   saved mission files
Workflows\  ComfyUI workflows in API format (optional; image tasks have a built-in one)
Themes\     custom color themes (made in F10, or by hand)
```

Settings live in `%APPDATA%\joe-ai\settings.json`, never in the app folder.

## Just describe it (Queue, F2)

The big box on the Queue screen takes plain words: "40 product descriptions for handmade mugs,
friendly and short, plus 8 pictures of mugs on a wooden table". Press **MAKE A PLAN** (or
Ctrl+Enter). Joe's local model writes the mission and you see it in plain words:

```
JOE'S PLAN — about 14 minutes
 • 40 items: Mug descriptions
 • 8 pictures: Mugs on a table
```

**RUN IT** starts it (or puts it in line if Joe is busy), **CHANGE IT** opens it in the Builder,
**START OVER** clears it. Nothing runs until you press RUN IT. The mission text itself is under
**ADVANCED** for anyone who likes editing it by hand; the plan updates as you edit.

## Building it step by step (F4)

The Builder makes the mission for you with simple forms:

- **+ ADD SOMETHING**, pick what it is (a list of things, a document, a spreadsheet, pictures,
  short video clips) and fill in the blanks: **How many?**, what each one looks like, how many
  **versions of each picture**, the **shape** of the pictures. Joe splits big counts into small
  batches himself so the AI stays sharp.
- **MORE OPTIONS** holds the rest: file name, profile, batches, models, seed, ComfyUI workflow.
- **↑ ↓** reorder, **COPY** duplicates, **SPLIT** cuts one in two, **REMOVE** takes it off.
- **MORE** (left) has the profile, IMPORT for a pasted mission, and START OVER.
- **RUN IT** starts it. **ADD TO QUEUE** adds it after whatever Joe is doing. Queued missions
  run one after another until all are done, with one combined morning report. Sleep/shut down
  happens only after the last one.
- **SAVE** keeps it in `Missions\` under a name. **PAST MISSIONS** lists every mission you've
  run, how many tasks finished, and LOAD / RUN buttons to revisit one.

## First start, tabs and looks

The first time Joe opens, a setup helper walks through it one step at a time: your graphics card
in plain words, the writing model (the only must-have), pictures, talking, extras, and a look.
Each **YES** installs just that one thing. Reopen it any time: Setup (F10) > **SETUP HELPER**.

Every screen has a tab along the top (the F-keys still work). Hover over any button and the
bottom line says what it does.

Looks (Setup > Display > Theme): **Modern** (follows your PC's day/night setting), **Modern day**,
**Modern night**, **Futuristic**, and the **Retro** green, amber and white screens (the old-screen
effect only applies to the retro looks). CUSTOM THEME still designs a retro-style look from a
description.

Joe opens fresh every time. If the last run didn't finish (stopped, crash, power cut), he asks on
start: **Y** resumes where it stopped, **N** starts fresh (it stays in History).
Pictures and video always run after the writing tasks, so the GPU switches over only once.

## Comfort (Setup > Comfort)

- **Chime when Joe is done**: a soft chime when a run finishes (a lower one if something didn't).
- **Screen saver**: after this many minutes without the mouse or keyboard (default 10, 0 = off)
  the window goes dark with a small, slowly drifting status line. Any key or mouse move wakes it.
- **Quiet hours** (e.g. 22:00 to 07:00): no chimes and no phone pings. A ping waits until they end.
- **Phone ping when done** (off until you set it): install the free ntfy app, subscribe to a topic
  name only you know, type the same name in Setup and press SEND A TEST PING. Joe sends one short
  line when a run is done ("Joe is done: 3 of 3 tasks done, 48 items."), nothing from your files.
  It's the only thing Joe ever sends off your PC, and only when you turn it on.

## Talking to Joe (F6)

Press **F6** to open Talk. The mic is open while that screen is up (MIC ON / MIC OFF button):
just talk, and when you pause Joe hears it and answers. He doesn't listen while he's speaking,
and the mic closes when you leave Talk. Prefer push-to-talk? F10 > Voice > How to talk >
Push-to-talk, then SET KEY and press any key; hold it anywhere in Joe to talk. Typing works without any setup. For voice, run F10 > System check > "Joe's voice"
once: Joe installs uv, makes a private Python 3.12 just for speech (your Python is left alone),
then installs faster-whisper (hearing) and Kokoro (his voice). Everything runs on the CPU and
lives in `%LOCALAPPDATA%\joe-ai\addons`. Recordings are deleted right after they're heard.

Ask how the run is going, what failed, or tell him what you need done. If he writes a mission,
it shows up with OPEN IN BUILDER and RUN IT buttons: Joe never starts work on his own.
F10 > Voice picks his voice, speed, and how carefully he listens. The report screen has
READ IT TO ME; the About page has HEAR JOE TELL IT.

### Make Joe sound like me (optional)

System check offers **Voice copy** on PCs with an NVIDIA card (6 GB+). It installs Chatterbox
(Resemble AI, MIT license) and PyTorch, about 3 GB, in its own environment. Then F10 > Voice >
MAKE JOE SOUND LIKE ME: tick "this is my own voice", press RECORD and read the passage
(about 30 seconds). Pick "My voice" in the voice list. The recording lives only in
`%LOCALAPPDATA%\joe-ai\addons\voice\myvoice` and is never shared, exported or packaged;
DELETE MY VOICE removes it. While a run is using the graphics card, Joe speaks with the
built-in voice instead. Chatterbox marks its audio with an inaudible watermark.

### Dropping files into Talk

Drag files onto Joe's window (or press ATTACH). They're copied to `Inbox\dropped\` and go with
your next message. Say "read it" to hear a file word for word, or ask anything about it.
Text, Markdown, CSV, JSON, Word (.docx), web pages and PDFs work (PDFs use the voice add-on's
Python; the PDF reader is added the first time). Pictures need a vision model in Ollama;
System check offers one that fits your graphics card.

## Finished documents (EXPORT)

`EXPORT: docx, pdf, epub` on a writing task makes finished copies next to the .md when it's
done (also `odt`, `html`). In F3, P makes Word + PDF copies of any .md file. Needs Pandoc
(System check installs it); PDFs are printed by Microsoft Edge, so no LaTeX is needed.


The smallest mission is one line:

```
TASK: 20 Instagram captions for a small bakery  CHUNKS: 4 x 5
```

Joe picks where to save it (`Output\<project>\<task name>.md`). Add more when you want more
control:

```
PROJECT: My Shop   RULES: Warm, plain voice. No exclamation marks.
TASK: Product blurbs  CHUNKS: 6 x 8  MIN WORDS PER ITEM: 60
FORMAT: One paragraph describing look, feel and use. End with a care tip.
INPUT: price-list.txt
```

The `=== JOE MISSION ===` and `=== END ===` lines are optional (handy when a mission sits
inside a longer message).

| Key | Meaning |
|---|---|
| `PROJECT` | Loads `Projects\<name>.md` (or its slug, e.g. `my-shop.md`) into every prompt |
| `RULES` | Before the first TASK: applies to all tasks. After a TASK: that task only |
| `TASK` | Task name; starts a new task |
| `SAVE` | Optional. Output file, relative to `Output\` (`.md` added if no extension). Left out: `<project>\<task name>.md`. Ending in `.mp4` makes it a video task, `.png` a picture task |
| `CHUNKS` | `parts x items per part`, e.g. `8 x 10` |
| `MIN WORDS PER ITEM` | Short items are expanded, or marked `[SHORT]` |
| `FORMAT` | Format rules, repeated every part |
| `INPUT` | Comma-separated text files from `Inbox\` used as reference facts |
| `MODEL` | Override the default model for this task |
| `TYPE` | `text` (default), `code`, `image`, `video` |
| `PART` | Repeat once per part with that part's instructions (instead of `CHUNKS`). The model's text is kept as written — good for documents and design docs |
| `HEADER` | Column names; required when `SAVE` ends in `.csv`. Rows are parsed, checked and re-quoted so the file always imports cleanly |

`PROJECT` can also go on a task's line to use a different profile for that task.

### Image and video tasks

```
TASK: Mood boards  SAVE: studio/moods  TYPE: image  CHUNKS: 2 x 5  VARIANTS: 2
FORMAT: Soft morning light, fresh bread on a wooden table, muted earth tones.
SIZE: 1216 x 832  NEGATIVE: text, watermark  MODEL: sdxl
```

`SAVE` is a folder. `CHUNKS 2 x 5` = the model writes 10 prompts; `VARIANTS: 2` draws each
twice (20 pictures). Or use `PART:` lines (one picture brief each); `PROMPTS: as written`
sends them to ComfyUI unchanged. `MODEL` = part of a checkpoint file name; without it the
best installed model for your GPU is used. `SEED: 1234` makes runs repeatable.

No `WORKFLOW` = a built-in text-to-image graph for SD 1.5 / SDXL checkpoints.

**Video without a workflow file:** System check offers Wan 2.2 5B (Apache 2.0, about 18 GB,
needs an 8 GB+ graphics card). After it downloads, restart ComfyUI once. Then
`TASK: Shop tour  SAVE: clips/tour.mp4` (or `TYPE: video`) makes about 5-second 1280 x 704
clips at 24 fps, one per prompt. `SIZE` changes the size; `FPS` the speed.

For Flux, other video models or anything fancy, build it in ComfyUI, then
**Workflow → Export (API)** and drop the file in `Workflows\`. Joe finds the prompt box, seed, size, model and save node by
itself, or you can type `{{PROMPT}}`, `{{NEGATIVE}}`, `{{SEED}}`, `{{WIDTH}}`, `{{HEIGHT}}`
into the workflow before exporting. With your own video workflow, frames or GIFs are
turned into MP4 with FFmpeg (`FPS: 16`).

Each folder gets `_prompts.md` and `_media.json` (prompt, seed, model, review marks).
These are AI pictures: never present them as photos of real products.

## Storage (F8)

F8 shows how much room each folder takes, the disk's free space, and four CLEAN buttons
(each asks first and moves files to the Recycle Bin): pictures you marked X, old `_v2`/`_v3`
versions (the newest is kept, and picture folders with a K or S mark are never touched),
reports older than 30 days, and leftover ComfyUI copies. Logs trim themselves at 2 MB.
ComfyUI keeps its own copy of every picture; Joe removes it once he has saved his
(F10 > ComfyUI, on by default). Only ComfyUI's `output\Joe` folder is ever touched.

Keys are UPPERCASE and must start a line or follow two spaces, so prose such as
"Note: …" inside a value is left alone. Values can span several lines.

## Running it

Needs Python 3.11+ (python.org) and Ollama with a model pulled (default `qwen3:14b`).

**Double-click `Joe.pyw`.** A window opens (Microsoft Edge in app mode, no
tabs). Paste a mission, press **F5**. You can close the window; the run keeps going.
Double-click again to check on it. F1 shows all keys.

| Key | Screen |
|---|---|
| F1 | Help |
| F2 | Queue: mission box, progress, log (R = morning report, C there copies it) |
| F3 | Files: arrows, Enter, Backspace; O = Explorer, E = Notepad, C = copy path; T = thumbnails, K/X/S = keep/reject/star, M = make MP4 |
| F5 | Run / stop |
| F8 | Stats and storage: space used, clean-up buttons |
| F9 | About Joe and the license |
| F10 | Setup: system check, models, ComfyUI, themes (incl. custom AI-made ones), CRT effect |

The status bar shows the GPU live: temperature, load, memory, power and fan. It flashes
when the GPU gets within 5 °C of the pause temperature.

Crashes are written to `%APPDATA%\joe-ai\crash.log`.

### Command line (optional)

```
python -m joeai init                 # creates settings + workspace
python -m joeai status               # is Ollama up? is the model 100% on GPU?
python -m joeai doctor               # system check; asks before installing anything
python -m joeai check my-mission.txt # validate + time estimate, writes nothing
python -m joeai run my-mission.txt   # go (Ctrl+C stops cleanly; run again to resume)
python -m joeai run -                # paste a mission instead of using a file
```

Mission files are read from `Missions\`. In the morning, open `Output\_REPORT.md`.


## Development

```
pip install pytest
python -m pytest
```

Tests use fake Ollama and ComfyUI servers, so no GPU is needed.
