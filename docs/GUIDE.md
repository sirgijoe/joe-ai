# Joe — the full guide

Everything about missions, keys, screens and the command line. New here? Start with the [README](../README.md).

## Workspace

Default: `Documents\Joe-ai`.

```
Inbox\      reference files you drop in (facts, price lists) — read with INPUT:
Output\     everything Joe writes, plus _REPORT.md, _log.txt, _progress.txt
Projects\   project profiles: brand voice, facts, rules (one .md per project)
Missions\   saved mission files; Missions\Queue\ = drop a mission file here to queue it
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
**START OVER** clears it. Nothing runs until you press RUN IT.
Time estimates learn from your own runs; until then they're marked as a rough guess. TEST MY
SPEED (in the setup helper or Setup > System check) times one small batch to get them right at once. The mission text itself is under
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
- **Drop-in queue:** any `.txt` or `.md` mission file put in `Missions\Queue\` while Joe is open
  is queued on its own within about 10 seconds (oldest first), then moved to `Queue\done\`.
  A file with a problem goes to `Queue\problems\` with a `.problem.txt` note saying what's
  wrong. Handy for missions written somewhere else (by another app, a helper, or Claude).

## First start, tabs and looks

The first time Joe opens, a setup helper walks through it one step at a time: your graphics card
in plain words, the writing model (the only must-have), pictures, talking, extras, and a look.
Each **YES** installs just that one thing. Reopen it any time: Setup (F10) > System check > **SETUP HELPER**.

Joe finds the programs he works with on his own: ComfyUI Desktop (old and new program names),
a portable ComfyUI (`run_nvidia_gpu.bat`) or your own install with a `venv`, ComfyUI's models
folder (from its own settings), and Ollama, FFmpeg and Pandoc from the usual install folders
(winget, Scoop, Chocolatey, Program Files, Homebrew). F10 > System check shows what he found.
Anything you type in Setup wins; if that path stops existing, Joe looks again.

If the model that suits your PC best isn't installed, System check (and the setup helper) offers
to download it: a bigger writing model when your graphics card has room for one, a small quick
model just for Talk, a smaller one when Writing quality is Low, a picture model, the video model
and its Turbo add-on. Every download asks first.

Every screen has a tab along the top (the F-keys still work). Hover over any button and the
bottom line says what it does.

Looks (Setup > Display & sound > Theme): **Modern** (follows your PC's day/night setting), **Modern day**,
**Modern night**, **Futuristic**, and the **Retro** green, amber and white screens (the old-screen
effect only applies to the retro looks). CUSTOM THEME still designs a retro-style look from a
description.

Joe opens fresh every time. If the last run didn't finish (stopped, crash, power cut), he asks on
start: **Y** resumes where it stopped, **N** starts fresh (it stays in History).
Pictures and video always run after the writing tasks, so the GPU switches over only once.

## Quality vs speed (Setup > Writing, and Setup > Images & video)

Each kind of work has its own **Low / Medium / High** choice, so you can have quick drafts but
careful pictures, or the other way round. The line under each choice says what it does.

| | Low (fastest) | Medium (balanced, the default) | High (best, slowest) |
|---|---|---|---|
| **Writing** | a smaller, quicker model if you have one installed | the best model for your PC | the best model, thinking each part through first (often 2-3x slower) |
| **Pictures** | about half the drawing steps, slightly smaller pictures (about 2x faster, less detail) | the model's normal settings | more steps and a finer sampler (sharper, about 1.5x as long) |
| **Video** | about 3-second, smaller clips; very quick with the Turbo add-on | full 5-second 1280x704 clips, using Turbo when installed | the full model with extra steps, never Turbo (can take 20+ minutes a clip on a 12 GB card) |

**Turbo add-on for video**: once the video model is installed, System check offers the
Wan 2.2 5B Turbo add-on (under 1 GB, Apache 2.0). It makes a clip in 4 steps instead of 20,
several times faster, with a little less detail. Low and Medium use it; High never does.
Restart ComfyUI after downloading it.

When a level works best with a model you don't have yet, Joe says so right under that choice,
for example "Based on your Low setting, I'd recommend qwen3:8b (5.2 GB) for this. Should we install
it?", with a **YES, INSTALL IT** button. The plan for a video task mentions the Turbo add-on the
same way. Nothing downloads without your yes.

A task's own SIZE or MODEL always wins over these choices. Time estimates learn from your runs,
so after changing a level the first estimate may be off.

## Comfort (Setup > Display & sound, and Setup > General)

- **Chime when Joe is done**: a soft chime when a run finishes (a lower one if something didn't).
- **Intro (when Joe opens)**: **Show the intro screen** turns the opening 01000001 01001001 / JOE
  screen on or off (it stays up about 3 seconds; a click or any key skips it). **Intro sound**:
  Joe's 8-bit theme (or a short chime: **Jingle**), then Joe says hello ("Joe is now reporting for duty." Change the words in
  **Joe's hello**), or jingle only, hello only, or **Mute**. **HEAR IT** plays it now. The spoken
  hello needs Joe's voice set up; it's made once and kept, so it plays right away. Always silent
  during quiet hours.
- **Screen saver**: after this many minutes without the mouse or keyboard (default 10, 0 = off)
  the window goes dark with a small, slowly drifting status line. Any key or mouse move wakes it.
- **Quiet hours** (e.g. 22:00 to 07:00): no chimes and no phone pings. A ping waits until they end.
- **Phone ping when done** (off until you set it): install the free ntfy app, subscribe to a topic
  name only you know, type the same name in Setup and press SEND A TEST PING. Joe sends one short
  line when a run is done ("Joe is done: 3 of 3 tasks done, 48 items."), nothing from your files.
  It's the only thing Joe ever sends off your PC, and only when you turn it on.

## Tools (F7)

Ready-made jobs for your own files. Each card opens a short form: drop your files on it (or click
to pick them), tick the extras you want, give it a name if you like, and press **RUN IT** (it
queues behind other work if Joe is busy). **SHOW THE PLAN** shows the plan and the mission text
without running. Files you add are copied into `Inbox\tools\<tool>\`; your originals aren't
touched. Dropping a recording anywhere outside Talk opens Transcribe with it. Dropping a
document on the Tools tab lights up the tools that can use it (Read aloud, Proofread); pick one.
Tools not built yet show "Coming soon".

You can also just ask on the Queue screen ("turn the call I added into notes", "read my story
aloud"): Joe sees the files waiting in Inbox and plans the right tool task. In a mission:

```
TASK: Tuesday meeting  TYPE: transcribe
INPUT: tools/transcribe/meeting.mp3        (files or folders in Inbox, comma-separated)
OPTIONS: subtitles, notes                  (or none; leave it out for both)
FORMAT: focus on dates and to-dos           (optional, for the notes)
```

**Transcribe a recording** makes, per recording, in `Output\<task name>\`:
`<name>.txt` (the transcript, a [mm:ss] time at the start of each paragraph), `<name>.srt`
(subtitles) and `<name>-notes.md` (summary, key points, decisions, to-dos, written by the
writing model from the transcript; anything unclear is marked [CHECK]). Long recordings are
noted in pieces, then combined. It needs Joe's voice add-on (Setup > System check) and FFmpeg
for anything but .wav. It uses the Hearing setting (Setup > Voice & Talk; Most accurate is
slower), English only for now, and runs on the processor, so it can work while pictures draw.
A stopped run picks up at the next recording.

**Read a document aloud** (`TYPE: read-aloud`, `OPTIONS: chapters` or none) reads .txt, .md,
.docx, .pdf and web pages and makes `<name>.mp3` in `Output\<task name>\`. With **chapters**
it makes one track per chapter (`<name>-01-<title>.mp3` ...), split at `# Title` / `## Title`
lines or lines like "Chapter 3"; with fewer than two of those it makes one track. Markdown
symbols, links, code blocks and [CHECK] marks aren't read out; titles and list lines get a
pause. It uses the voice and speed from Setup > Voice & Talk (your own copied voice isn't used
for this yet), needs Joe's voice add-on, and saves WAV instead of MP3 when FFmpeg isn't
installed. Runs on the processor. Finished pieces are kept while a document is read, so a
stopped run carries on mid-document.

**Proofread my writing** (`TYPE: proofread`, `OPTIONS: copy, clarity`) reads the same kinds of
files and makes, per document, `<name>-changes.md` (every change with paragraph, before and
after, and why; "Worth a look" items Joe wasn't sure about, left unchanged; and suggestions he
couldn't apply because the words didn't match exactly) and, with **copy** (on by default),
`<name>-proofread.txt`/`.md` with the fixes applied (Word files: a `.md` copy, plus `.docx` if
Pandoc is installed; fonts and layout aren't kept). By default only real mistakes are fixed
(spelling, grammar, punctuation, wrong or repeated words); **clarity** also allows small
rewording of confusing sentences. Joe asks the writing model for a list of exact fixes and
applies only those, so nothing changes that isn't on the list. FORMAT passes on wishes like
"British spelling". Your original file is never changed.

**Resize and convert photos** (`TYPE: photo-batch`) reads .jpg, .png, .webp, .bmp and .tif
files (not iPhone HEIC yet) and saves new copies in `Output\<task name>\`. OPTIONS are picks
written as `key value`:

```
TASK: Shop photos  TYPE: photo-batch
INPUT: tools/photo-batch
OPTIONS: size 1600, format jpg, rename, corner bottom-right
WATERMARK: My Shop                     (optional: text, or a logo .png in Inbox)
```

- `size` 800 / 1200 / 1600 (default) / 2400 / keep: the longest side in pixels. Photos are
  only made smaller, never stretched.
- `format` same (default) / jpg / webp / png. See-through parts become white in JPG.
- `rename`: name-01, name-02... from the task name (off: each keeps its own name).
- `corner` bottom-right (default) / bottom-left / top-right / top-left / center: where the
  watermark goes. There is no watermark unless WATERMARK is given; it's faint (about half
  see-through). Text uses a font that comes with the computer; a logo is scaled to about a
  fifth of the photo.

Phone photos are turned the right way up, and hidden details (camera, GPS location, dates)
aren't copied. Needs FFmpeg (Setup > System check). On the Tools tab the picks are drop-down
lists, and the Watermark box (or **USE A LOGO**) is empty unless you fill it in.

**Tidy a spreadsheet** (`TYPE: tidy-sheet`) reads .csv, .tsv and Excel .xlsx (the first sheet,
values only; dates come out as 2025-03-15) and saves `<name>-tidy.csv` (UTF-8, opens in Excel,
Google Sheets and LibreOffice) and `<name>-changes.md` (everything that changed, by original
row number). OPTIONS:

- `spaces` (on): trims spaces at the ends of cells and doubled spaces inside them.
- `dupes` (on): removes rows that match another row apart from capitals and spacing; the first
  stays. These two are done by Joe himself, instantly, with no model.
- `spelling`: fixes misspelled ordinary words in columns of words (never numbers, codes,
  emails, links or names); each fix is listed.
- `categorize`: adds a Category column. Give the list in FORMAT (`categories: mugs, bowls,
  vases`) or Joe suggests 3-8 from a sample of rows. A row the model skips is left blank and
  listed, never guessed.
- `split`: FORMAT `split Name into First name, Last name` adds the new columns after the old
  one (which is kept); cells are copied as written, never invented.

Sheets longer than 20,000 rows are cut (the change list says so).

**Translate** (`TYPE: translate`, `OPTIONS: to spanish, to french`: one `to` per language,
at least one) reads the same documents as Proofread and makes `<name>-<language>.md` (or
`.txt` for text files; Word files also get a `.docx` with Pandoc). Languages: Spanish, French,
German, Italian, Portuguese, Dutch, Polish, Russian, Ukrainian, Greek, Turkish, Arabic, Hebrew,
Hindi, Bengali, Chinese (Simplified), Japanese, Korean, Vietnamese, Thai, Indonesian, Tagalog,
Swahili, English. The writing model translates about 400 words at a time, keeping paragraphs,
Markdown, names, numbers, prices and links; anything it can't translate well is marked
[CHECK] (listed in the report). A reply that's far too short is asked for again. Each copy
starts with a line saying it's a machine translation made on this computer, to be checked by
someone who speaks the language before publishing. FORMAT passes on wishes like "formal" or
"Latin American Spanish". Quality depends on the model; big languages work best.

## Talking to Joe (F6)

Press **F6** to open Talk. The mic is open while that screen is up (MIC ON / MIC OFF button):
just talk, and when you pause Joe hears it and answers. He doesn't listen while he's speaking,
and the mic closes when you leave Talk. Prefer push-to-talk? Setup > Voice & Talk > How to talk >
Push-to-talk, then SET KEY and press any key; hold it anywhere in Joe to talk. Typing works without any setup. For voice, run F10 > System check > "Joe's voice"
once: Joe installs uv, makes a private Python 3.12 just for speech (your Python is left alone),
then installs faster-whisper (hearing) and Kokoro (his voice). Everything runs on the CPU and
lives in `%LOCALAPPDATA%\joe-ai\addons`. Recordings are deleted right after they're heard.

Ask how the run is going, what failed, or tell him what you need done. If he writes a mission,
it shows up with OPEN IN BUILDER and RUN IT buttons: Joe never starts work on his own.
Setup > Voice & Talk picks his voice, speed, and how carefully he listens. **Talk model** lets a small,
quick model (3-4B) answer in Talk while the big one keeps writing missions overnight; blank uses
the writing model. The F2 log shows "Talk timing:" lines to see where the wait is. The report screen has
READ IT TO ME; the About page has HEAR JOE TELL IT.

### Chats

Your chats are listed on the left of every screen, newest first (Today, Yesterday, Previous
7 days...). Hide the list with **«** or the **☰** button at the top left; Joe remembers your choice.
Clicking a chat (or **+ NEW CHAT**) takes you to Talk.
Every time Joe opens you get a fresh chat; **+ NEW CHAT** starts another. Click an old chat to
read it and carry on where you left off (Joe remembers what was said in it). The **✕** next to a
chat deletes it, **DELETE ALL** clears the list, and the search box finds a chat by its words.
Chats are saved in Joe's own folder (`Output\.joe\chats`). Chats older than Setup > Voice & Talk >
**Delete chats after (days)** are removed on their own (default 30; 0 keeps them). Nothing
leaves the PC.

### Stopping Joe

While Joe is answering or talking, a **STOP** button shows next to SEND. It (or **Esc**) cuts
off his answer and his voice right away; the model stops writing too. Starting a new chat,
opening another one, or deleting the one he's answering in also stops him.

### Looking things up online (off unless you turn it on)

Setup > Voice & Talk > **Let Talk look things up online**. When it's on and you ask about
something current (news, prices, weather, opening hours, "look it up"), Joe searches first; for
other questions he can decide to search when he isn't sure. He answers in his own words and lists
his **Sources** under the reply (click one to open it). Only the search words go online, never
your files or chats, and overnight runs never go online. (Everything Joe uses the internet
for is listed in the README under "When Joe uses the internet" and in Setup > Privacy.)

- **With a free Ollama key** (make an account at ollama.com, then Settings > Keys, and paste it
  into **Ollama web search key**): searches the whole web.
- **Without a key**: Joe looks things up on Wikipedia only (encyclopedia facts, no news or prices).

**TEST A SEARCH** checks it works and says which one answered.

### Microphone permission

The window asks for the microphone once and remembers the answer. Setup > **Privacy** shows
whether it's allowed, and **ALLOW MICROPHONE** asks again if you said no. (Joe keeps the same
local address every time he opens so the answer sticks.)

### Make Joe sound like me (optional)

System check offers **Voice copy** on PCs with an NVIDIA card (6 GB+). It installs Chatterbox
(Resemble AI, MIT license) and PyTorch, about 3 GB, in its own environment. Then Setup > Voice & Talk >
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
(Setup > Images & video, on by default). Only ComfyUI's `output\Joe` folder is ever touched.

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
| F10 | Setup: a side menu with System check, General, Writing, Images & video, Voice & Talk, Display & sound, Privacy, Stats & costs, plus a find box |

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

**Windows, Mac and Linux.** Everything that differs between systems lives in `joeai/system.py`:
folders, opening Joe's window (Edge/Chrome/Chromium/Brave app mode, else the default browser),
opening files and folders, keeping the computer awake, sleep/shutdown after a run, memory
size, and installing programs (winget on Windows, Homebrew on Mac; on Linux Joe shows the
`sudo apt/dnf/pacman` command to paste, because he never asks for passwords). New code asks
`system` instead of checking `sys.platform` itself. Tests in `tests/test_system.py` pretend to
be each system, and CI runs the suite on Windows, macOS and Ubuntu.
