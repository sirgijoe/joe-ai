# Joe

```
01000001 01001001
```

**Meet 01000001 01001001. Humans can't say that, so we just call him Joe.**

Joe does the grunt work on your own computer while you sleep. You hand him a list of jobs
before bed — product descriptions, long lists, design notes, spreadsheets, pictures, short
video clips — and in the morning the drafts are waiting, along with a short report of what
needs a human (or a bigger AI) to look at.

He's free, open source, and runs on your PC. No account, no subscription, no tokens to buy.

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
- Open Talk (**F6**) and just say what you need: the mic stays open while that screen is up,
  and Joe answers when you pause. Prefer push-to-talk? Pick any key in Setup. Joe hears you, answers out loud, and can draft
  the night's mission into the Builder for you to check. He never starts a run on his own.
- He can read the morning report to you, or tell you his own backstory.
- Drop a file onto his window (text, Word, PDF, a web page or a picture) and ask about it,
  or just say "read it".
- **Make Joe sound like you** (optional, NVIDIA card): read a short passage once and Joe talks
  in your voice. The recording stays on your PC; it's never shared or packaged with Joe.
- Speech runs on the regular processor in its own small add-on, so it never fights the
  night's work for the graphics card. Recordings are never kept.

**Finished documents**
- Add Word, PDF or EPUB copies to any writing task, or press P on a file in F3. Uses
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
  with CRT glow — or describe your own theme in words and Joe designs it for you.
- Stats for the number nerds: words written, items, files, hours of work, and how much
  you'd have paid a cloud AI for the same thing.
- A morning report sized to paste straight into a bigger AI for review.

## What Joe won't do

- Send your files anywhere. Everything stays on your PC.
- Browse the web, send email, post online, or spend money.
- Touch anything outside his own folder (`Documents\Joe-ai`).
- Install or download anything without asking you first.
- Collect data about you. There's no tracking, no analytics, no phoning home.
- Listen unless the Talk screen is open with the mic on (or you're holding the talk key).

## What you need

| | Minimum | Better |
|---|---|---|
| System | Windows 10 or 11 | Windows 11 |
| Graphics card | NVIDIA with 6 GB memory | NVIDIA with 12 GB or more |
| Memory (RAM) | 16 GB | 32 GB |
| Free disk space | 15 GB | 50 GB+ if you want pictures and video |
| Python | 3.11 or newer (python.org) — until the one-click installer is ready | |

Joe will offer to install Ollama, ComfyUI and FFmpeg for you. They're free programs made by
other people, each under their own license. AI models are big downloads (2–20 GB each).

Without an NVIDIA card Joe still works, just much slower.

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
  own license.
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
