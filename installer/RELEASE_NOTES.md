## What's new in 2.3 (in development)

- **Tidier Output: one folder per mission.** New work goes into a folder with the date in front
  ("2026-11-10 Showcase video") with every task of that mission inside. A piece of writing gets its
  own folder with its Word, PDF and other copies. Running a task again puts the new one beside the
  old one as "v2", "v3" (never over it), even on another day. Setup > General > HOW JOE FILES HIS
  WORK: by date (new), by project, or flat like before. Nothing you already have moves.
- **TIDY MY OUTPUT** (same place): sorts what's already in Output the same way, once. It only moves
  things (nothing is deleted or written over), shows you the list first, and UNDO puts it all back.
  Morning reports, resume, the Files tab, Joe Phone and the connector follow the moved files.
- **Projects** (Files F7 > PROJECTS, or J): group missions into a project, with an About text Joe
  reads when he writes for it, your own notes, a "what's left" list, and every file of its missions
  in one place. A plan with a PROJECT: line joins its project by itself.
- **Safer downloads of programs Joe runs:** uv (for the voice add-ons) and whisper.cpp now come from
  one known release each and are checked byte for byte (SHA-256) before Joe unpacks them; a download
  that doesn't match is thrown away. This also fixes whisper.cpp on Windows: its newest releases no
  longer carry the Windows download Joe asked for.
- **FFmpeg only reads files on your computer:** every picture, video and sound tool now tells FFmpeg
  not to follow web addresses or other places named inside someone else's media file.
- **For low vision and screen readers** (Setup > Display & sound): two high contrast themes (dark and
  light), a Large text setting that grows every button and box, screen-reader announcements while Joe
  works (progress, finished and failed jobs; failures as an alert), and voice commands in Talk to move
  through a list or the morning report: "read the third one", "next", "go back", "skip to the CHECK
  items", "how many are there?". See ACCESSIBILITY.md for what works and what doesn't yet.
- **Quicker Talk:** when the Talk model is blank (so the big writing model answers, 10-20 seconds),
  System check offers a small model you already have, or a small one to download.

## What's new in 2.2 (in development)

- **Joe has a face in Talk (F4):** the Joe character stands beside the chat. He listens while the
  mic is open, thinks while he works out an answer, his mouth follows his voice as he talks, he
  smiles when a run is done, looks worried when something failed and gets sleepy during the night
  shift and the screen saver. Setup > Voice & Talk > "Joe's face in Talk": On, Still (no blinking
  or moving mouth; also used when your computer is set to reduce motion) or Off.
- **Nine everyday paperwork tools** on the Tools tab (or just ask on Home). Your files are only read,
  never changed, and everything stays on your computer:
  - **PDF toolkit:** join, split, pick or reorder pages, turn pages, make a PDF smaller, and fill in
    PDF forms. Uses qpdf, a small free program that System check installs for you.
  - **Explain this letter:** a bill, lease or benefits letter in plain words, with every deadline and
    the days left, scam warnings and a polite reply to fill in.
  - **Hide personal details:** names, addresses and account numbers replaced in a copy you can share.
  - **Meeting minutes:** a recording or transcript into decisions, to-dos (who, by when) and a summary.
  - **Bank statement to budget:** where your money went, your regular payments and their price rises.
  - **Resume tailor:** a resume matched to a job posting, plus a cover letter. Nothing invented.
  - **Mail merge:** one letter and a spreadsheet into a personal letter for everyone on the list.
  - **Picture descriptions (alt text):** short descriptions for screen readers and shop listings.
  - **Duplicate photo finder:** copies grouped with the best one to keep. Nothing is deleted.
- **Safer add-on tools:** words filled into an add-on's program can't start with "/" or "@" either
  (some programs read those as a switch or as "read this file").

## What's new in 2.1.4

- **UPDATE works on PCs with an out-of-date certificate list:** when Joe's own Python can't make
  a secure connection to GitHub, he now checks and downloads with the computer's own curl
  instead (still a secure connection, and the checksum and signature are checked as always).
- **If UPDATE doesn't work on an older Joe** (it says it couldn't make a secure connection, or
  nothing happens after YES): download the installer from this page and open it. Your files and
  settings are kept, and UPDATE works from then on.

## What's new in 2.1.3

A safety update from an outside review of Joe's code. Please update.

- **Finished copies stay inside Joe's folder:** a Word, PDF, e-book or web-page copy can no longer
  pull in a file from somewhere else on your PC, and can't carry script. Pictures Joe made still
  land on their pages.
- **Joe's window keeps its key to itself:** other programs and other accounts on the PC can no
  longer pick it up from Joe's page, and other web pages can't put Joe's window inside theirs.
- **Private stays private:** a plan (from another AI app, the phone or a pasted answer) can't use
  Joe's own private folders, like your chats, as its INPUT.
- **Joe Phone:** RUN IT only runs the plan Joe showed you, and REMOVE always sticks.
- **Restoring a backup** never points Joe's AI programs at another computer and never turns Joe
  Phone on; Joe's log says what he left as it was.
- **Fixes:** a ComfyUI start line with a path in its options works; a tiny spreadsheet that
  unpacks to gigabytes is refused; a tool's results always go in Output; one failed background
  chore no longer stops the others.

## What's new in 2.1.2

- **Stop keeps your waiting work:** missions still in line are kept ON HOLD, with RUN THEM and
  CLEAR buttons, instead of being thrown away.
- **Better pictures:** pixel art comes out as real crisp pixels; groups of people, riders, neon
  cities and a story's pictures use FLUX.2 klein when it's installed (different faces, characters
  that stay the same from page to page, signs with real letters).
- **Picture books with pictures:** ask for "a picture book about..." and Joe writes it, makes one
  picture per page and puts each on its page in the PDF.
- **Fine-tuning in Setup > Workflows:** prompt strength, style add-on strength, detail pass,
  sampler and versions per picture style; prompt strength and motion for video.
- **Joe recommends better models** that suit your graphics card, in the log and at the top of
  System check (including his pick for writing), and never downloads without your OK.
- **In Files:** MORE LIKE THIS (same layout, change a few words) and WHY DOES THIS LOOK WRONG?
- **Tools:** Make bigger all around, remove background "main subject only", quick character
  turnaround, gentler AI photo repair with a darkroom finish, social graphics without a photo,
  edits kept at your photo's size, proofreading that leaves names and web addresses alone, and a
  meal plan that stays under budget.
- **Fixes:** writing parts keep their own titles and lengths; time estimates match real cards.

## What's new in 2.1.1

- **Faster, complete lists on High quality:** when the model spends all its room thinking and
  writes nothing, Joe writes the rest of that task without thinking first (100 dad jokes: 19
  minutes and 70 jokes before, under 2 minutes and all 100 now).
- **Lists come out the full size you asked for:** if repeats were dropped or a part ran out of
  tries, Joe writes the missing items at the end.
- **The bottom bar shows the right model** after a run, instead of the one the last run used.

## What's new in 2.1

- **20 new tools (48 in all):** Summarize, Rewrite or change the tone, Brainstorm, Study helper,
  Explain or review my code, Ask my spreadsheet, Sort and rename my files, Dates and to-dos to my
  calendar, Budget meal planner, Get found by AI search, Clean up a recording, Cut out ums and
  pauses, Privacy blur, Social graphics and flyers, Dub or voice-over a video, Add B-roll to a
  talking video, Find a book to read aloud, Hear it in a loved one's voice and more.
- **Night shift "Stop by" time:** Joe finishes the job he's on, saves the rest for the next night
  and tells you in the morning report. Type the time any everyday way (7am, 7:30 pm, 0700).
- **Reminders and lists to your phone,** by voice or the Home box, even with the PC off.
- **Watch folders:** drop a file in and the tool you picked runs by itself.
- **Three writing models for your graphics card:** Joe's pick (Gemma or Llama), an alternative
  (Qwen) and one with little to no filtering. Or type any model's name in Setup > Writing.
- **More writing programs:** LM Studio, llama.cpp, LocalAI or any OpenAI-compatible program
  (Jan, KoboldCpp, vLLM), each explained in Setup > Writing.
- **Connects to more apps** (Claude Desktop, Cursor, LM Studio, VS Code, Gemini) the apps' own
  way, and System check spots a connection that needs fixing.
- **Fixes:** plans keep what you asked for even with small models, phone pings work on PCs
  with old certificates, social graphics keep every line of words.

## Meet Joe

Joe does the grunt work on your own computer while you sleep. Tell him what you need in plain
words, check his plan, press RUN IT, and in the morning the drafts are waiting with a short report.

- **Writing:** long lists, whole documents section by section, spreadsheets, code drafts, and
  Word, PDF or EPUB copies. He checks his own work and marks anything unsure with [CHECK].
- **Pictures and short videos** (with ComfyUI): 21 styles, his own image prompts, every picture
  labelled AI-GENERATED.
- **48 ready-made tools:** transcribe, read aloud, proofread, translate, photo tools, OCR,
  photo restore and more.
- **Talk to him** (optional): he listens, answers out loud and drafts the night's plan.
- **Works with bigger AIs:** ASK A BIGGER AI for any chatbot, or connect him to Claude Desktop,
  ChatGPT desktop and other apps as an MCP connector. No keys, no accounts.
- **Looks after himself:** finds Ollama, ComfyUI and your models, asks before installing
  anything, offers three writing models that fit your graphics card (recommended, an
  alternative, and one with little to no filtering), and picks up where he left off.

**Joe is free, open source (GPL-3.0) and fully transparent, and will always remain that way.**
No ads, no upgrades, no donations. Every line of code is in this repository: check it yourself,
or have an AI check it for you.

Joe is in beta: please [open an issue](https://github.com/sirgijoe/joe-ai/issues/new/choose)
if something breaks. Setup and model downloads need the internet; see the README for exactly
when Joe goes online.

[Code signing policy](https://github.com/sirgijoe/joe-ai/blob/main/CODE_SIGNING.md)

## Installing
