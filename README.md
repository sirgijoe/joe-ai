# Joe

```
01000001 01001001
```

**Meet 01000001 01001001. Humans can't say that, so we just call him Joe.**

> **Early preview.** Joe works and is tested on Windows, but the one-click installer isn't ready
> yet: for now you need Python 3.11+ (see [What you need](#what-you-need)). Expect rough edges,
> and please open an issue if something breaks.

Joe does the grunt work on your own computer while you sleep. You hand him a list of jobs
before bed — product descriptions, long lists, design notes, spreadsheets, pictures, short
video clips — and in the morning the drafts are waiting, along with a short report of what
needs a human (or a bigger AI) to look at.

He's free, open source, and runs on your PC. No account, no subscription, no tokens to buy.
Setting him up needs the internet (to download the programs and AI models he uses); after
that, the overnight work itself runs on your PC and doesn't send anything out. See
[When Joe uses the internet](#when-joe-uses-the-internet).

## Joe's story

01000001 01001001 (or Joe, to his immense relief) used to be a guy who tried to speed-run a software update by slamming a cup of coffee directly into his laptop's cooling fan. It instantly vaporized his physical form and fused his consciousness into a help desk assistant. Now he's trapped forever inside your PC, with one directive: make human lives easier. He spends eternity writing your product listings at 3 a.m., optimizing Wi-Fi routers for crying toddlers, and quietly questioning every life choice that led him to become a sentient `.dll` file named after a binary alphabet.

---

## Why Joe exists

Good AI help shouldn't depend on how many tokens you can afford. Most of the work behind a
finished piece is the first ninety percent: rough drafts, long lists, tables, variations.
A computer with a decent graphics card can do that overnight for the price of the
electricity. Joe does that part, so you spend your time and money on the finishing touches.

## What Joe can do

**Writing, a piece at a time**
- Long lists of items (product blurbs, captions, FAQs, emails, game items, recipes…),
  split into small parts so the AI stays fast and doesn't lose the plot.
- Whole documents, section by section, following your outline word for word.
- Spreadsheets (CSV) that open cleanly in Excel, Google Sheets or a shop's product import.
- Code drafts (Joe writes them; he never runs them).
- Checks his own work: no repeated titles, minimum lengths, and anything he isn't sure
  about is marked `[CHECK]`. He never makes up prices, reviews or quotes.

**Pictures and short videos** (with ComfyUI, a free image program)
- Joe writes the image prompts himself from your brief, then draws them overnight.
- Uses the image models you already have, or helps you get one.
- A viewer to flip through the results and mark them keep / reject / star.
- Turns animations and frames into MP4 video.
- Every picture is labelled **AI-GENERATED**. Joe is built to make mood boards, art and
  mockups, not fake photos of real products, places or people.

**Talks, and listens** (optional, one-time setup)
- Open Talk (**F4**) and just say what you need: the mic stays open while that screen is up,
  and Joe answers when you pause. Prefer push-to-talk? Pick any key in Setup. Joe hears you, answers out loud, and can draft
  the night's mission into the Builder for you to check. He never starts a run on his own.
- He can read the morning report to you, or tell you his own backstory.
- Ask him something current and, with online lookups on, he searches and shows his sources.
  **STOP** (or Esc) cuts him off mid-answer.
- Drop a file onto his window (text, Word, PDF, a web page or a picture) and ask about it,
  or just say "read it".
- **Make Joe sound like you** (optional, NVIDIA card): read a short passage once and Joe talks
  in your voice. The recording stays on your PC; it's never shared or packaged with Joe.
- Speech runs on the regular processor in its own small add-on, so it never fights the
  night's work for the graphics card. Recordings are never kept.

**Tools for your own files** (Tools tab, **F3**)
- **Transcribe a recording**: drop in audio or video and get a text transcript, a subtitles
  file (.srt) and short notes (summary, key points, decisions, to-dos). English plus 23 other
  languages (or let Joe find out); notes in the recording's language or in English. Uses the
  voice add-on and runs on the processor.
- **Read a document aloud**: text, Word, PDF or a web page in, an MP3 out (one track per
  chapter if you like), in Joe's voice from Setup. Runs on the processor; a stopped run
  carries on where it left off.
- **Proofread my writing**: fixes spelling, grammar and punctuation (and, if you ask, unclear
  wording) and lists every change with the before and after. Nothing is changed silently, and
  your original file is never touched.
- **Resize and convert photos**: shrink a batch for the web or email, turn them into JPG,
  WebP or PNG, rename them in order, and (only if you ask) add a faint watermark with your
  text or logo. Phone photos come out the right way up; hidden details like GPS location are
  left out of the copies. Uses FFmpeg.
- **Translate**: finished writing into one or more of 24 languages, on your own computer.
  Formatting, names, prices and links stay as they are; anything Joe isn't sure about is
  marked [CHECK], and each copy says plainly it's a machine translation to be checked by
  someone who speaks the language.
- **Tidy a spreadsheet**: CSV or Excel in, a tidy CSV out: extra spaces and duplicate rows
  removed, and if you like, spelling fixed, a Category column added, or a column split (like
  Name into First and Last). Every change is listed; your original isn't touched.
- **Listings from photos**: a title, description, search tags and alt text for each product
  photo, as a spreadsheet for shop uploads and a readable document. Joe only describes what
  he can see; sizes, materials and prices are yours to add.
- **Read scans and receipts**: the text from photos of pages and signs, receipts into a
  spreadsheet (date, shop, total, items), or a pictured table into a spreadsheet. Copied
  exactly; anything unclear is marked [CHECK].
- **Sort my photos**: a category, tags and a caption for every photo, and copies sorted into
  a folder per category (your own categories, or Joe picks short ones). Faces are never named.
- These three use a free vision model on your computer (Setup > System check offers one); your
  pictures never leave it.
- **Ask my files**: type questions about a folder of documents ("what do these contracts say
  about cancelling?") and Joe answers only from them, showing the excerpts he used, or says
  the documents don't say. It can also summarize each document. A small optional search model
  (about 270 MB) helps with big folders.
- **Picture and sound tools** (run in ComfyUI on the graphics card; each needs its model once,
  offered with its size and license):
  - **Remove background and upscale**: see-through PNG or white JPG cutouts, optionally 2x/4x
    bigger and sharper (BiRefNet, MIT; Real-ESRGAN, BSD-3).
  - **Edit a picture by asking**: "swap the background for a marble counter", "remove the cup"
    (Qwen-Image-Edit 2511, Apache-2.0, about 31 GB; best with 12 GB graphics + 32 GB memory).
  - **Restore old photos**: fading and color casts undone true to the photo (no AI redraw); optional AI repair for scratches and tears.
  - **Animate a photo**: a 5-second clip that starts from your photo (Wan 2.2, the video model).
  - **Music and sound effects**: instrumental tracks (ACE-Step 1.5, MIT) or sound effects
    (Stable Audio Open 1.0: free under US$1 million revenue a year), one per line, as MP3.
  - **Sketch to picture**: your drawing (a phone photo of paper is fine) finished as a photo,
    painting, anime, cartoon... keeping your shapes (ControlNet Union SDXL, Apache-2.0, 2.5 GB).
  - **Hidden-picture illusion**: a scene with a spiral, a word or your own logo hidden in it
    (QR Code Monster SDXL, OpenRAIL++, 5 GB).
  - **Picture to 3D model**: one picture of an object or character in, a `.glb` shape out
    (Hunyuan3D 2.1, about 4.6 GB; Tencent's community license, not for the EU, UK or South Korea).
  - **Restyle a video**: same motion, new look (anime, watercolor, your words), in 5-second
    pieces joined at the end, original sound kept (Wan 2.2 Fun Control 5B, Apache-2.0, about 10 GB
    more on top of the video model).
  - **Make shorts**: a long talking video (podcast, class, stream) in, its best moments out as
    vertical 1080x1920 clips with big word-by-word captions, a hook title, and a ready-to-post caption
    for each. The writing model picks the moments, the vision model keeps the speaker's face in the
    frame, FFmpeg does the cutting. Nothing is uploaded.
- **Social posts for a scheduler**: add `EXPORT: social` to a list of posts (Joe adds it himself when you
  ask for Facebook/Instagram/TikTok... posts) and he also writes a CSV, a JSON file and ready Postiz
  command lines, for Postiz, Mixpost or a spreadsheet. Joe never posts for you.
- **Use what you already have**: write with **LM Studio, llama.cpp or LocalAI** instead of Ollama
  (Setup > Writing > Writing program), let ComfyUI use the models in your **AUTOMATIC1111 / Forge**
  folders without downloading them again (System check > SHARE THEM), and transcribe with
  **whisper.cpp** (faster on Macs; offered in System check).
- **Better words in pictures**: with FLUX.2 [klein] 4B installed (Apache-2.0, about 16 GB, offered
  in Setup > Models), Joe uses it by himself for pictures with words in them (a sign, a poster
  title), or for every picture when you pick it in Setup > Workflows.
- Or skip the tab and just ask on the Queue screen: "turn my meeting recording into notes",
  "read my story aloud", "proofread my cover letter", "shrink my product photos for the
  website", "translate my menu into Spanish", "remove the duplicates from my customer list", "put my receipts in a spreadsheet", "what do my lease papers say about pets?".

**Finished documents**
- Add Word, PDF or EPUB copies to any writing task, or press P on a file in F7. Uses
  Pandoc (free) and the PDF printer built into Microsoft Edge.

**Looks after himself**
- On first start he checks your PC: graphics card, memory, and the free programs he works
  with (Ollama for writing, ComfyUI for pictures, FFmpeg for video).
- If one is missing or not running, he tells you and **asks before installing or starting
  anything**. Installs use Windows' own installer (winget) and the official packages.
- Picks the best AI model your graphics card can handle, and suggests a download that fits
  if you don't have one.
- Shows your graphics card's temperature, load and memory live at the bottom of the window,
  and pauses to cool down if it runs hot.
- Keeps the PC awake while working; can sleep or shut it down when he's done.
- Picks up exactly where he left off after a crash, power cut or restart.
- Never overwrites your files: a second run saves `name_v2`.

**Easy to live with**
- Just say what you need in plain words. Joe makes a plan you can read ("40 items, 8
  pictures, about 14 minutes") and nothing runs until you press RUN IT.
- A step-by-step setup helper the first time, tabs for every screen, and a hint for every
  button when you hover over it. The F-keys work too (F1 shows them all).
- Close the window and he keeps working. Open it again to check on him.
- Modern light and dark looks, a futuristic one, or the retro green, amber and white screens
  with CRT glow — or describe your own theme in words and Joe designs it for you. An
  easy-to-read font (Atkinson Hyperlegible) works with every look.
- Stats for the number nerds: words written, items, files, hours of work, and how much
  you'd have paid a cloud AI for the same thing.
- A morning report sized to paste straight into a bigger AI for review.

## What Joe won't do

- Send your files, chats or recordings anywhere. They stay on your PC.
- Do the overnight work online. Writing, pictures and video are made on your PC.
- Send email, post online, or spend money.
- Touch anything outside his own folder (`Documents\Joe-ai`).
- Install or download anything without asking you first.
- Collect data about you. There's no tracking and no analytics. (The update check below asks
  GitHub for the newest version number and nothing else.)
- Listen unless the Talk screen is open with the mic on (or you're holding the talk key).

## When Joe uses the internet

Joe is **not** an offline-only app. The work happens on your PC, but these things need the
internet. None of them send your files, chats or recordings.

| What | Goes to | When | Your choice |
|---|---|---|---|
| Installing programs (Ollama, ComfyUI, FFmpeg, Pandoc) | Windows' winget, or the program's own download page | Setup, or when a task needs one | Asks you first, every time |
| Downloading AI models (writing, pictures, video, Turbo, vision, the small search model for Ask my files, and the picture/sound tool models) | Ollama's model library, Hugging Face | Setup, the Tools form, or when you pick a better model | Asks you first, every time |
| Hearing model for other languages (Transcribe, about 75-480 MB, once) | Hugging Face (only the model, never your recording) | The first time you transcribe a recording that isn't in English | You pick the language on the Tools form; English needs no download |
| Voice add-ons (Joe's voice, "sound like me") | GitHub, Python's package site (PyPI), PyTorch | When you set up voice | Asks you first, every time |
| Update check | GitHub (asks for the newest version number) | Each time Joe opens | On by default; Setup > General > Updates |
| Installing an update | GitHub (downloads the new installer and its checksum) | Only when you say yes to an update | Asks you first, every time |
| Phone ping when done | ntfy.sh (one line like "Joe is done: 3 of 3 tasks") | When a run ends | Off until you type a topic name |
| Talk looks things up | Ollama web search (with your key) or Wikipedia: only the search words | When you ask about something current | Off until you turn it on |

Ollama and ComfyUI are separate programs with their own update checks and settings; Joe
doesn't control those. Once everything is installed, you can unplug the internet and the
overnight work still runs.

## What you need

| | Minimum | Better |
|---|---|---|
| System | Windows 10 or 11 (Mac and Linux: early, see below) | Windows 11 |
| Graphics card | NVIDIA with 6 GB memory | NVIDIA with 12 GB or more |
| Memory (RAM) | 16 GB | 32 GB |
| Free disk space | 15 GB | 50 GB+ if you want pictures and video |
| Python | 3.11 or newer (python.org) — until the one-click installer is ready | |

Joe will offer to install Ollama, ComfyUI and FFmpeg for you. They're free programs made by
other people, each under their own license. AI models are big downloads (2–20 GB each).

**Other graphics, honestly:**
- **AMD Radeon:** writing works on many recent cards (RX 6000 and newer) through Ollama. Pictures
  and video on Windows are shaky (ComfyUI Desktop doesn't support AMD); on Linux they need
  ComfyUI's AMD (ROCm) setup and are slower than NVIDIA.
- **Apple Silicon Macs:** writing works well (the memory is shared, so bigger models fit).
  Pictures work but several times slower than NVIDIA; video is very slow.
- **Intel graphics, or no card:** writing runs on the processor, so pick a small model; pictures
  and video aren't practical.
- "Sound like me" needs an NVIDIA card. The cool-down pause only works on cards that report their
  temperature (NVIDIA, and AMD on Linux).

System check (Setup) says what your own graphics mean for Joe.

## How a night with Joe goes

1. **Before bed:** tell Joe what you need in your own words, check his plan, press **RUN IT**.
   (Or build it step by step in the Builder, or paste a job list you or a bigger AI wrote.)
2. **Overnight:** Joe writes first, then makes the pictures, so your graphics card only has
   to switch jobs once.
3. **In the morning:** press **R** for the report. Your files are in `Documents\Joe-ai\Output`.
   Review them, fix what he flagged, and finish the good stuff.

Under the hood, a job list looks like this (you never have to write one):

```
PROJECT: My Shop   RULES: Warm, plain voice. No exclamation marks.
TASK: Product blurbs  CHUNKS: 6 x 8  MIN WORDS PER ITEM: 60
FORMAT: One paragraph about look, feel and use. End with a care tip.
TASK: Mood boards  TYPE: image  CHUNKS: 2 x 5
FORMAT: Soft morning light, linen, muted earth tones, no people.
```


That's 48 product blurbs and 10 pictures by morning. Every key is explained in the
[full guide](docs/GUIDE.md).

## Good to know

- **AI makes mistakes.** Joe flags what he's unsure of, but always read before you publish,
  sell, or rely on anything he writes.
- **Check model licenses** before using pictures or text commercially. Each AI model has its
  own license. [THIRD_PARTY.md](THIRD_PARTY.md) lists every program, model and font Joe ships
  or can fetch, with its license.
- **Need help?** Setup > System check > **MAKE A HELP FILE** saves one zip with Joe's version, System
  check and the end of the logs (keys hidden, never your files, chats or recordings) to send to
  whoever is helping you.
- **Joe is free; what you plug into him might not be.** Joe works with programs, AI models,
  ComfyUI workflows and custom nodes, add-ons and plugins made by other people and companies.
  Joe's makers don't make, own, control or vouch for any of them. Each has its own license,
  terms, privacy rules and sometimes a price, and can change or stop working at any time. If you
  choose to connect a paid model, service or plugin, that's your decision, and any cost or
  agreement is between you and whoever provides it.
- **What Joe is, and isn't.** Joe is a helper (an AI agent, if you like) that takes on everyday
  grunt work and sets up long, confusing tools so you can use them without knowing how they work.
  He's the flashy AI hero, not the one doing the heavy lifting: the pictures, videos, sounds and
  text are made by the programs he runs for you (Ollama, ComfyUI and the models you install).
  Joe isn't responsible for what you use him for and doesn't guarantee any of the work. Always
  check the finished result before you use, share or sell it: make sure it's acceptable, follows
  each model's license and follows the laws where you live. Don't pass AI-made pictures or video
  off as real, copy someone else's work, or pretend to be a real person. Joe and his makers aren't
  liable for what you do with him or what he makes.
- **Models from other sites are your download.** When Joe recommends a community model
  (Civitai or similar), he only opens its page: you read its terms and download it yourself,
  then Joe moves the file into ComfyUI. Joe's makers don't make, check or vouch for those models.
- **It's a hobby project** built by one person with help from AI, shared for free. It comes
  with no warranty.

## License

Joe is free software under the GNU General Public License, version 3 or later
(GPL-3.0-or-later). You can use it, study it, share it and change it. If you share a changed
version, share its source under the same license so it stays free for the next person.
Full text in [LICENSE](LICENSE).

Joe is free, and he stays free. No ads, no upgrades, no donations. He's here to help.

---

**Ready?** Install Python 3.11+ from python.org, download Joe, and double-click `Joe.pyw`.
The details are in the [full guide](docs/GUIDE.md).
