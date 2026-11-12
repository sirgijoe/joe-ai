# Joe

```
01000001 01001001
```

**Meet 01000001 01001001. Humans can't say that, so we just call him Joe.**

> **🧪 Beta.** Joe is free to use and works today. It's tested most on Windows. Download the
> installer for Windows, Mac or Linux from the [latest release](https://github.com/sirgijoe/joe-ai/releases/latest).
> Expect rough edges, and please [open an issue](https://github.com/sirgijoe/joe-ai/issues/new/choose) if something breaks.

Joe does the grunt work on your own computer while you sleep. You hand him a list of jobs
before bed — product descriptions, long lists, design notes, spreadsheets, pictures, short
video clips — and in the morning the drafts are waiting, along with a short report of what
needs a human (or a bigger AI) to look at.

He's free, open source, and runs on your PC. No account, no subscription, no tokens to buy.
Setting him up needs the internet (to download the programs and AI models he uses); after
that, the overnight work itself runs on your PC and doesn't send anything out. See
[When Joe uses the internet](#when-joe-uses-the-internet).

**Joe is free, open source and fully transparent, and will always remain that way.**

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
- 21 picture styles: photo, product, black and white, anime, manga, cartoon, comic, painting,
  watercolor, concept art, fantasy, sci-fi, cyberpunk, 3D, pixel art, surreal, abstract,
  illustration, characters and mascots, coloring pages, and an all-round general one. Name one or
  let Joe guess from your words;
  he picks the installed model that suits it best and adds the style's own words.
- "An image of a fox in the snow" gets you 4 versions of that one picture to pick from.
- Coloring pages always come out as clean black-and-white outlines (a colored example is kept).
- Uses the image models you already have, or helps you get one (System check shows free picks
  for each style, with their licenses). Bring your own ComfyUI workflow too
  (Setup > Images & video > IMPORT WORKFLOW).
- Short video clips (Wan 2.2), black-and-white films, and looping GIFs (`EXPORT: gif`). The
  Turbo add-on makes video several times faster; **Keep my PC usable** makes smaller videos so
  you can still use the computer while Joe works.
- A viewer to flip through the results and mark them keep / reject / star.
- Every picture is labelled **AI-GENERATED**. Joe is built to make mood boards, art and
  mockups, not fake photos of real products, places or people.

**Lines up the night for you**
- **Queue** as much as you like: plans run one after another, with one combined morning report.
- **Night shift** (Setup > General): SAVE FOR TONIGHT and Joe starts those plans at the time you
  set, even with his window closed (Windows can wake the PC for it). Uses your computer's own
  scheduler, and turning it off removes the entry again. Give it a **Stop by** time too and he
  finishes the job he's on, saves the rest for the next night and says so in the morning report.
- **Watch folders** (Setup > General): drop a file into `Inbox\Watch\<tool>` (like `clean-audio` or
  `summarize`) and Joe does it by himself while he's open, with that tool's usual options.
- **Starter packs**: one question ("what's your shop called?") and Joe plans a whole bundle: a shop
  starter, a month of social posts, a blog starter, a party kit or a coloring book. Make your own
  in `Missions\Packs`. Parts your PC can't do are left out.
- **Looks things up first** (`RESEARCH: yes`): a writing task can check facts online and list its
  sources. Only when you've turned online lookups on.
- **Matching lists** (`FROM:`): a price list or a set of pictures that uses the exact names from a
  list above it.
- **Park an idea**: type "park this: a recipe book for my mom" and Joe saves it, dated, in
  `Ideas.md` for later.

**Works with bigger AIs** (no keys, no accounts)
- **ASK A BIGGER AI** (Home): Joe writes one message you paste into any chatbot (ChatGPT, Claude,
  Gemini...). Paste its answer back and Joe tidies it, checks it and shows it as a plan. Folder
  paths and your user name are left out of the message, and nothing is sent unless you paste it.
- **Use Joe from another AI app**: Joe is an MCP connector, so Claude Desktop, ChatGPT desktop
  (and Codex), Gemini CLI, Cursor and LM Studio can see what Joe can do, queue plans, run his tools
  and read the results. One-click CONNECT in Setup > General (it keeps a copy of that app's
  settings first and only touches Joe's own entry).

**Talks, and listens** (optional, one-time setup)
- Open Talk (**F4**) and just say what you need: the mic stays open while that screen is up,
  and Joe answers when you pause. Prefer push-to-talk? Pick any key in Setup. Joe hears you, answers out loud, and can draft
  the night's mission into Step by step (F6) for you to check. He never starts a run on his own.
- **Joe has a face** beside the chat: he listens while the mic is open, thinks while he works out
  an answer, moves his mouth with his voice, smiles when a run is done, looks worried when
  something failed and gets sleepy during the night shift. Setup > Voice & Talk > "Joe's face in
  Talk": On, Still (no blinking or moving mouth; also used when your computer is set to reduce
  motion) or Off.
- He can read the morning report to you, or tell you his own backstory.
- Ask him something current and, with online lookups on, he searches and shows his sources.
  **STOP** (or Esc) cuts him off mid-answer.
- Drop a file onto his window (text, Word, PDF, a web page or a picture) and ask about it,
  or just say "read it".
- **Make Joe sound like you** (optional, NVIDIA card): read a short passage once and Joe talks
  in your voice. The recording stays on your PC; it's never shared or packaged with Joe.
- **A voice to remember** (optional, NVIDIA card): from a family recording of someone you miss (a phone
  video or voicemail), hear a letter or a story in their voice with the tool "Hear it in a loved one's
  voice". You tick three promises first (family's OK, family listening only, never to fool anyone); it
  stays on this PC, every recording says it was made by AI, and the voice program watermarks it.
- Speech runs on the regular processor in its own small add-on, so it never fights the
  night's work for the graphics card. Recordings are never kept.

**48 ready-made tools** (Tools tab, **F3**)
- **Transcribe a recording**: drop in audio or video and get a text transcript, a subtitles
  file (.srt) and short notes (summary, key points, decisions, to-dos). English plus 23 other
  languages (or let Joe find out); notes in the recording's language or in English. Uses the
  voice add-on and runs on the processor.
- **Read a document aloud**: text, Word, PDF or a web page in, an MP3 out (one track per
  chapter if you like), in Joe's voice from Setup. Runs on the processor; a stopped run
  carries on where it left off.
- **Find a book to read aloud**: by ISBN, title or a photo of the cover or barcode. Free public-domain
  books (Project Gutenberg) are downloaded and read aloud; for books still under copyright, scan your
  own copy's pages and Joe reads those. Needs online lookups on.
- **Proofread my writing**: fixes spelling, grammar and punctuation (and, if you ask, unclear
  wording) and lists every change with the before and after. Nothing is changed silently, and
  your original file is never touched.
- **Resize and convert photos**: shrink a batch for the web or email, turn them into JPG,
  WebP or PNG, rename them in order, and (only if you ask) add a faint watermark with your
  text or logo. Phone photos come out the right way up; hidden details like GPS location are
  left out of the copies. Uses FFmpeg.
- **Summarize**: an article, PDF, book or web page as a short summary, key points (with names,
  numbers, dates and to-dos copied as written) or chapter by chapter. Long books are read in parts.
- **Rewrite or change the tone**: friendlier, more formal, shorter, simpler, notes into an email, or a
  resume tailored to a job post. A new copy plus a "what changed" list; Joe never adds facts (no
  invented jobs or skills on a resume).
- **Brainstorm**: ideas, names, gift ideas, marketing angles, an outline or ways to solve a problem;
  no file needed, just say what you need ideas for.
- **Study helper**: your class notes or a chapter explained at your level (kid to expert), flashcards
  as a CSV for Anki or Quizlet, a practice quiz with answers, and a "teach me" mode that asks you
  questions first so you learn it instead of just getting answers.
- **Explain or review my code**: what it does, likely bugs and risks with fixes, tests to add. Real
  line numbers; Joe reads the code and never runs it.
- **Get found by AI search**: from the facts you give (never invented ones), a FAQ, a short
  description, schema code for your website and an llms.txt file, so AI assistants describe your
  business correctly. A README says where each goes and lists any missing facts.
- **Budget meal planner**: "$80 this week for a family of 8" -> a week of cheap meals and a shopping
  list. Joe adds up the total himself and says plainly if it goes over. Real prices come from your own
  receipts (Read scans and receipts); otherwise prices are estimates marked [CHECK].
- **Clean up a recording**: less background noise and electrical hum, and an even volume, for a
  recording or a video's sound (FFmpeg, no AI, seconds).
- **Cut out ums and long pauses**: Joe listens word by word, cuts the "um", "uh" and long silences,
  and lists every cut.
- **Edit a video by its words**: Joe writes down what was said; delete the words you don't want, give
  the file back and he cuts them out of the video or recording (like Descript, on your own PC).
- **Dub or voice-over a video**: Joe listens, translates each line and makes subtitles in the new
  language; for English, Spanish, French, Italian, Portuguese and Hindi his voice also says each line at
  its time over the original sound turned down. A machine translation: have it checked before publishing.
- **Add B-roll to a talking video**: give Joe the video plus your own clips and photos; he cuts to them
  where they match what's being said (named for what they show), keeping the speaker's sound.
- **Privacy blur**: faces, license plates, house numbers and screens blurred before you post (the
  vision model finds them, FFmpeg blurs them, GPS details left out). Always look before posting.
- **Social graphics and flyers**: your exact words on a photo or a plain color, at Instagram, story,
  Facebook, X, YouTube thumbnail, Pinterest or printable flyer size. Real font, so no AI spelling mistakes.
- **Translate**: finished writing into one or more of 24 languages, on your own computer.
  Formatting, names, prices and links stay as they are; anything Joe isn't sure about is
  marked [CHECK], and each copy says plainly it's a machine translation to be checked by
  someone who speaks the language.
- **Ask my spreadsheet**: "which month sold the most?", "total spent on supplies in 2026". The
  writing model only turns the question into a plan; Joe's own code does the math (so the numbers are
  right) and shows how, with a bar chart when there are several rows.
- **Sort and rename my files**: documents copied into folders (yours or Joe's) with clear names like
  "2026-03-02 Electric bill.pdf". The originals stay where they were.
- **Dates and to-dos to my calendar**: the dates, times and to-dos from notes, emails or a transcript
  as a calendar file (.ics) for Google Calendar, Outlook or Apple Calendar. Joe never touches your
  calendar account; guessed dates are marked [CHECK].
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
- **Everyday paperwork** (new in 2.2; nothing you give them is changed, and numbers, dates and names
  the AI gives are checked against your own file, [CHECK] where they aren't there):
  - **PDF toolkit**: join, split, pick or reorder pages, turn pages, make a PDF smaller, and fill in
    PDF forms (Joe lists the fields, you type the answers). No AI: uses qpdf, a small free program
    System check installs.
  - **Explain this letter**: a bill, lease, insurance or benefits letter (or a photo of it) in plain
    words: what it means, what to do, every deadline with the days left, money and reference numbers
    checked against the letter, scam warnings, and a polite reply to fill in. Not legal advice.
  - **Hide personal details**: names, addresses, phone, card, account and ID numbers replaced by
    labels like [NAME 1] (or black blocks) in a copy to share. Word files stay Word files; Joe only
    hides words that are really there. Read the copy before you send it.
  - **Meeting minutes**: a recording or transcript into minutes: summary, decisions, to-dos (who, by
    when), open questions. Names only when the recording makes them clear.
  - **Bank statement to budget**: your bank's CSV into where the money went, by category and month,
    regular payments with their yearly cost, and price rises. Joe's own math; the AI only ever sees
    shop names.
  - **Resume tailor**: your resume plus a job posting into a matched resume, a cover letter and a
    list of what the job asks for that your resume does or doesn't show. Nothing invented: anything
    not in your resume is marked [CHECK].
  - **Mail merge**: one letter with {Name}-style spots plus a spreadsheet into a personal letter per
    row (Word formatting kept), and one file with all of them.
  - **Picture descriptions (alt text)**: a short description of every picture for screen readers
    and shop listings, never naming people.
  - **Duplicate photo finder**: copies and near-copies grouped, with the best one to keep and why.
    Nothing is moved or deleted.
- **Picture and sound tools** (run in ComfyUI on the graphics card; each needs its model once,
  offered with its size and license):
  - **Remove background and upscale**: see-through PNG or white JPG cutouts, optionally 2x/4x
    bigger and sharper (BiRefNet, MIT; Real-ESRGAN, BSD-3).
  - **Edit a picture by asking**: "swap the background for a marble counter", "remove the cup"
    (Qwen-Image-Edit 2511, Apache-2.0, about 31 GB; best with 12 GB graphics + 32 GB memory).
  - **Restore old photos**: fading and color casts undone true to the photo (no AI redraw); optional AI repair for scratches and tears.
  - The same picture editor also does: **Fix one spot** (brush over it; only that spot changes),
    **Put pictures together** (two or three into one), **Change the lighting** (golden hour,
    studio, night...), **Redraw in a new style** (watercolor, anime, a sketch...), **Change a
    picture a little or a lot**, **Make a picture wider or taller** (the original stays in the
    middle), **Same character, new scenes**, and a **Character turnaround** (front, side and back,
    plus a sheet).
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
- **Templates for finished copies**: book, manuscript, children's picture book, e-book, report, large
  print, poetry, screenplay, letter, resume, cookbook, recipe card, coloring book, school paper (MLA),
  everyday, spreadsheet and price list. They set page size, margins (with binding gutter), fonts,
  spacing, page numbers, headers, drop caps and more for Word, PDF, EPUB and Excel copies; every one
  is shown and editable in Setup > Writing. Need a look that isn't there? **Add your own**: name it,
  start from the closest one, change anything, and use it with `TEMPLATE:` and its name.
- **Portable Joe**: copy Joe to a USB drive (Setup > General > MAKE A PORTABLE JOE) and start him on
  any computer with "Start Joe". His settings, your work and anything he sets up (voice, Ollama,
  ComfyUI, models) stay on the drive. Each computer still needs its own graphics driver, and
  Windows may still remember that a program ran: portable means carried with you, not invisible.
- **Takes care of the small stuff**: CHECK MY MODEL FILES spots a model whose download stopped part way;
  Joe checks there's room on the drive before big downloads and big plans; BACK UP MY SETTINGS saves
  everything you set up by hand in one zip to restore on any computer; and every pop-up window works
  with the keyboard and screen readers.
- **"What can Joe do?"**: ask him (in Talk or the Home box), or press WHAT CAN JOE DO? on Home or
  Help (F1). He lists everything in plain words, and "how does restore photo work?" gets the long
  version: how he does it behind the scenes, what to give him, every option, time, needs and tips.
  Every tool card has a "learn more" link. It's all built from Joe's own code, so it stays true.
- **Use what you already have**: write with **LM Studio, llama.cpp, LocalAI or any other OpenAI-compatible program** (Jan, KoboldCpp, vLLM...) instead of Ollama
  (Setup > Writing > Writing program), let ComfyUI use the models in your **AUTOMATIC1111 / Forge**
  folders without downloading them again (System check > SHARE THEM), and transcribe with
  **whisper.cpp** (faster on Macs; offered in System check).
- **Better words in pictures**: with FLUX.2 [klein] 4B installed (Apache-2.0, about 16 GB, offered
  in Setup > Models), Joe uses it by himself for pictures with words in them (a sign, a poster
  title), or for every picture when you pick it in Setup > Workflows.
- Or skip the tab and just ask on the Home screen (**F2**): "turn my meeting recording into notes",
  "read my story aloud", "proofread my cover letter", "shrink my product photos for the
  website", "translate my menu into Spanish", "remove the duplicates from my customer list", "put my receipts in a spreadsheet", "what do my lease papers say about pets?".

**Reminders and lists** (by voice or in the box, no AI needed)
- "Remind me at 3pm to call the vet", "in 20 minutes", "tomorrow at 9", "on Friday at 10": the
  reminder comes to your phone through the free phone ping (ntfy), even if the PC is off by then.
- "Add milk and eggs to my shopping list", "what's on my to-do list?", "take milk off my list",
  "send my shopping list to my phone". Lists are plain files in Joe's `Lists` folder.
- "Directions to the feed store", "where can I buy a cheap air fryer?": opens your map or shopping
  site (picked in Setup > General) in the browser. Joe doesn't pick stores or track you.
- **Joe in your language** (Setup > Display & sound): Spanish built in for the main screens; MAKE IT has
  Joe translate the rest of his window into any of 23 languages overnight. Edit any line yourself.
- **Add-ons from other people** (Setup > Add-ons): new tools, starter packs, picture workflows and
  themes in a .zip. Each stays off until you've read what it runs; changed files switch it off again.
  Make your own: [docs/ADDONS.md](docs/ADDONS.md).
- **Joe Phone** (Setup > Phone): use Joe from your phone on your home Wi-Fi. See the run and stop it,
  ask Joe or plan work (RUN IT on the phone), lists, reminders and everything he made. Pair once with a
  QR code; home network only, and it can't change settings or open files outside Joe's Output folder.
- "What time is it?", "what's the date?", "what's 15% of 80?", "12 times 7": answered right away,
  no AI and no internet. "Stop talking" cuts Joe's voice off; "say that again" repeats his last answer.

**Finished documents**
- Add Word, PDF or EPUB copies to any writing task, or press P on a file in F7. Uses
  Pandoc (free) and the PDF printer built into Microsoft Edge.

**Looks after himself**
- On first start he checks your PC: graphics card, memory, and the free programs he works
  with (Ollama for writing, or LM Studio, llama.cpp, LocalAI or another OpenAI-compatible program
  if you'd rather; ComfyUI for pictures; FFmpeg for video).
- If one is missing or not running, he tells you and **asks before installing or starting
  anything**. Installs use Windows' own installer (winget) and the official packages.
- Offers three writing models that fit your graphics card: Joe's pick (Gemma or Llama), an
  alternative (Qwen) and one with little to no filtering (Mistral, Dolphin or Hermes), each with a
  plain line on what it's good at and its downside. Or type any model's name in Setup > Writing.
- When a model thinks so long it runs out of room, Joe writes the rest of the task without
  thinking first, and a list that comes up short gets its missing items written at the end.
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
- **For low vision and screen readers:** two high contrast themes, a Large text setting that makes
  every button and box bigger, screen-reader announcements while Joe works (progress, finished and
  failed jobs), and voice commands in Talk to move through a list or the morning report ("read the
  third one", "next", "skip to the CHECK items"). [ACCESSIBILITY.md](ACCESSIBILITY.md) says what
  works and what doesn't yet.
- Stats for the number nerds (**F9**): words written, items, pictures, video, hours of work, and
  how much you'd have paid a cloud AI for the same thing, for today, this week, month, year or all
  time. The same screen shows how much room Joe takes up, with clean-up buttons (everything goes
  to the Recycle Bin, after asking).
- Setup has a page for everything, a find box, **Setup > Models** (downloads by kind, or DOWNLOAD
  ALL for an overnight download) and **Setup > Workflows** (see and edit the exact words Joe adds
  for each picture style, video and tool, or pick the model). Every page has RESET THIS PAGE,
  and there's one RESET ALL SETTINGS; both ask first.
- Screen savers for Joe's window (coffee mug, binary rain, starfield...; they can show how the run
  is going), or describe your own and MAKE SCREEN SAVER designs it.
- A morning report sized to paste straight into a bigger AI for review.

## What Joe won't do

- Send your files, chats or recordings anywhere. They stay on your PC.
- Do the overnight work online. Writing, pictures and video are made on your PC.
- Send email, post online, or spend money.
- Touch your files outside his own folder (`Documents\Joe-ai`, or `Joe-ai` on the drive for Portable Joe). Programs and models he installs with your OK go where those programs normally live. A few buttons reach further, only when you press them: CONNECT adds Joe to that AI app's settings (a copy of the old file is kept), the night shift adds one entry to your computer's scheduler, and a model file you downloaded from a model page is moved from Downloads into ComfyUI.
- Install or download anything without asking you first.
- Collect data about you. There's no tracking and no analytics. (The update checks below only
  ask for version numbers and model lists, nothing about you.)
- Listen unless the Talk screen is open with the mic on (or you're holding the talk key).

## When Joe uses the internet

Joe is **not** an offline-only app. The work happens on your PC, but these things need the
internet. None of them send your files, chats or recordings.

| What | Goes to | When | Your choice |
|---|---|---|---|
| Installing programs (Ollama, ComfyUI, FFmpeg, Pandoc, qpdf) | Windows' winget, or the program's own download page | Setup, or when a task needs one | Asks you first, every time |
| Downloading AI models (writing, pictures, video, Turbo, vision, the small search model for Ask my files, and the picture/sound tool models) | Ollama's model library, Hugging Face | Setup, the Tools form, or when you pick a better model | Asks you first, every time |
| Hearing model for other languages (Transcribe, about 75-480 MB, once) | Hugging Face (only the model, never your recording) | The first time you transcribe a recording that isn't in English | You pick the language on the Tools form; English needs no download |
| Voice add-ons (Joe's voice, "sound like me") | GitHub, Python's package site (PyPI), PyTorch | When you set up voice | Asks you first, every time |
| Update check | GitHub (asks for the newest version number) | Each time Joe opens | On by default; Setup > General > Updates |
| Helper and model update check | GitHub (newest Ollama and ComfyUI versions, Joe's list of recommended models), Ollama's model library (are your models up to date?) | At most once a week, when System check runs | Nothing installs until you say yes; off with the update check (Setup > General > Updates) |
| Installing an update | GitHub (downloads the new installer and its checksum) | Only when you say yes to an update | Asks you first, every time |
| Ollama on a portable drive (only if you use Portable Joe) | GitHub (Ollama's official release) | When you choose "Put Ollama on the drive" in System check | Asks you first, every time |
| Phone ping when done | ntfy.sh (one line like "Joe is done: 3 of 3 tasks") | When a run ends | Off until you type a topic name |
| Find a book to read aloud | Open Library and Project Gutenberg (only the ISBN or title; the free book text comes back) | When you use that tool | Only with online lookups on |
| Reminders and lists sent to your phone | ntfy.sh (the reminder text, with the time to deliver it; or the list you asked to send) | When you say "remind me..." or "send my list to my phone" | Off until you type a topic name |
| Looking things up (Talk, and writing tasks with `RESEARCH: yes`) | Ollama web search (with your key) or Wikipedia: only the search words | When you ask about something current, or a task asks to research | Off until you turn it on |
| Model pages | Hugging Face or Civitai, in your browser (for Hugging Face, the browser also starts the download) | When you press GET IT on a recommended picture model | You read its terms; the download is yours |

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
| Python | Only to run Joe from the source code: 3.11.4 or newer (python.org). The installers bring their own. | |

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

## Why your computer may warn you about Joe

**Mac:** the first time you open Joe, macOS says it can't check Joe for malicious software.
Apple charges developers $99 every year before a Mac will open their apps without that warning.
Joe is free, makes no money and never will, so we won't pay a yearly toll for the right to give
something away. Instead, all of Joe is open source: every line is right here. If you don't feel
safe installing it, check the code yourself, or have an AI check it for you. Complete
transparency for everything included, free and at your disposal. Joe is free, open source and fully transparent, and will always remain that way.
To open Joe anyway (once): System Settings > Privacy & Security, scroll down, **Open Anyway** next
to Joe, then **Open**. The disk image's "Read me first.txt" says the same.

**Windows:** until Joe's free code-signing certificate is in place (applied for through
SignPath Foundation, which signs open-source projects at no cost), Windows may show "Windows
protected your PC". Click **More info**, then **Run anyway**. Windows first asks Microsoft about
the file online; when that check is slow, the installer can seem to hang for a bit and then say
SmartScreen "couldn't be reached". That's Windows, not Joe: choose **Run anyway**.

**Updates:** each release lists a SHA-256 checksum for every file, and releases are signed with
Joe's own key, so Joe refuses an update that was changed or didn't come from this project.
If UPDATE doesn't work on your computer, download the installer from the
[release page](https://github.com/sirgijoe/joe-ai/releases/latest) and run it; your files and settings are kept.

**Older model files:** Joe only downloads `.safetensors` models (data only). Files in the older
`.ckpt`, `.pt`, `.pth` or `.bin` formats can run hidden code when they're loaded, so Joe never picks
one himself; if you bring one you trust, say YES to it once in Setup > System check > Your models.
[SECURITY_REVIEW.md](SECURITY_REVIEW.md) lists what an outside reviewer should check. How releases are signed, and by whom: [Code signing policy](CODE_SIGNING.md).

## How a night with Joe goes

1. **Before bed:** tell Joe what you need in your own words, check his plan, press **RUN IT**
   (or SAVE FOR TONIGHT and let the night shift start it). You can also build it step by step
   (F6), pick a starter pack, or ask a bigger AI to write the plan.
2. **Overnight:** Joe writes first, then makes the pictures, so your graphics card only has
   to switch jobs once.
3. **In the morning:** open the Report (**F8**). Your files are in `Documents\Joe-ai\Output`.
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

- **Memory, only if you want it.** Turn it on in Setup > Memory and say "remember that I like short
  captions": Joe keeps a note you can see, edit and delete, on this computer only.
- **Agents.** Give Joe a whole job (Tools > OPEN AGENTS): a Researcher, Paperwork clerk, Daily
  briefing, Maker or Personal assistant plans it, looks things up, checks its own facts and works until
  each point is done. Risky abilities stay off until you turn them on, each explained first; once an
  agent has read your files, its searches only use words from the job you typed.
- **Recurring missions.** "Every Sunday night, make next week's meal plan", then REPEAT under the plan:
  it runs with the night shift on those nights (Setup > General lists them to pause or delete).
- **Your keys stay locked away.** Keys and passwords you give Joe (web-search key, connector password)
  are kept in the computer's own protected store (Windows DPAPI, the Mac Keychain, the Linux keyring),
  not in a plain settings file. Setup > Privacy shows where.
- **Where your work goes.** Each mission gets one folder in Output with the date in front
  ("2026-11-10 Showcase video"); writing gets its own folder with its Word and PDF copies, and a task
  run again goes beside the first as v2. Prefer the old way? Setup > General > HOW JOE FILES HIS WORK
  > Flat. TIDY MY OUTPUT sorts older work the same way, only moving things, with an UNDO. Group
  missions into **projects** (Files F7 > PROJECTS) with notes and a "what's left" list.

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
  (Civitai, Hugging Face or similar), he only opens its page in your browser (on Hugging Face the
  browser starts the download too): you read its terms, then Joe moves the file into ComfyUI. Joe's makers don't make, check or vouch for those models.
- **It's a hobby project** built by one person with help from AI, shared for free. It comes
  with no warranty.

## License

Joe is free software under the GNU General Public License, version 3 or later
(GPL-3.0-or-later). You can use it, study it, share it and change it. If you share a changed
version, share its source under the same license so it stays free for the next person.
Full text in [LICENSE](LICENSE).

Joe is free, and he stays free. No ads, no upgrades, no donations. He's here to help.

---

**Ready?** Download the installer for your computer from the [latest release](https://github.com/sirgijoe/joe-ai/releases/latest)
and open it. (Running from the source code instead? Install Python 3.11.4+ and double-click `Joe.pyw`.)
The details are in the [full guide](docs/GUIDE.md).
