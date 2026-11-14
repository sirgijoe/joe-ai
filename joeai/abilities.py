"""WHAT CAN JOE DO? Joe explains everything he does, in plain words, at two levels.

- overview(): every ability, grouped, one line each ("what all can you do?").
- explain(id): the long version of one ability: what it does, how Joe does it behind the
  scenes, what to give it, the options and when to pick each, time, what it needs, limits, tips.
- find(text) / answer(text): turn "how does restore photo work?" into the right explanation.

One source of truth: the Tools part is built from tools.TOOLS (name, blurb, help, options,
accepts, needs, examples) plus STEPS below (how Joe does it, step by step). A new tool shows up
here by itself; tests/test_abilities.py fails until it has its STEPS, so nothing goes stale.
The rest of Joe (writing, pictures, night shift, connector...) is in OTHER.
No AI is used for any of this: the answers are instant and always true to the code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MORE = "Want more on any of these? Just ask, like \"how does restore photo work?\" or \"tell me about the night shift\"."


@dataclass(frozen=True)
class Ability:
    id: str
    group: str
    name: str
    line: str                                   # one line for the overview
    text: str = ""                              # the long explanation (plain words, short paragraphs)
    aliases: tuple[str, ...] = field(default_factory=tuple)   # other ways people name it


# --------------------------------------------------------------------------- everything that isn't a Tool
OTHER: tuple[Ability, ...] = (
    Ability("writing", "Writing", "Writing (lists, documents, spreadsheets)",
            "Lists of anything, articles, guides, books, FAQs, product descriptions and spreadsheets, written overnight on your PC.",
            "What it does: Joe writes as much as you need with a writing model on your own computer (Ollama), so it costs nothing and nothing leaves your PC.\n"
            "How Joe does it: he turns your request into a plan with one task per thing to make. Big counts are split into small batches (5 x 6 instead of 1 x 30) so the model stays sharp. Each part is checked: too short, repeated or broken parts are written again (up to the Retries number in Setup > General). Near-duplicates are dropped and logged. Long documents are written part by part with the outline in view, and a part that comes out far shorter than the others is redone.\n"
            "What to give it: just say what you want in the box on Home, in your own words (\"40 product descriptions for handmade mugs, friendly and short\"). Facts it must use go in a file in Inbox, or in a project profile (Projects folder) for your brand voice and rules.\n"
            "Options: Quality in Setup > Writing (High thinks each part through: better, 2-3 times slower). FROM: makes a spreadsheet or pictures use the names from a list above it. RESEARCH: yes looks facts up online first (only when you allow lookups). EXPORT: makes Word, PDF, EPUB or Excel copies.\n"
            "Time: a few seconds to a minute per part, depending on the model and quality. The plan shows an estimate that learns from your own runs.\n"
            "Needs: Ollama and a writing model (System check offers the best one for your graphics card). LM Studio, llama.cpp or LocalAI work too.\n"
            "Limits: a local model can get facts wrong. Check names, prices and anything important before you publish.\n"
            "Tips: be specific about tone, length and who it's for. Put your real facts in Inbox so Joe doesn't have to guess.",
            ("write", "writing tasks", "lists", "documents", "articles", "books", "spreadsheets", "descriptions")),
    Ability("pictures", "Pictures", "Pictures",
            "Pictures from your words in 21 styles (photo, anime, watercolor, pixel art, coloring pages, black and white...).",
            "What it does: Joe makes pictures with ComfyUI on your graphics card, from a few words or a long description.\n"
            "How Joe does it: the writing model turns each idea into a detailed picture prompt for the style you picked, Joe adds the style's own words and leave-out list, picks the best installed model for that style (Setup > Workflows lets you choose), and ComfyUI draws it. On High quality a second pass adds fine detail. \"An image of X\" makes 4 versions so you can pick. Coloring pages are forced to clean black and white, with a colored example kept.\n"
            "What to give it: describe what you want: \"8 pictures of mugs on a wooden table, cozy morning light\". Name a style if you like (anime, watercolor, product, mascot, coloring page...). Words that must appear in the picture (a sign, a label) work best with the FLUX.2 [klein] pack.\n"
            "Options: style, number of pictures and versions of each, shape (square, wide, tall), quality (Setup > Images & video), MODEL: to force one.\n"
            "Time: about 10-60 seconds a picture on a modern graphics card; High takes longer.\n"
            "Needs: ComfyUI and at least one picture model (System check and Setup > Models offer free ones, with their licenses).\n"
            "Limits: hands, text and exact counts can still go wrong; make a few versions and pick the best.\n"
            "Tips: say the subject, the setting, the light and the mood. Check Setup > Workflows to see (and change) exactly which words Joe adds.",
            ("images", "picture", "image", "drawing", "art", "styles", "coloring pages", "mascot")),
    Ability("video", "Video", "Video clips",
            "Short video clips from your words (and GIFs), plus black-and-white films.",
            "What it does: Joe makes 5-second clips with the Wan 2.2 video model in ComfyUI.\n"
            "How Joe does it: the writing model writes one clear shot per clip (one subject, one whole-body motion, one camera move, keeping every subject and setting you named). Wan draws it; FFmpeg turns the frames into an MP4. Black-and-white films are made in color and then graded with FFmpeg (keeps hands and faces right), with the color copy kept. Ask for a GIF and a looping GIF is saved too.\n"
            "What to give it: describe the scene and what moves: \"a cat jumping onto a windowsill at sunset, slow camera push in\".\n"
            "Options: quality (High = 1280x704, 40 steps), the Turbo add-on (much faster), Keep my PC usable (smaller 960x544 videos while you use the PC), EXPORT: gif.\n"
            "Time: about 2 minutes a clip with Turbo on a 12 GB card, much longer without.\n"
            "Needs: ComfyUI, the Wan 2.2 video model (about 10 GB) and FFmpeg. Best with an 8 GB+ NVIDIA, AMD or Apple graphics chip.\n"
            "Limits: clips are short; fast or complex motion can wobble. Make a few and keep the best.\n"
            "Tips: one simple action per clip works far better than a whole story in one.",
            ("videos", "clips", "clip", "film", "movie", "gif", "gifs", "animation")),
    Ability("talk", "Talking with Joe", "Talk (F4)",
            "Chat with Joe by voice or typing; he answers out loud, can look things up, see pictures and read files.",
            "What it does: Talk is a chat with Joe. Ask questions, think out loud, or ask him to make a plan.\n"
            "How Joe does it: your voice is turned into text on your PC (Whisper or whisper.cpp), a small quick writing model answers, and Joe's voice (Kokoro) speaks it sentence by sentence so he starts talking in about a second. If you allow lookups, he searches the web for current facts and shows his sources. Drop a picture in and a vision model looks at it; drop a document in and he reads it.\n"
            "What to give it: just talk, or type. Short words act at once: go, stop, report, files, tools, help.\n"
            "Options: Setup > Voice & Talk: voice and speed, mic always listening or push-to-talk (F4), how accurate the hearing is, a small Talk model for quicker answers, how long chats are kept.\n"
            "Needs: Ollama with a writing model; Joe's voice add-on (about 500 MB) for speaking and hearing. The microphone is only used with your permission.\n"
            "Limits: Joe's answers come from a local model, so double-check important facts.\n"
            "Tips: every chat is a whole session: its plan, run and results stay with it, and past chats are in the list to reopen or delete.",
            ("chat", "voice", "talking", "speak", "microphone", "conversation")),
    Ability("home-box", "Working for you", "Just say it (the Home box)",
            "Type what you need in plain words; Joe makes a plan you check before anything runs.",
            "What it does: the big box on Home (F2) takes anything: a request, a question, or a one-word command.\n"
            "How Joe does it: he first decides what you mean, without any AI: a command (go, stop, report, files, tools, check, update) happens at once; a question goes to Talk; work becomes a plan. The writing model writes the plan, Joe checks it and shows it in plain words with a time estimate. Nothing runs until you press RUN IT.\n"
            "Tips: ASK A BIGGER AI next to it lets a big free chatbot write the plan for you. STARTER PACKS give whole bundles from one question. Type \"park this: ...\" to save an idea for later.",
            ("home", "box", "plan", "planning", "ask joe", "queue", "commands")),
    Ability("overnight", "Working for you", "Overnight runs and the queue",
            "Queue as much work as you like; Joe works through it while you sleep and leaves a report.",
            "What it does: Joe runs plan after plan with nobody watching, then writes a morning report (_REPORT.md) and a log.\n"
            "How Joe does it: plans wait in line (Home shows NEXT UP and an overall time estimate). Joe hands the graphics card between writing and pictures, keeps the PC awake, pauses if the card gets too hot, retries parts that fail, and picks up where he stopped if the run is stopped or the PC restarts. A plan file dropped in Missions\\Queue is queued too.\n"
            "Options: Setup > General: keep the PC awake, sleep or shut down when finished, pause above a GPU temperature, retries, phone ping when done (ntfy), quiet hours.\n"
            "Tips: \"do it again\" or \"rerun the black and white videos\" finds those tasks in past runs and plans them again exactly.",
            ("queue", "run", "running", "report", "overnight", "morning report", "resume", "rerun", "do it again")),
    Ability("reminders", "Working for you", "Reminders and lists",
            "\"Remind me at 3pm to call the vet\", \"add milk to my shopping list\": by voice or in the box.",
            "What it does: reminders come to your phone at the time you said, and simple lists (to-do, shopping, any name) live in Joe's folder.\n"
            "How Joe does it: he works out the time from your words (at 3pm, in 20 minutes, tomorrow at 9, on Friday) and hands the reminder to ntfy, the free phone-ping service, with the time to deliver it. ntfy holds it, so it arrives even if this PC is off. ntfy keeps messages for up to 3 days, so a reminder further out waits in Joe's folder and is handed over when it's closer (whenever Joe is open). No AI is needed, so it's instant.\n"
            "What to give it: say or type \"remind me ...\" with a time and what; \"add ... to my ... list\", \"what's on my ... list?\", \"take ... off my list\", \"send my shopping list to my phone\".\n"
            "Options: phone pings are set up in Setup > Display & sound (an ntfy topic name). Without them reminders are still saved in Reminders.md.\n"
            "Limits: ntfy is an online service (only the reminder text goes there). Lists stay on this PC in the Lists folder.",
            ("remind", "reminder", "reminders", "list", "lists", "shopping list", "to-do list", "todo list")),
    Ability("phone", "Working for you", "Joe Phone",
            "Use Joe from your phone on your home Wi-Fi: see the run, stop it, ask, plan, lists, reminders, results.",
            "What it does: a small page Joe serves to your phone. Home shows what Joe is doing (with a STOP button) and a box to ask Joe or tell him what to make; work comes back as a plan with RUN IT, like on the PC. Lists, Reminders and Results (the pictures, videos and files he made) have their own tabs.\n"
            "How Joe does it: Setup > Phone turns it on. PAIR A PHONE shows a QR code; scan it with the phone's camera and the phone gets its own key (Joe keeps only a fingerprint of it). Only phones on your home network can reach it.\n"
            "What to give it: your phone on the same Wi-Fi as this PC, with Joe's window open. Add the page to your home screen so it opens like an app. Speak with the keyboard's microphone button.\n"
            "Options: the port (8770) in Setup > Phone; REMOVE a phone there any time.\n"
            "Limits: works only while this PC is on and Joe's window is open, and only at home (reminders still reach your phone with the PC off through phone pings). From the phone Joe can't change settings, install anything or open files outside his Output folder. Home Wi-Fi traffic isn't encrypted, so don't use it on public Wi-Fi.",
            ("phone", "joe phone", "my phone", "from my phone", "phone app", "mobile", "pair a phone")),
    Ability("language", "Working for you", "Joe in your language",
            "Joe's own screens in Spanish and 22 other languages (Setup > Display & sound > Language).",
            "What it does: switches Joe's window (buttons, settings, tooltips, messages) into another language. Spanish comes with the main screens done.\n"
            "How Joe does it: a language file maps each English line of the window to the other language, and the window swaps them as it shows them. MAKE IT has Joe translate every remaining line himself with the writing model, in small batches, saving as he goes.\n"
            "What to give it: pick the language and press SAVE; press MAKE IT to fill in the rest (it's queued like any task).\n"
            "Options: fix any line in Languages/<code>.json in Joe's folder; your lines win over Joe's.\n"
            "Limits: lines not translated yet stay in English. It's a machine translation until someone checks it. Your own words (the log, Talk, files) are never changed.",
            ("language", "languages", "spanish", "español", "translate joe", "in my language", "other language")),
    Ability("addons", "Working for you", "Add-ons from other people",
            "New tools, starter packs, picture workflows and themes other people made, added in Setup > Add-ons.",
            "What it does: an add-on plugs new things into Joe without changing his code: tools on the Tools tab, starter packs, picture workflows and themes.\n"
            "How Joe does it: ADD AN ADD-ON (a .zip) puts it in the Add-ons folder, switched off. READ AND TURN ON shows who made it and, for each tool, the exact program and command it runs; nothing happens until you say yes. Tools run on copies of your files with a time limit, and only what they write into the task's folder is kept. If an add-on's files change later, Joe turns it off until you look again.\n"
            "What to give it: an add-on .zip from someone you trust. Its tools then work like Joe's own (the planner can use them too).\n"
            "Options: TURN OFF or REMOVE any time. Making one: docs/ADDONS.md.\n"
            "Limits: a tool's program can do anything a program can, so only turn on tools from people you trust. Packs, workflows and themes are data and are checked like Joe's own.",
            ("add-on", "addon", "add-ons", "addons", "plugin", "plugins", "extension", "community tools")),
    Ability("directions", "Working for you", "Directions and shopping",
            "\"Directions to the feed store\" or \"where can I buy an air fryer?\" opens your map or shopping site.",
            "What it does: opens directions or a shopping search in your browser, by voice or in the box.\n"
            "How Joe does it: he takes the place or thing from your words and opens the site you picked with it filled in. No AI and no tracking; the map site works out the route from your location.\n"
            "Options: Setup > General > Directions and shopping: Google Maps, OpenStreetMap, Apple Maps or Bing Maps; Google Shopping, DuckDuckGo or Bing Shopping.\n"
            "Limits: Joe doesn't pick stores or compare prices himself, and nobody pays him: compare on the site.",
            ("directions", "map", "maps", "navigate", "route", "shopping", "buy", "store", "price")),
    Ability("watch-folders", "Working for you", "Watch folders",
            "Drop a file into a tool's folder and Joe does it by himself.",
            "What it does: with watch folders on, Inbox\\Watch has a folder per tool (clean-audio, summarize, privacy-blur...). Anything you drop in is done with that tool's usual options, no plan or button needed.\n"
            "How Joe does it: while he's open he looks in those folders every few seconds; once a file has finished copying he queues one task per tool for the new files. Each file is done once.\n"
            "Options: Setup > General > Watch folders on. The READ ME in Inbox\\Watch lists the folders.\n"
            "Limits: only while Joe is open. Tools that need a choice first (like which language to translate into) don't get a folder.",
            ("watch folder", "watch folders", "hot folder", "drop folder", "automatic", "automatically")),
    Ability("night-shift", "Working for you", "Night shift",
            "Save plans for tonight and Joe starts them at a set time, even with his window closed.",
            "What it does: SAVE FOR TONIGHT keeps a plan for later; at the time you pick, Joe starts by himself and runs them.\n"
            "How Joe does it: he asks your computer's own scheduler to start him (Task Scheduler on Windows, launchd on a Mac, cron on Linux). On Windows he can wake the PC from sleep. With no window open he works through the plans and closes when done.\n"
            "Options: Setup > General > Night shift on, the start time (24-hour clock) and an optional Stop by time: then Joe finishes the mission he's on and leaves the rest for the next night, noted in the morning report. A stop time before the start time means the next morning.\n"
            "Limits: the PC must be signed in; on a Mac or Linux it must be awake. Turned off, or Joe uninstalled, the scheduler entry is removed. Not available while Joe runs from a USB drive.",
            ("night shift", "tonight", "schedule", "scheduled", "save for tonight", "timer")),
    Ability("starter-packs", "Working for you", "Starter packs",
            "Ready-made bundles (shop starter, a month of social posts, blog, party kit, coloring book) from one question.",
            "What it does: pick a pack, answer one question (\"What's your shop and what do you sell?\"), and Joe plans the whole bundle.\n"
            "How Joe does it: each pack is a plan with a blank where your answer goes. Parts your PC can't do yet (music without ComfyUI, say) are left out and the plan says so.\n"
            "Tips: make your own: a plan file in Missions\\Packs with PACK:, ABOUT: and ASK: lines on top and {for} where the answer goes.",
            ("packs", "pack", "bundles", "starter pack")),
    Ability("research", "Working for you", "Looking things up (research)",
            "Writing tasks can look facts up online first and list their sources (only if you allow it).",
            "What it does: a task with RESEARCH: yes is looked up once before Joe writes it; the text marks facts like [2] and a Sources list is added.\n"
            "How Joe does it: only the search words go online (Ollama's web search with a free key, or Wikipedia), the results go to the model with the task, and they're cached.\n"
            "Options: Setup > Voice & Talk > Let Joe look things up online (off until you turn it on). Asking for current facts in the box adds research by itself.\n"
            "Limits: a search can miss things or find wrong pages: check the sources.",
            ("research", "lookup", "look up", "web search", "internet", "sources", "online")),
    Ability("exports", "Working for you", "Finished copies and templates",
            "Word, PDF, EPUB, PowerPoint and Excel copies that follow a template (book, kids, screenplay, resume, price list...).",
            "What it does: EXPORT: docx, pdf, epub, pptx (a slide for every ## heading; or xlsx for spreadsheets, social for post schedulers) makes finished copies next to the text Joe wrote.\n"
            "How Joe does it: Pandoc builds the Word and EPUB files and a styled page for the PDF (printed by Edge or Chrome without a window). The template sets page size, margins, fonts, spacing, page numbers, chapter breaks and more. Spreadsheets get money columns and totals.\n"
            "Options: Setup > Writing > Templates: 17 ready-made ones (standard, book, manuscript, kids, ebook, report, large print, poetry, screenplay, letter, resume, cookbook, recipe card, coloring, school, price list...), EDIT any of them, set a default per file kind, or ADD YOUR OWN. A task picks one with TEMPLATE: and its name.\n"
            "Needs: Pandoc for Word, PDF, EPUB and PowerPoint (System check installs it).",
            ("export", "word", "pdf", "epub", "powerpoint", "pptx", "slides", "excel", "docx", "xlsx", "templates", "template", "formatting", "book layout")),
    Ability("bigger-ai", "Working for you", "Ask a bigger AI",
            "A paste-ready message for any big chatbot (ChatGPT, Claude, Gemini...); paste its answer back and Joe runs it.",
            "What it does: Joe's own model is small. ASK A BIGGER AI writes one message with what Joe is, the exact plan format, what your PC can do, your request and (if you like) the last report's problems.\n"
            "How Joe does it: you copy it into any chatbot, paste the whole answer back, and Joe finds the plan in it, tidies what that chatbot got wrong (and tells you), checks it and shows it like his own.\n"
            "Limits: nothing leaves your PC unless you paste it; folder paths and your user name are hidden. Free, no keys, works with any chatbot.",
            ("bigger ai", "chatgpt", "gemini", "grok", "chatbot", "paste")),
    Ability("connector", "Working for you", "Use Joe from another AI app (connector)",
            "Claude Desktop and other apps can use Joe directly: see what he can do, queue plans, run tools, read results.",
            "What it does: Joe works as a connector (MCP) for AI apps on your PC, so a bigger AI hands grunt work to Joe and polishes the results.\n"
            "How Joe does it: Setup > General > SHOW CONNECT OPTIONS lists the apps Joe found (Claude Desktop, ChatGPT desktop, Gemini CLI, Cursor, LM Studio) with a CONNECT button each; Joe adds only his own entry to that app's settings and keeps a copy of the old file.\n"
            "Limits: the other app can't install anything, change settings, or reach outside Joe's folder. Chatbots in a web browser can't reach programs on your PC: use ASK A BIGGER AI for those.",
            ("mcp", "connector", "claude desktop", "connect", "another ai app")),
    Ability("portable", "Working for you", "Portable Joe (run from a USB drive)",
            "Copy Joe to a USB drive and carry him to any computer, with your work and models.",
            "What it does: MAKE A PORTABLE JOE (Setup > General) copies Joe to a drive or folder with a \"Start Joe\" file. Started from there, he keeps his settings, your work and everything he sets up on the drive instead of the computer's folders.\n"
            "How Joe does it: a portable.txt file next to his program tells him he's portable. Downloads and caches go to the drive. From System check he can put Ollama (on its own port, so the computer's Ollama is left alone) and ComfyUI on the drive too. Paths are saved relative to the drive, so a different drive letter on another PC still works.\n"
            "Options: bring along your settings, your work, your writing models and your picture models (sizes are shown first).\n"
            "Limits: each computer still needs its own graphics driver. Windows may still remember that a program ran: portable means carried with you, not invisible. The night shift is off while running from a drive. A FAT32 drive can't hold files over 4 GB (most models): use exFAT or NTFS, and a fast USB 3 drive.\n"
            "Tips: you can run MAKE A PORTABLE JOE again later; it carries on and skips what's already copied.",
            ("portable", "usb", "flash drive", "thumb drive", "drive mode", "carry")),
    Ability("stats", "Working for you", "Stats (F9)",
            "What Joe made, how long it took, and what the same work would have cost in the cloud.",
            "What it does: F9 counts words, items, pictures and video seconds, time spent, power used and the honest cloud price of the same work, for today, this week, this month, this year or all time. It also shows how much space Joe's files use, with a way to clean up.\n"
            "Options: Setup > Stats & costs: cloud prices and your power price, so the numbers match your situation.",
            ("statistics", "numbers", "savings", "cost", "storage", "space")),
    Ability("setup", "Setting up", "System check, models and setup",
            "Joe finds, installs and updates what he needs, with your OK for every step.",
            "What it does: System check (Setup, F10) shows what Joe found on your PC and offers each missing piece with its size and license: Ollama, ComfyUI, FFmpeg, Pandoc, voice, and the best models for your graphics card.\n"
            "How Joe does it: he looks for programs where they're usually installed (and the ones you already have, like LM Studio or Automatic1111/Forge models), checks your graphics card and memory, and only downloads after you say yes. DOWNLOAD ALL in Setup > Models gets every offered model overnight. Once a week he can check for newer versions (only telling you).\n"
            "Options: Setup > Workflows sets the model and words for each kind of picture, video and sound. RESET THIS PAGE and RESET ALL SETTINGS put things back. MAKE A HELP FILE packs up what someone helping you needs (never your files). CHECK MY MODEL FILES (Setup > Models) finds a model whose download stopped part way, with no internet needed. BACK UP MY SETTINGS (Setup > General) saves everything you set up by hand in one zip, and RESTORE brings it back on any computer.\n"
            "Limits: setup, downloads and update checks use the internet. Joe tells you each time. Before a big download (or a plan that makes lots of pictures or video) he checks there's room on the drive and tells you if there isn't. Updates are only installed when their checksum (and, for signed releases, the maker's signature) matches.",
            ("system check", "install", "installing", "models", "download", "updates", "settings", "setup helper", "workflows",
             "backup", "back up", "restore", "model check", "broken model", "disk space")),
    Ability("quality", "Setting up", "Quality vs speed",
            "Low, Medium or High for writing, pictures and video; High is the default for overnight work.",
            "What it does: one setting per kind of work trades speed for quality.\n"
            "How Joe does it: Low uses smaller, quicker models; High uses the best model, lets writing think each part through, and adds a detail pass to pictures and full-size video. Proofreading, translating and asking your files always use the best model. If a plan asks for \"high quality\" or \"quick\", Joe offers to switch for just that kind of work.\n"
            "Tips: Keep my PC usable (Setup > General) lowers Joe's priority while you use the computer.",
            ("quality", "speed", "faster", "slow", "high quality", "keep my pc usable")),
    Ability("looks", "Setting up", "Looks, sounds and screen savers",
            "Retro green-screen or modern looks, an easy-to-read font, Joe's jingle and screen savers.",
            "What it does: Setup > Display & sound changes how Joe looks and sounds: modern day/night, futuristic, green, amber or white retro screens, your own color themes, text size, the CRT effect, an easy-to-read font (Atkinson Hyperlegible), the opening jingle and Joe's hello.\n"
            "Screen savers: 10 built in, or MAKE SCREEN SAVER describes one in words and Joe builds it.",
            ("theme", "themes", "look", "display", "font", "screen saver", "screensaver", "jingle", "colors")),
    Ability("ideas", "Working for you", "Park an idea",
            "\"park this: a recipe book for my mom\" saves the idea, dated, for later.",
            "What it does: type park this: and your idea in the box or in Talk. Joe adds it to Ideas.md in his folder, so it's out of your head and safe for later.\n"
            "Tips: open Ideas.md any time to look through them; when you're ready, type the idea in the box and Joe makes a plan for it.",
            ("park", "park this", "idea", "ideas", "save an idea")),
)

# --------------------------------------------------------------------------- how each Tool works, step by step
STEPS: dict[str, tuple[str, ...]] = {
    "transcribe": ("Joe pulls the sound out of the file with FFmpeg.",
                   "Whisper (or whisper.cpp) listens on your processor and writes every word with its time.",
                   "He saves the text, a subtitle file (.srt) if ticked, and the writing model writes the notes: a summary, key points and to-dos."),
    "read-aloud": ("Joe reads the document's text (Word, PDF, web page or plain text).",
                   "He splits it into sentences and Joe's voice (Kokoro) speaks them on your processor.",
                   "FFmpeg joins the pieces into an MP3 (one per chapter if you ticked it)."),
    "find-book": ("Joe reads the ISBN or title (or the vision model reads it off your photo of the cover or barcode).",
                  "He looks the book up in Open Library, then on Project Gutenberg for a free public-domain copy.",
                  "If there is one, he downloads the text into Inbox/books and queues Read aloud; if not, he says how to scan your own copy."),
    "memory-voice": ("Joe reads your document and splits it into parts.",
                     "The voice-copy add-on says each part in the voice made from your family recording.",
                     "Joe joins the parts into one MP3 with a note that it was made by AI (the voice program also watermarks it)."),
    "proofread": ("Joe splits your writing into parts the model can check carefully.",
                  "The best writing model lists each real mistake as before / after (no rewriting your style).",
                  "Joe applies each change himself, skips any he can't find exactly or that are already right, and writes the change list next to the corrected copy."),
    "translate": ("Joe splits the text into parts at paragraph breaks.",
                  "The best writing model translates each part, keeping headings and lists.",
                  "Anything it isn't sure about is marked [CHECK]; each language gets its own copy."),
    "ask-files": ("Joe reads every document in the folder and cuts them into small passages.",
                  "For each question he finds the passages that fit (with a small search model if installed).",
                  "The best writing model answers only from those passages and Joe shows which ones it used."),
    "summarize": ("Joe reads the document (a long one in parts, keeping every name, number and date).",
                  "The writing model turns the parts into one summary in the shape you picked.",
                  "Anything unclear is marked [CHECK]; your file is never changed."),
    "rewrite": ("Joe splits the text at paragraph breaks.",
                "The writing model rewrites each part the way you asked, keeping every fact and adding none.",
                "You get the new copy and a short list of what changed."),
    "brainstorm": ("Joe reads what you need ideas for (and your file, if you added one).",
                   "The writing model lists varied ideas, from safe to bold, with no repeats.",
                   "Prices or facts it isn't sure of are marked [CHECK]; park the ones you like."),
    "study": ("Joe reads your material (a long one in parts).",
              "The writing model explains it at your level, using only your material.",
              "It also makes flashcards (a CSV for Anki or Quizlet) and a practice quiz with answers."),
    "code-review": ("Joe reads the code with line numbers, in parts for long files. He never runs it.",
                    "The writing model explains it and lists likely bugs and risks, each with a fix.",
                    "Test ideas and easy improvements are added if you asked."),
    "ai-search": ("Joe pulls the business facts out of what you gave (never adding any).",
                  "The writing model writes a FAQ and descriptions from those facts.",
                  "Joe builds the website schema code and llms.txt himself and lists any missing facts."),
    "meal-plan": ("Joe reads your budget, how many people and what to avoid (and your price list, if added).",
                  "The writing model plans cheap meals and a shopping list with prices.",
                  "Joe adds up the total himself, marks estimated prices [CHECK] and says if it's over budget."),
    "clean-audio": ("FFmpeg cuts low rumble (and electrical hum if you ticked it).",
                    "It removes steady background noise at the strength you picked.",
                    "It evens out the volume to the usual podcast level; a video keeps its picture."),
    "tidy-speech": ("Joe listens to the recording word by word, with the time of every word.",
                    "He marks every um, uh and er, and every silence longer than you picked.",
                    "FFmpeg cuts them out (long pauses become a short natural gap) and Joe lists every cut."),
    "joe-language": ("Joe collects every line of his own window (buttons, settings, tooltips, messages).",
                     "The writing model translates them in small numbered batches, keeping names and {1} places as they are.",
                     "Joe saves them to Languages/<code>.json as he goes; pick the language in Setup > Display & sound."),
    "edit-words": ("Joe listens word by word, with the time of every word, and writes what was said as plain text.",
                   "You delete the words you don't want and give the file back; Joe lines it up with what he heard.",
                   "FFmpeg cuts each deleted word (and the gap after it) out of a copy, and Joe lists every cut."),
    "dub-video": ("Joe listens to the video line by line, with the time of each line.",
                  "The writing model translates every line; Joe saves them as a subtitles file.",
                  "For languages his voice speaks, Joe's voice says each line at its time over the original sound turned down."),
    "b-roll": ("Joe listens to the talking video line by line, with times.",
               "The writing model matches your clips and photos (by their names) to what's said.",
               "FFmpeg lays each match over the speaker for a few seconds; the sound stays theirs, and Joe lists every cutaway."),
    "privacy-blur": ("The vision model looks at each photo and marks faces, plates, addresses or screens.",
                     "FFmpeg blurs a little more than each marked spot, hard enough that it can't be read back.",
                     "Joe saves a copy without GPS details and says what he blurred; you check it before posting."),
    "social-graphic": ("Joe takes your words exactly as typed: the first line is the headline.",
                       "FFmpeg fits your photo (or a plain color) to each size you picked.",
                       "It adds a dark band and places the words with a real font, so the spelling is exactly yours."),
    "ask-sheet": ("Joe reads the spreadsheet's columns and a few rows.",
                  "The writing model turns your question into a plan (which column, which rows, add or count).",
                  "Joe's own code does the math and shows how it was worked out, with a bar chart for several rows."),
    "sort-files": ("Joe reads the start of each document.",
                   "The writing model picks a folder and a clear name (with the document's own date).",
                   "Joe makes sorted copies and a list of what went where; the originals stay put."),
    "calendar-file": ("Joe reads your notes, emails or transcript in parts.",
                      "The writing model lists every date, time and to-do it actually says ('next Friday' counted from today).",
                      "Joe builds calendar.ics himself; guessed dates are marked [CHECK]."),
    "tidy-sheet": ("Joe reads the CSV or Excel sheet.",
                   "He trims spaces and removes duplicate rows himself (instant).",
                   "The writing model fixes spelling, adds categories or splits columns if you asked, and every change is listed."),
    "photo-batch": ("Joe copies each photo with FFmpeg, made smaller (never bigger) and in the format you chose.",
                    "Camera details and GPS location are left out of the copies.",
                    "A faint watermark is added only if you gave one, in the corner you picked."),
    "read-scans": ("Big photos are shrunk first so the vision model can read them.",
                   "A vision model on your PC copies exactly what's written; unclear bits are marked [CHECK].",
                   "Receipts and tables become a spreadsheet; text becomes a document."),
    "photo-listing": ("A vision model looks at each product photo.",
                      "It writes a title, description, search tags and alt text from what it can see (and what you told it).",
                      "Joe saves a spreadsheet for shop uploads and a readable document."),
    "sort-photos": ("A vision model looks at every photo.",
                    "It gives each one a category, tags and a caption (never naming faces), reusing short categories.",
                    "Joe writes photo-list.csv and copies each photo into a folder for its category."),
    "remove-bg": ("ComfyUI runs BiRefNet to find the subject and cut it out.",
                  "Joe puts it on a see-through or white background.",
                  "If you asked, Real-ESRGAN makes it 2x or 4x bigger and sharper."),
    "edit-picture": ("Joe frees the graphics card and sends your picture and words to the Qwen picture editor in ComfyUI.",
                     "The editor makes the change you asked for; the picture keeps its shape.",
                     "If the card runs out of memory, Joe tries once more at a smaller size and tells you."),
    "restore-photo": ("True to the photo: FFmpeg undoes fading and color casts, smooths grain in gentle rounds, then makes it bigger and a little sharper. Nothing is redrawn.",
                      "AI repair (only if you pick it): a vision model finds the faces first, the picture editor mends scratches, tears and stamps (and adds color if asked), then Joe pastes the real faces back from a true-to-the-photo copy.",
                      "Sepia prints can keep their warm tone; the original is never changed."),
    "fix-spot": ("You paint over the spot with MARK THE SPOT; Joe saves the mark next to the picture.",
                 "The picture editor redraws only inside the mark (removing what's there, or putting what you asked).",
                 "Joe puts every unmarked pixel back from your original, so nothing else changes."),
    "merge-pictures": ("Joe sends picture 1 and up to two more to the picture editor with your words.",
                       "The editor combines them into one new picture.",
                       "The new picture is saved; your pictures stay as they were."),
    "relight": ("Joe tells the picture editor the light you picked, and to keep everything else the same.",
                "The editor changes only the light and shadows.",
                "The relit copy is saved next to your original."),
    "restyle": ("Joe tells the picture editor the new style, keeping what's in the picture and where.",
                "\"Like my last picture\" uses your last picture as the look for the others.",
                "Each restyled copy is saved; originals stay."),
    "redraw": ("Joe sends your picture and words to the picture editor.",
               "How much may change sets how far the AI may move away from your picture.",
               "The new take is saved next to your original."),
    "make-bigger": ("Joe adds space around your picture in the direction you picked.",
                    "The picture editor paints the new parts to match the scene.",
                    "Joe puts your original back in the middle, untouched."),
    "character-scenes": ("Joe sends your character picture to the picture editor once per scene.",
                         "Each time it's told to keep the exact same face, outfit, colors and art style.",
                         "One picture per scene line is saved."),
    "character-spin": ("Joe asks the picture editor for six views of the same character (front, three-quarter, sides, back).",
                       "Each view keeps the face, outfit and colors.",
                       "He puts all six side by side on character-sheet.png."),
    "sketch-to-picture": ("Joe turns your drawing into clean outlines (paper is made dark, lines bright).",
                          "ControlNet holds the AI to your shapes while an SDXL picture model paints the finished picture in the look you chose.",
                          "How closely it follows your lines is your choice: close, some or loose."),
    "illusion-art": ("FFmpeg draws the hidden shape (spiral, circles, checker, waves, a word) or uses your black-and-white picture.",
                     "QR Code Monster guides an SDXL picture model so the scene bends around that shape.",
                     "Joe makes the number of versions you chose; each one looks different."),
    "make-3d": ("Joe puts the object on a white square (cutting it out first when the background remover is installed).",
                "Hunyuan3D 2.1 in ComfyUI builds the 3D shape from the picture.",
                "It's saved as a .glb file: a plain white model, ready to paint or print."),
    "animate-photo": ("Joe sends your photo and the motion you described to the Wan 2.2 video model.",
                      "Wan makes a 5-second clip that starts from your photo.",
                      "FFmpeg saves it as an MP4."),
    "restyle-video": ("FFmpeg cuts your video into 5-second pieces and traces the outlines of every frame.",
                      "Wan 2.2 Fun Control paints a new video over those outlines in the new look (and your picture's look, if you added one).",
                      "Joe puts the original sound back on each piece and joins them into one video."),
    "make-shorts": ("Joe writes down every word with its time (Whisper).",
                    "The writing model picks moments that stand on their own: a strong start, one complete thought, a clean ending.",
                    "FFmpeg cuts each one as a tall 1080x1920 clip, following the speaker's face if a vision model is installed, with big captions, a hook title and a post for each if ticked."),
    "pdf-tools": ("qpdf (a free PDF program) opens your PDFs on this computer: no AI is used.",
                  "It joins, splits, picks or reorders pages, turns them or shrinks the file exactly as you chose; "
                  "for a form, Joe first lists every field so you can fill them in plain lines.",
                  "Joe saves the new PDFs and a short report; locked or damaged PDFs are explained in plain words."),
    "explain-letter": ("Joe reads the letter (a photo is read word for word by the vision model first).",
                       "The writing model lists the dates, amounts, contacts and reference numbers; Joe checks each "
                       "one is really in the letter, works out the days left and points out scam signs.",
                       "Then it explains the letter in plain words with next steps, and drafts a reply you can fill in."),
    "hide-details": ("Joe's own patterns find emails, phone numbers, card numbers (checked with the card-number "
                     "sum), account, ID and policy numbers, street addresses and birth dates.",
                     "The writing model adds people's names and home addresses; Joe only hides words that are "
                     "really in the text, plus anything you typed.",
                     "He saves a cleaned copy with labels like [NAME 1] (or black blocks) and a list of how many of "
                     "each were hidden."),
    "meeting-minutes": ("Joe listens to the recording with Whisper on this PC (or reads your transcript).",
                        "The writing model pulls out decisions, to-dos (who, by when) and open questions, and writes "
                        "a summary; a long meeting is done in parts.",
                        "Joe checks names and dates against what was said ([CHECK] if not) and saves the minutes, "
                        "the transcript and, if ticked, a calendar file of to-dos."),
    "bank-budget": ("Joe reads your bank's CSV or Excel file and finds the date, description and amount columns.",
                    "He sorts well-known shops himself; the writing model sorts the rest from their names only.",
                    "Joe's own math adds it all up: money in and out, categories by month, regular payments with "
                    "their cost a year, and price rises."),
    "resume-tailor": ("The writing model lists what the job posting asks for.",
                      "It finds each one in your resume; Joe keeps a match only when the quoted line is really there.",
                      "It writes the tailored resume and cover letter; Joe marks anything not in your resume "
                      "[CHECK] and lists the gaps."),
    "mail-merge": ("Joe finds the {Name}-style spots in your letter and matches them to the spreadsheet's columns.",
                   "For every row he makes a copy of the letter with that row's details (Word formatting kept).",
                   "He saves one letter per row, one file with them all, and a list of empty cells or unmatched spots."),
    "compare-docs": ("Joe reads the text of both versions (Word, PDF, text or web page) and splits it into paragraphs.",
                     "He lines the paragraphs up, pairs each edited paragraph with its new version and marks the words that went and came in.",
                     "He saves one report: a summary, then the changed, added and removed paragraphs. Nothing is guessed and neither file is touched."),
    "alt-text": ("Big pictures are shrunk first so the vision model can look at them.",
                 "The vision model describes what it sees, without naming people.",
                 "Joe trims each short description to 125 characters at a whole word and saves a CSV and a document."),
    "duplicate-photos": ("Joe fingerprints every photo: its exact bytes, and a tiny 9x8 picture of how it looks.",
                         "Photos with the same or nearly the same fingerprint are grouped.",
                         "For each group he suggests a keeper (biggest, then sharpest) and makes a side-by-side "
                         "picture; nothing is moved or deleted."),
    "music": ("Each line you type becomes one piece.",
              "ACE-Step (music) or Stable Audio Open (sound effects) makes it in ComfyUI on your graphics card.",
              "Joe saves it as an MP3."),
}

NEED_WORDS = {"voice": "Joe's voice add-on (about 500 MB; whisper.cpp also works for hearing)",
              "ollama": "Ollama and a writing model", "ffmpeg": "FFmpeg (free; System check installs it)",
              "comfy": "ComfyUI", "vision": "a vision model in Ollama (System check offers a free one)",
              "sdxl": "an SDXL picture model", "qpdf": "qpdf (a free PDF program; System check installs it)"}


def _tool_abilities() -> list[Ability]:
    from .tools import TOOLS
    out = []
    for t in TOOLS.values():
        if not t.ready:
            continue
        aliases = (t.id.replace("-", " "),)
        out.append(Ability("tool:" + t.id, "Tools (F3)", t.name, t.blurb, "", aliases))
    return out


def all_abilities() -> list[Ability]:
    return list(OTHER) + _tool_abilities()


GROUP_ORDER = ("Writing", "Pictures", "Video", "Talking with Joe", "Tools (F3)", "Working for you", "Setting up")


def overview() -> str:
    """Everything Joe can do, grouped, one line each."""
    groups: dict[str, list[Ability]] = {}
    for a in all_abilities():
        groups.setdefault(a.group, []).append(a)
    lines = ["Here's everything I can do. It all runs on your own computer."]
    for g in sorted(groups, key=lambda g: GROUP_ORDER.index(g) if g in GROUP_ORDER else 99):
        lines.append("")
        lines.append(g.upper())
        lines += [f"- {a.name}: {a.line}" for a in groups[g]]
    lines += ["", MORE]
    return "\n".join(lines)


def groups() -> list[dict]:
    """The same, for the WHAT CAN JOE DO? screen."""
    out: dict[str, list[dict]] = {}
    for a in all_abilities():
        out.setdefault(a.group, []).append({"id": a.id, "name": a.name, "line": a.line})
    return [{"name": g, "items": out[g]}
            for g in sorted(out, key=lambda g: GROUP_ORDER.index(g) if g in GROUP_ORDER else 99)]


def _choice_words(o) -> str:
    if not o.choices:
        return "on to start with" if o.default else "off to start with"
    labels = [c[1] for c in o.choices]
    default = next((c[1] for c in o.choices if c[0] == o.value), labels[0])
    if len(labels) > 8:
        return f"{len(labels)} choices; starts on {default}"
    return "pick " + ("one or more" if o.multi else "one") + ": " + " / ".join(labels) + f". Starts on: {default}"


def _tool_text(tid: str) -> str:
    from .tools import TOOLS
    t = TOOLS[tid]
    parts = [f"What it does: {t.blurb}"]
    steps = STEPS.get(tid, ())
    if steps:
        parts.append("How Joe does it, step by step:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)))
    if t.accepts:
        parts.append(f"What to give it: {', '.join(t.accepts[:12])}{' and more' if len(t.accepts) > 12 else ''} files. "
                     "Drop them on the tool's card in Tools (F3), or put them in Inbox.")
    else:
        parts.append("What to give it: just your words in the tool's box (one per line).")
    if t.options:
        parts.append("Options:\n" + "\n".join(f"- {o.label}: {_choice_words(o)}." + (f" {o.hint}" if o.hint else "")
                                              for o in t.options))
    if t.help:
        parts.append("Good to know (time, size, limits): " + t.help)
    needs = [NEED_WORDS[n] for n in t.needs if n in NEED_WORDS]
    try:
        from .picturetools import PACKS, TOOL_PACKS
        for p in TOOL_PACKS.get(tid, ()):
            if p in PACKS:
                pk = PACKS[p]
                some = "" if "comfy" in t.needs else "for some options: "
                needs.append(f"{some}{pk.label} (about {pk.size_gb:g} GB, {pk.license}; Setup > Models offers it)")
    except Exception:                 # noqa: BLE001 (explanations never fail)
        pass
    if needs:
        parts.append("Needs: " + "; ".join(needs) + ". The tool's card says Ready, or what's missing with a GET IT button.")
    if t.examples:
        parts.append("Examples: " + " | ".join(t.examples[:3]))
    if t.accepts:
        parts.append("Tips: try it on one or two files first, look at the result, then run the rest.")
    return "\n\n".join(parts)


def get(aid: str) -> Ability | None:
    return next((a for a in all_abilities() if a.id == aid), None)


def explain(aid: str) -> dict | None:
    """{id, title, text} for one ability, or None."""
    a = get(aid)
    if not a:
        return None
    text = _tool_text(aid[5:]) if aid.startswith("tool:") else a.text.replace("\n", "\n\n")
    return {"id": a.id, "title": a.name, "text": text}


# --------------------------------------------------------------------------- understanding the question
_STOP = {"a", "an", "the", "my", "your", "of", "to", "and", "from", "in", "by", "into", "one", "for", "on",
         "joe", "joes", "you", "it", "is", "do", "does", "how", "what", "with", "i", "me", "can", "work",
         "works", "tool", "about", "tell", "more", "explain", "use"}
OVERVIEW_Q = re.compile(r"^\s*(?:hey |so |ok |okay )?(?:joe[, ]+)?(?:what (?:all |else |exactly )?(?:can|could) "
                        r"(?:you|joe) do|what (?:all )?do you do|what are (?:all )?(?:your|joe'?s) "
                        r"(?:features|abilities|skills|tools)|what is joe able to do|what can i (?:do|make) "
                        r"with (?:you|joe)|show me (?:everything|what you can do)|list (?:your|all) "
                        r"(?:features|abilities)|abilities|features|what can joe do)\s*[?!.]*\s*$", re.I)
EXPLAIN_Q = re.compile(r"^\s*(?:(?:hey |so |ok |okay )?(?:joe[, ]+)?(?:please |(?:can|could|would) you (?:please )?)?)"
                       r"(?:how (?:does|do|would|will|can) .+\b(?:work|works|do|does)\b|how (?:do|can|should) i "
                       r"use\b|what (?:does|is|are|'s)\b|whats\b|tell me (?:more )?about\b|explain\b|more "
                       r"(?:about|on)\b|learn (?:more )?about\b|what can .+ do\b|how .+ works?\b)", re.I)


def _tokens(s: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", (s or "").lower()):
        if w in _STOP:
            continue
        out.add(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def find(text: str) -> str | None:
    """The ability a question is about, or None. Every token of one of its names must be in it."""
    words = _tokens(text)
    if not words:
        return None
    best, score = None, 0
    for a in all_abilities():
        for alias in (a.name, a.id.split(":")[-1].replace("-", " "), *a.aliases):
            toks = _tokens(re.sub(r"\(.*?\)", "", alias))
            if toks and toks <= words and len(toks) > score:
                best, score = a.id, len(toks)
    # most of the question must be about it ("what can a vision model do?" is not about models)
    if best and (score == len(words) or (score >= 2 and score * 2 >= len(words))):
        return best
    return None


def answer(text: str) -> dict | None:
    """{kind: overview|explain, id?, title, text} for "what can you do?" or "how does X work?"."""
    t = (text or "").strip()
    if not t or len(t) > 300:
        return None
    if OVERVIEW_Q.match(t):
        return {"kind": "overview", "title": "What Joe can do", "text": overview()}
    if EXPLAIN_Q.match(t):
        aid = find(t)
        if aid:
            e = explain(aid)
            return {"kind": "explain", **e} if e else None
    return None
