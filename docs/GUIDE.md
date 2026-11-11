# Joe — the full guide

Everything about missions, keys, screens and the command line. New here? Start with the [README](../README.md).

## Workspace

Default: `Documents\Joe-ai`.

```
Inbox\      reference files you drop in (facts, price lists) — read with INPUT:
Output\     everything Joe writes, plus _REPORT.md, _log.txt, _progress.txt
Projects\   project profiles: brand voice, facts, rules (one .md per project)
Missions\   saved mission files; Missions\Queue\ = drop a mission file here to queue it;
            Missions\Tonight\ = plans saved for the night shift; Missions\Packs\ = your own starter packs
Workflows\  ComfyUI workflows in API format (optional; image tasks have a built-in one)
Themes\     custom color themes and screen savers (made in F10, or by hand)
Ideas.md    ideas you parked ("park this: ...")
```

### How Joe files his work (Setup > General)

New in 2.3. **By date** (the default): every mission gets one folder in Output with the date in
front, named after its first task, and everything it makes goes inside:

```
Output\2026-11-10 Product blurbs +1\
    product-blurbs\product-blurbs.md, product-blurbs.docx, product-blurbs v2.md
    mug-photos\001_....png ...
```

- A piece of writing gets its own folder with its finished copies (EXPORT) and versions inside.
- A mission with just one task uses the mission folder itself.
- Running a task again (RUN on a past mission, or the same plan another day) puts the new result
  inside the original's folder: `name v2.md` for writing, a `v2` folder for pictures and tools.
  Nothing is ever written over. Joe remembers where each task went in `Output\.joe\filing.json`.
- A SAVE: line still names the file; its folder part is replaced by the mission folder. Watch
  folders keep `Output\watch-<tool>`. An INPUT: that points at a file an earlier task of the same
  mission SAVEs is pointed at the new place for you.

**By project**: the same mission folders, inside `Output\<PROJECT name>\` (a mission without a
PROJECT: line goes in Output as "by date"). **Flat**: straight into Output under the SAVE: name,
like Joe did before 2.3.

Changing this never moves anything you already have. **TIDY MY OUTPUT** does that, once, when you
press it: **LOOK FIRST** lists every move; nothing is deleted or written over; reruns named
`x_v2`, `x-redo`, `x-retry`, `x2` go inside the original's folder as v2, v3; loose files that belong
together (`notes.md`, `notes.docx`) go into one folder; `_REPORT.md`, Backups, watch folders and
folders that already start with a date stay where they are. The list of moves is saved in
`Output\_TIDY_UNDO_<date>.txt`, and **UNDO THE LAST TIDY** moves everything back. Joe updates his run
records, the morning reports and project lists so resume and the reports still find your files.

### Projects (Files F7 > PROJECTS)

A project groups missions. A plan with `PROJECT: My Shop` joins the project "My Shop" by itself
when it runs (the project is made if it's new); any folder in Output can be added by hand. The
project page has:
- **About this project**: Joe reads this when he writes for the project (it's the
  `Projects\<name>.md` profile, as before).
- **My notes**: just for you; Joe doesn't read them.
- **What's left**: a to-do list you tick off, plus any task in its folders that didn't finish.
- **Its missions and files**: every file in its folders; OPEN IN FILES jumps there.
- **NEW MISSION IN THIS PROJECT** starts a plan on Home with the PROJECT: line filled in.
Removing a project only takes it off the list: its folders and files stay.

Settings live in `%APPDATA%\joe-ai\settings.json` (Mac: `~/Library/Application Support/joe-ai`,
Linux: `~/.config/joe-ai`), never in the app folder. A Portable Joe keeps everything on its drive
instead (see Portable Joe below).

## Just describe it (Home, F2)

The big box on the Home screen takes plain words: "40 product descriptions for handmade mugs,
friendly and short, plus 8 pictures of mugs on a wooden table". Press **MAKE A PLAN** (or
Ctrl+Enter). Joe's local model writes the mission and you see it in plain words:

```
JOE'S PLAN — about 14 minutes
 • 40 items: Mug descriptions
 • 8 pictures: Mugs on a table
```

**RUN IT** starts it (or puts it in line if Joe is busy), **CHANGE IT** opens it in Step by step (F6),
**START OVER** clears it. Nothing runs until you press RUN IT.
Time estimates learn from your own runs; until then they're marked as a rough guess. TEST MY
SPEED (in the setup helper or Setup > System check) times one small batch to get them right at once. The mission text itself is under
**ADVANCED** for anyone who likes editing it by hand; the plan updates as you edit.

### Ask a bigger AI (free, any chatbot, no keys)

Joe's own model is small. **ASK A BIGGER AI** (next to ASK JOE) makes one message you paste into
any chatbot you like (ChatGPT, Claude, Gemini...): what Joe is, the exact mission format, the
tools on your PC, what you typed in the box, and (if you leave the tick on) Joe's last report and
the problems from his log. Read it first: nothing leaves your PC unless you paste it, and folder
paths and your user name are hidden. Paste the chatbot's whole answer into the second box and
press **USE THIS PLAN**: Joe finds the mission in it, checks it, and shows it like his own plan.
Every chatbot writes the plan a little differently, so Joe tidies the answer first and tells you
what he changed: lost line breaks, bold or bulleted keys, a list in one huge part (1 x 30 becomes
5 x 6), a style name he doesn't know (black and white becomes bw), a price list that says it
"matches" the descriptions (he adds FROM: so it really does).

### What can Joe do?

Ask "what can you do?" (in Talk or the box) and Joe lists everything, grouped, one line each. Ask
about one part ("how does restore photo work?", "tell me about the night shift", "how do I use make
shorts?") and you get the long version: what it does, how Joe does it step by step behind the
scenes, what to give it, every option and when to pick it, time, what it needs (models, sizes,
licenses), limits and tips. No AI is used for these answers, so they're instant and always match
the program. The same is behind **WHAT CAN JOE DO?** on Home and Help (F1), and the "learn more"
link on every Tools card (and LEARN MORE ABOUT THIS TOOL in its form). Developers: the text lives in
`joeai/abilities.py`; tools are explained from their own help and options plus a short STEPS list,
and a test fails if a new tool has no STEPS.

### Matching names between tasks (FROM:)

Each task is written on its own. When a spreadsheet or pictures must use the names from a list
above it (a price list for the candles you just described, one picture per product), add
`FROM: <that task's name>` and use the same number. Joe hands over the finished names in order.
In Step by step (F6) it's **Use the names from**.

### Setup: Models, Workflows and resets

- **Better-model tips**: when a model you don't have would do a job better (FLUX.2 klein for words in a
  picture, groups of people or two animals; a style's own picture model; the video Turbo add-on) and it
  suits your graphics card's memory, the run log says so once, with the reason. System check then
  lists that offer first, marked **RECOMMENDED** with the reason. Offers too big for your card say so.
  Nothing downloads until you press its button. With the writing model left blank (Joe picks), Joe's
  pick for your card's memory is offered there whenever it's missing (RECOMMENDED), with the alternative
  and the little-to-no-filtering choice beside it: pick whichever you want.
- **Models** (Setup > Models): every model download Joe offers, sorted by what it's for (writing,
  pictures and styles, video, picture tools, music and sound, helpers, newer copies), plus
  SHOW MY MODELS. System check keeps the programs (Ollama, ComfyUI, FFmpeg...). **DOWNLOAD ALL**
  at the bottom gets every model on the page, one after another (it shows the list and rough total
  size first, keeps going if one fails, adds follow-on files by itself, keeps the PC awake, and
  has a STOP button). Good for slow connections: press it at bedtime.
- **Workflows** (Setup > Workflows): for Joe's built-in pictures, each picture style, video, the
  picture editor tools, Animate a photo, music, sound effects and every workflow file you
  imported, pick the model and see **Joe's own words**, filled in: what he tells the prompt writer,
  the words he adds to every prompt, and his leave-out list (the Pictures list is Joe's general
  one; Video clips' is Wan's, partly in Chinese because Wan was trained that way, and it's also used
  by Animate a photo). EDIT unlocks a box; your copy replaces Joe's for that workflow, and JOE'S
  WORDS puts his back. Below them, **also add** / **also leave out** take your extra words, and (for
  pictures) the number of steps. RESET THIS WORKFLOW brings everything back to how Joe came.
  Pictures and each picture style also have **FINE-TUNING**, filled in with Joe's own values (hover
  each for what it does): **prompt strength (CFG)** (lower it to 4-5 when pictures get fake writing
  or look overcooked), **style add-on strength** (LoRA), the **detail pass** (auto / on / off) and
  how much it may repaint, the **sampler**, and **versions per prompt** (make 3 and pick the best:
  handy for people and animals). Only the values you change are kept. **Video clips** have
  prompt strength and **motion** (low / normal / high).
- **MORE LIKE THIS** and **WHY DOES THIS LOOK WRONG?** (Files, F7, under a picture Joe made): the
  first puts that picture's recipe in the plan box with its seed locked, so changing a few words keeps
  the layout; the second asks what's wrong (fake writing, bad hands, cloned faces, plastic look,
  blur, ignored words...) and says which setting to change.
- **Folder and file boxes** (Joe's folder, ComfyUI's models/output folders, start commands, FFmpeg):
  the [ + ] button next to each opens this computer's own chooser and fills the box. Press SAVE.
- **Restart Joe**: a bar with RESTART JOE shows up when a restart helps: newer Joe files were copied
  into his folder, helpers were set up, or DOWNLOAD ALL finished. It asks first; Joe closes and opens
  again by himself (LATER hides it).
- **Reset**: every Setup page has RESET THIS PAGE, and System check has RESET ALL SETTINGS. Each
  asks first, and only a click on YES, RESET does it (Enter doesn't). Your stats, files, chats,
  models, Joe's folder and any keys you typed are never touched.
- **Stats** (F9): Today, This week, This month, This year or All time.

### Starter packs

**STARTER PACKS** (next to ASK JOE) are ready-made bundles: a small shop starter (descriptions, a
matching price list, About page, FAQ, product pictures), a month of social posts, a blog starter,
a party or event kit, and a kids coloring book. Pick one, answer one question ("What's your shop
and what do you sell?"), and Joe shows the whole plan. A part this PC can't do yet (music without
ComfyUI, say) is left out and the plan says so. Your own packs: a mission file in
`Missions\Packs` with `PACK:`, `ABOUT:` and `ASK:` lines on top, and `{for}` where the answer goes.
A file in `Missions\Queue` may also hold several mission blocks; each is queued in turn.

### Park an idea

Type `park this: a recipe book for my mom` in the box. Joe adds it, dated, to `Ideas.md` in his
folder, so it's out of your head and safe for later.

### Looking things up for a task (RESEARCH: yes)

A writing task with `RESEARCH: yes` is looked up online once before Joe writes it. The facts go
to the model, the text marks them like [2], and a **Sources** list is added at the end (a
`-sources.md` file next to a spreadsheet). Only the search words go online, and only when Setup >
Voice & Talk > **Let Joe look things up online** is on; otherwise Joe writes from what he knows and
the plan warns you. Ask for research or current facts in the box and Joe adds it himself.

### GIFs

A video task with `EXPORT: gif` also saves a looping GIF next to each clip. Asking for "a gif of
..." in the box does this by itself.

### Reminders and lists (Home box or Talk)

Say or type it the way you'd say it to a person:

```
remind me at 3pm to call the vet
remind me in 20 minutes to take the bread out
remind me tomorrow at 9 to feed the horses
add milk and eggs to my shopping list
what's on my shopping list?
take milk off my shopping list
send my shopping list to my phone
```

Reminders come to your phone as a phone ping (Setup > Display & sound > phone ping, an ntfy topic
name, free). Joe hands each one to ntfy with the time to deliver it, so it arrives even if your PC
is off by then. ntfy holds messages for up to 3 days: a reminder further out waits in
`Reminders.md` and Joe hands it over once it's within 3 days (whenever he's open). Without phone
pings, reminders are still saved in `Reminders.md`. Lists are plain files in Joe's `Lists` folder
(one per name: to-do, shopping, anything). No AI is used, so these are instant.

Quick answers and voice controls are instant too (no AI, no internet): "what time is it?",
"what's the date today?", plain arithmetic like "what's 15% of 80?" or "12 times 7", "stop talking"
(cuts Joe's voice off) and "say that again" (repeats his last answer). Anything else that needs
current facts (weather, opening hours) is answered in Talk when Setup > Voice & Talk > Let Joe look
things up online is on, with the sources shown.

### Joe Phone (Setup > Phone)

Use Joe from your phone while you're home: see what he's doing (and STOP a run), ask him anything or
tell him what to make (work comes back as a plan with RUN IT, the same as on the PC), check your lists
and reminders, and look at the pictures, videos and files he made.

1. Setup > Phone: tick **Joe Phone on** and press SAVE. Windows may ask once whether Joe may use your
   network: pick **Private networks**.
2. Press **PAIR A PHONE** and scan the QR code with your phone's camera (or type the address shown
   into the phone's browser). The code works for 10 minutes, for one phone.
3. Name the phone and tap PAIR. Then use the browser's menu > **Add to Home screen** so Joe opens like
   an app. To speak instead of type, tap the microphone on your phone's keyboard.

It works while this PC is on, Joe's window is open, and the phone is on the same Wi-Fi. Reminders
still reach your phone with the PC off (phone pings). Only phones on your home network can reach it;
Joe never opens your router to the internet. REMOVE (Setup > Phone) ends a phone's access right away.
From the phone Joe can't change settings, install anything or open files outside his Output folder.
Home Wi-Fi traffic isn't encrypted (like most home devices' own pages), so use it at home, not on
public Wi-Fi.

### Joe's screens in other languages (Setup > Display & sound > Language)

Pick a language and press SAVE: Joe's window switches right away. Spanish comes with the main
screens done; anything not translated yet stays in English, so a half-made language still works.
**MAKE IT** has Joe translate the rest of his screens himself with the writing model (a queued task,
good for the night shift; a stopped run carries on next time). He saves it to
`Languages/<code>.json` in Joe's folder: English on the left, the translation on the right. Fix any
line there and it wins over Joe's built-in file. Your own words (the log, Talk, files, what you type)
are never changed.

### Add-ons from other people (Setup > Add-ons)

Add-ons bring new tools, starter packs, picture workflows and themes that other people made.
**ADD AN ADD-ON** takes the .zip; it stays off. **READ AND TURN ON** shows who made it and, for every
tool, the exact program and command line it runs, before you say yes. Its tools then sit on the
Tools tab (F3) like Joe's own, and plans can use them (`TYPE: x-<tool>`).

Tools run on copies of your files, without a command shell, with a time limit, and only what they
write into the task's folder is kept. If anything in an add-on changes after you turned it on, Joe
turns it off until you look again. A tool's program can still do anything a program can: only turn
on tools from people you trust. TURN OFF or REMOVE any time. To make one, see
[ADDONS.md](ADDONS.md); there's a full example in `examples/addons/simple-extras`.

### Night shift (Setup > General)

**SAVE FOR TONIGHT** (on the plan) keeps a plan for later. Turn on **Night shift** in Setup >
General and pick a time (24-hour clock, e.g. 23:00): Joe asks your computer's own scheduler to
start him then (Task Scheduler on Windows, launchd on a Mac, cron on Linux). On Windows he also
wakes the PC from sleep for it. If his window is open
he just runs them; if not, he starts without a window, works through them (keep-awake, "when
finished", phone ping all apply) and closes when done. Open Joe during the night to watch. The PC
has to be signed in; on a Mac or Linux it also has to be awake. Turning it off, or uninstalling Joe, removes
the scheduler entry. Plans saved for tonight sit in `Missions\Tonight`.

**Stop by (optional):** put a stop time next to the start time (24-hour, e.g. 07:00; blank = run
until done). At the stop time Joe finishes the mission he's working on, puts every plan he hasn't
started back in `Missions\Tonight` for the next night, and the morning report (and phone ping)
says so: "3 missions left for tomorrow night". Then he closes if he started without a window. A
stop time earlier than the start time means the next morning (start 23:00, stop 06:00). If the PC
was asleep or off and the scheduler only starts Joe after the stop time, he leaves the plans for
the next night instead of running into your day. A mission that's already running is never cut
off half-way.

### Watch folders (Setup > General)

Turn on **Watch folders** and Joe makes a folder per tool in `Inbox\Watch` (`clean-audio`,
`summarize`, `privacy-blur`...), with a READ ME listing them. Drop a file into one while Joe is open
and he runs that tool on it by himself, with the tool's usual options: no plan, no button. Only
tools that read files and need no choice from you get a folder. Results land in `Output` as usual.

### Check my model files (Setup > Models)

**CHECK MY MODEL FILES** makes sure every picture, video and sound model (`.safetensors`, in ComfyUI's
models folder and any shared A1111/Forge folders) is whole. Each such file says in its first bytes how
big it must be, so Joe can spot one whose download stopped part way without the internet and without
changing anything. A cut-short file gets a **MOVE ... TO THE RECYCLE BIN** button; after that, Setup >
Models offers its download again. (Writing models are checked by Ollama itself.)

### Room on the drive

Before a download starts, Joe compares its size with the free space (plus a spare GB so the computer
keeps working) and stops with a plain message if it won't fit. A plan that makes lots of pictures,
video or tool copies gets a "Low on space" warning, and the log says so at the start of a run when less
than 2 GB is free.

### Back up and restore my settings (Setup > General)

**BACK UP MY SETTINGS** saves one zip in `Output\Backups`: your settings, your own writing templates,
workflow words, color themes and screen savers (`Themes`), imported workflows (`Workflows`), project
profiles (`Projects`) and your own starter packs (`Missions\Packs`). Keys, the connector password and
the phone-ping topic only go in when you tick **Include keys and passwords**. Never inside: your files,
chats, recordings or models. **RESTORE FROM A BACKUP** brings it back on any computer: settings become
the backup's, except where things are on this computer (Joe's folder, program paths) and keys the
backup doesn't have. Files you already have are never overwritten; a different file with the same name
comes back as `name (restored)`.

### Portable Joe (Setup > General)

**MAKE A PORTABLE JOE** copies Joe to a USB drive or any folder you pick (into a folder called
`Joe`). Press LOOK first to see what can come along and how big it is: Joe's program (and his
private Python, when he came with one) always; your settings (paths to programs on this PC are left out),
your work, your writing models (Ollama) and your picture and video models (ComfyUI) if you tick
them. Nothing on this computer changes, and you can press it again later to carry on: files
already copied are skipped.

On the drive:

```
Joe\Start Joe.bat        (Windows; Start Joe.command on a Mac, start-joe.sh on Linux)
Joe\portable.txt         (tells Joe he's portable; delete it and he uses the PC's folders again)
Joe\app\                 Joe's program (+ python\ when he has his own)
Joe\Joe-ai\              your work (Inbox, Output, Missions...)
Joe\JoeData\settings\    settings, chats, the window's profile, crash.log
Joe\JoeData\data\        add-ons: voice, Ollama, Joe's own ComfyUI and its models, caches
```

Started from the drive, Joe shows PORTABLE next to his version and keeps everything there:
downloads and caches (uv, Python, Hugging Face, PyTorch) go to the drive too. System check offers
**Put Ollama on the drive** (Ollama's official release from GitHub, run on its own port 11435 with
its models in `JoeData\data\ollama-models`, so the computer's own Ollama is left alone) and **Put
ComfyUI on the drive** (Joe's own copy with a private Python; models you copied are already in
place). Until then Joe uses the computer's Ollama and ComfyUI if it has them. Paths are saved
relative to the drive, so a different drive letter on another PC is fine; helper environments are
pointed at the new place by themselves.

Good to know: each computer still needs its own graphics driver, and Joe uses its Edge or Chrome
for the window (with a profile kept on the drive). Windows may still remember that a program ran
(prefetch, the page file): portable means carried with you, not invisible. The night shift is off
while Joe runs from a drive (it would leave a task in that computer's scheduler). Use a fast USB 3
drive (an SSD is best) formatted as exFAT or NTFS: FAT32 can't hold files over 4 GB, which most
models are. On a Mac or Linux the drive copy uses the computer's Python 3.11.4+ unless Joe came with
his own.

### Keep my PC usable (Setup > General)

For using the PC while Joe works: Ollama and ComfyUI run at below-normal priority (so the mouse,
browser and games stay smooth) and videos are made smaller (960x544 instead of 1280x704). Runs
take a little longer. Leave it off overnight.

### Use Joe from another AI app (MCP)

A bigger AI can use Joe directly, the way a helper hands grunt work to an assistant: it sees
what Joe can do on this PC (models, tools, how long things take), suggests which parts Joe should
make, writes and queues the plan, makes pictures, runs Joe's tools on files in his Inbox, checks
the report, reads the results and looks at the pictures, then polishes them for you. It can't
install anything, change settings, or reach outside Joe's folder.

Setup > General > **SHOW CONNECT OPTIONS** lists the apps Joe knows on this PC. Wherever an app has
its own way to add a connector, Joe uses it, so the app itself asks you and nobody has to open a
settings file:

- **Cursor, LM Studio, VS Code (Copilot)**: ADD TO ... opens the app's own install link; the app
  shows its own box asking you to add Joe.
- **Gemini CLI**: Joe runs Gemini's own command (`gemini mcp add -s user joe ...`).
- **Claude Desktop**: OR AS AN EXTENSION makes a small extension file for this PC (`Joe.mcpb`) and
  opens it; Claude Desktop shows its own Install box. CONNECT writes Joe's entry into Claude's
  settings file instead: Joe finds it wherever this Claude Desktop keeps it (`Claude-Data`, the MSIX
  package folder or `%APPDATA%\Claude`).
- **ChatGPT desktop**: reads the same connector list as Codex (`~/.codex/config.toml`). ChatGPT on the
  web can't reach programs on your PC at all.

Whenever Joe has to write an app's settings file, **close that app completely first**: while it's
open it keeps its own copy of its settings and writes it back later, wiping out Joe's entry. Joe
checks and won't continue while it's running (Claude Desktop keeps running in the tray: end it in
Task Manager). Joe only ever touches his own entry, keeps a copy of the file as it was before he
first touched it (`.before-joe`), and leaves a file he can't read alone.

System check keeps an eye on the apps you connected: if one lost Joe (it moved or reset its
settings), or starts Joe from an old place (Joe's folder moved, Python was updated, or it points at
another copy of Joe), it says so with a RECONNECT button. Uninstalling Joe takes him out of every
app's settings, so none keeps trying to start a Joe that's gone. For other apps, copy the lines
shown there. Apps that connect by address can use `http://127.0.0.1:<port>/mcp` with the key shown
there, while Joe's window is open. Chats in a web browser (ChatGPT or Gemini on the web, Grok) and
the Gemini and consumer Copilot desktop apps can't reach programs on your PC; for those, use ASK A
BIGGER AI. When an app asks Joe for something while his window is closed, queued plans wait and
run when Joe's window opens (or at the night-shift time); his status says whether the window is open.


## Building it step by step (F6)

Step by step (the Builder) makes the mission for you with simple forms:

- **+ ADD SOMETHING**, pick what it is (a list of things, a document, a spreadsheet, pictures,
  short video clips) and fill in the blanks: **How many?**, what each one looks like, how many
  **versions of each picture**, the **shape** of the pictures. Joe splits big counts into small
  batches himself so the AI stays sharp.
- **MORE OPTIONS** holds the rest: file name, profile, batches, models, seed, ComfyUI workflow.
- **↑ ↓** reorder, **COPY** duplicates, **SPLIT** cuts one in two, **REMOVE** takes it off.
- **MORE** (left) has the profile, IMPORT for a pasted mission, and START OVER.
- **RUN IT** starts it. **ADD TO QUEUE** adds it after whatever Joe is doing. Queued missions
  run one after another until all are done, with one combined morning report. Sleep/shut down
  happens only after the last one. **STOP** (F5) finishes the step Joe is on; missions still
  waiting in line are kept **ON HOLD** (shown under the queue, saved in `Missions\Queue\on hold\`),
  never thrown away: **RUN THEM** puts them back in line in the same order, **CLEAR** puts them
  away (a copy stays in `Queue\done\`).
- **SAVE** keeps it in `Missions\` under a name. **PAST MISSIONS** lists every mission you've
  run, how many tasks finished, and LOAD / RUN buttons to revisit one. **DEL** removes one from
  the list and **CLEAN UP** clears them all (both ask first and use the Recycle Bin; only the saved
  plans go, never what they made or plans you saved yourself).
- **Drop-in queue:** any `.txt` or `.md` mission file put in `Missions\Queue\` while Joe is open
  is queued on its own within about 10 seconds (oldest first), then moved to `Queue\done\`.
  A file with a problem goes to `Queue\problems\` with a `.problem.txt` note saying what's
  wrong. Handy for missions written somewhere else (by another app, a helper, or Claude).

### Installer warnings (Mac and Windows)

**Mac:** macOS says Joe can't be checked for malicious software. Apple charges developers $99 a
year to remove that warning; Joe is free and makes no money, so we don't pay it. All of Joe's code
is open on GitHub for anyone (or any AI) to check. Open it once with System Settings > Privacy &
Security > **Open Anyway** next to Joe > **Open**.

**Windows:** until Joe's free SignPath Foundation certificate is in place, SmartScreen may say
"Windows protected your PC": **More info** > **Run anyway**. If Windows pauses and then says
SmartScreen "couldn't be reached", that's its online check timing out: choose **Run anyway**.

## First start, tabs and looks

The first time Joe opens, a setup helper walks through it one step at a time. **Hello** lets you
pick Joe's look right away (change it any time in Setup > Display & sound, or describe your own
under CUSTOM THEME and Joe designs it). Then your graphics card in plain words, then **Pick**: a checklist of everything Joe could install, grouped (Writing,
Pictures, Talking, Extras), each with its size, and a running total. Small and needed things start
ticked; big downloads (the picture editor, video, music) start unticked, and picture programs are
pre-ticked only on a strong graphics card. **INSTALL WHAT'S TICKED** installs them one after
another; more choices appear once Ollama and ComfyUI are in. The later steps (writing, pictures,
talking, extras) still explain each piece with its own **YES**, and the last one picks a look.
Reopen it any time: Setup (F10) > System check > **SETUP HELPER**.

**The top bar**, left to right: making things (Home F2, Tools F3, Talk F4, Step by step F6), seeing
results (Files F7, Report F8, Stats F9), then Setup F10 and Help F1 (ABOUT JOE is at the bottom of
Help). On the right: **RUN/STOP** (F5) and the **TOOLS n/28** badge. Hover the badge to see every
tool with √ (ready) or × and what it still needs; click it for System check. Ollama and ComfyUI
keep their up/down lights in the status bar.

Joe finds the programs he works with on his own: ComfyUI Desktop (old and new program names),
a portable ComfyUI (`run_nvidia_gpu.bat`) or your own install with a `venv`, ComfyUI's models
folder (from its own settings), and Ollama, FFmpeg and Pandoc from the usual install folders
(winget, Scoop, Chocolatey, Program Files, Homebrew). F10 > System check shows what he found.
Anything you type in Setup wins; if that path stops existing, Joe looks again.

If the model that suits your PC best isn't installed, System check (and the setup helper) offers
to download it: a bigger writing model when your graphics card has room for one, a small quick
model just for Talk, a smaller one when Writing quality is Low, a picture model, the video model
and its Turbo add-on. Every download asks first.

**Picking a writing model.** For writing, Joe offers three models that fit your graphics card, each
with who made it and one or two plain sentences on why it's there and what it costs:

- **Recommended**: Joe's pick, the best all-round writer for your card (Gemma 4 or Llama on most PCs).
- **Alternative**: another strong choice (Qwen 3: better at code and other languages, but
  made in China, so it often dodges or refuses questions about Chinese politics and history).
- **Little to no filtering**: follows your instructions with very few refusals (Mistral, Dolphin or
  Hermes, depending on the card). Usually a little less accurate than Joe's pick; the note says so.

Tick the one you want before pressing the download button. Prefer something else? Type any model's
name in Setup > Writing > Model (Ollama downloads it the first time), or bring your own model with
LM Studio, llama.cpp or LocalAI. The list lives in `joeai/model_picks.json` on GitHub, so it can
change without a new version of Joe.

Every screen has a tab along the top (the F-keys still work). Hover over any button and the
bottom line says what it does.

Looks (Setup > Display & sound > Theme): **Modern** (follows your PC's day/night setting), **Modern day**,
**Modern night**, **Futuristic**, and the **Retro** green, amber and white screens (the old-screen
effect only applies to the retro looks). CUSTOM THEME still designs a retro-style look from a
description. **Easy-to-read font** (same section) switches every look to Atkinson Hyperlegible, a
font made by the Braille Institute for low vision, where letters like I, l and 1 never look alike.
All fonts ship with Joe (SIL Open Font License, files in `joeai/ui/fonts`), so nothing loads online.

Joe opens fresh every time. If the last run didn't finish (stopped, crash, power cut), he asks on
start: **Y** resumes where it stopped, **N** starts fresh (it stays in History).
Pictures and video always run after the writing tasks, so the GPU switches over only once.

### Older model files (.ckpt)

Model files ending in .ckpt, .pt, .pth or .bin are an older format that can run hidden code when
they're loaded. Joe always uses a .safetensors file first when there's a choice, and Setup >
System check > Your models lists any older ones so you can swap them for .safetensors copies.

### Graphics cards other than NVIDIA

System check names your graphics and says plainly what they mean for Joe. NVIDIA cards give the
full picture (temperature, load, memory). AMD cards on Linux report the same through the driver;
AMD and Intel on Windows only give the name and memory, and Apple Silicon Macs share the main
memory with the graphics (Joe counts about two thirds of it for models). Where the card doesn't
report a temperature, the cool-down pause is simply off. Writing works on all of them (on recent
AMD cards and Apple Silicon at good speed; on Intel or without a card, on the processor, so pick
a small model). Pictures and video: fine on NVIDIA, slower on Apple Silicon and AMD on Linux,
shaky on AMD under Windows (ComfyUI Desktop doesn't support AMD). The video model is only offered
on NVIDIA, AMD and Apple Silicon with 8 GB+, and "Sound like me" only on NVIDIA.

### Use the programs and models you already have

- **Other writing programs**: Setup > Writing > Writing program picks the program, with a line
  under it on what each is good for and what it costs:
  - **Ollama** (recommended): Joe installs, starts and fills it, and frees the graphics card for
    pictures. The easiest; a little slower than a hand-tuned llama.cpp.
  - **LM Studio** (alternative recommended): a desktop app where you see and manage your models.
    On a Mac with an M chip, its MLX models usually write about 20-30% faster than Ollama.
  - **llama.cpp** (fastest, for advanced users who like to tinker): often 20% or more quicker once
    tuned, but you find the model files and settings yourself.
  - **LocalAI** and **Other** (bring your own): Jan, KoboldCpp, vLLM, Apple MLX and more. vLLM is
    built for many users at once and holds most of the graphics card, so it doesn't share well
    with pictures.

  With the
  others, you add models in that program; Joe writes with whatever it has (the biggest one that fits
  your card, or the one in Setup > Writing > Model). LM Studio: Joe starts its server himself with
  its `lms` helper. llama.cpp and LocalAI: put the line that starts them in More options > Start
  command (for example `llama-server -m C:\models\model.gguf --port 8080 --ctx-size 8192`), or
  start them yourself. Joe only talks to programs on this PC or your home network. One catch:
  llama.cpp and LocalAI keep their model in the graphics card, so pictures and video get less room
  while they run (LM Studio's is unloaded for picture work, like Ollama's).
- **Other (OpenAI-compatible)**: for Jan, KoboldCpp, vLLM, Text Generation WebUI and anything else
  that speaks the OpenAI-style language. Put its address in More options > Other program's address
  (usual ports: Jan 1337, KoboldCpp 5001, vLLM 8000, Apple MLX's `mlx_lm.server` 8080), the model name in Model (exactly as that
  program lists it; blank = the first one it has), and a Key only if the server asks for one (vLLM
  started with `--api-key`, a KoboldCpp password). **TEST CONNECTION** checks that it answers, lists
  its models and says plainly what's wrong if not (not running, wrong port, key needed, model not
  there). The key stays in your settings and is blanked in help files. Online addresses are refused
  even with a key: Joe never sends your work to a paid online service.
- **AUTOMATIC1111 / Forge / reForge models**: when System check finds a Stable Diffusion WebUI folder,
  SHARE THEM adds it to ComfyUI's extra model folders file (Desktop: `extra_models_config.yaml` in its
  settings folder; portable and own installs: `extra_model_paths.yaml` next to ComfyUI). Checkpoints,
  LoRAs, VAEs, upscalers, embeddings and ControlNets are used where they are: nothing is copied. The
  old file is kept as `.joe-backup`; Joe's lines start with `# joe-ai`. Restart ComfyUI afterwards.
  Joe also reads any extra folders you added yourself when he looks for picture models.
- **whisper.cpp**: a faster transcriber (Transcribe, Make shorts), especially on Macs, and the
  Transcribe tool then works without the voice add-on. System check offers it on Windows (a 4 MB
  download into Joe's add-ons folder) and Macs (Homebrew). On Linux Joe uses `whisper-cli` if you
  have it. Setup > Voice & Talk > Transcribe with: Auto uses it when it's there.

## Quality vs speed (Setup > Writing, and Setup > Images & video)

Each kind of work has its own **Low / Medium / High** choice, so you can have quick drafts but
careful pictures, or the other way round. The line under each choice says what it does.

| | Low (fastest) | Medium (balanced) | High (best, slowest, the default) |
|---|---|---|---|
| **Writing** | a smaller, quicker model if you have one installed | the best model for your PC | the best model, thinking each part through first (often 2-3x slower) |
| **Pictures** | about half the drawing steps, slightly smaller pictures (about 2x faster, less detail) | the model's normal settings | more steps and a finer sampler (sharper, about 1.5x as long) |
| **Video** | about 3-second, smaller clips; very quick with the Turbo add-on | full 5-second 1280x704 clips, using Turbo when installed | the full model with extra steps, never Turbo (can take 20+ minutes a clip on a 12 GB card) |

**Turbo add-on for video**: once the video model is installed, System check offers the
Wan 2.2 5B Turbo add-on (under 1 GB, Apache 2.0). It makes a clip in 4 steps instead of 20,
several times faster, with a little less detail. Low and Medium use it; High never does.
Restart ComfyUI after downloading it.

When a level works best with a model you don't have yet, Joe says so right under that choice,
for example "Based on your Low setting, I'd recommend llama3.1:8b (4.9 GB) for this. Should we install
it?", with a **YES, INSTALL IT** button. The plan for a video task mentions the Turbo add-on the
same way. Nothing downloads without your yes.

**When thinking runs out of room.** On High, some models (Gemma among them) can think so long about
a short job, like a list of jokes, that they run out of room and write nothing. Joe spots the empty
answer, says so in the log, and writes the rest of that task without thinking first, so the list
still finishes quickly. And if a list comes up a few items short (repeats dropped, a part that ran
out of tries), Joe writes the missing items at the end, so 100 asked means 100 written.

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
  the screen saver starts; any key or mouse move wakes Joe. Setup > Display & sound > SCREEN SAVER
  picks one: Joe (classic drifting status), Binary rain (Joe's real name, 01000001 01001001),
  Coffee break (the mug that started it all), Starfield, Bouncing Joe, Phosphor waves, Fireflies,
  Snowfall, Pipes or Retro clock. PREVIEW shows it now. Or describe one ("a calm night sky with slow
  orange shooting stars that says GOOD NIGHT") and MAKE SCREEN SAVER: the local model picks the
  animation, colors, speed, how busy it is and a short line of text, and Joe draws it. Like custom
  themes, it's only those settings, never code, and colors are checked so it stays visible. Yours are
  saved in Themes\savers and DELETE MINE removes one.
- **Quiet hours** (e.g. 22:00 to 07:00): no chimes and no phone pings. A ping waits until they end.
- **Phone ping when done** (off until you set it): install the free ntfy app, subscribe to a topic
  name only you know, type the same name in Setup and press SEND A TEST PING. Joe sends one short
  line when a run is done ("Joe is done: 3 of 3 tasks done, 48 items."), nothing from your files.
  It's the only thing Joe ever sends off your PC, and only when you turn it on.

## Tools (F3)

Ready-made jobs for your own files. Each card opens a short form: drop your files on it (or click
to pick them), tick the extras you want, give it a name if you like, and press **RUN IT** (it
queues behind other work if Joe is busy). **SHOW THE PLAN** shows the plan and the mission text
without running. Files you add are copied into `Inbox\tools\<tool>\`; your originals aren't
touched. Dropping a recording anywhere outside Talk opens Transcribe with it. Dropping a
document on the Tools tab lights up the tools that can use it (Read aloud, Proofread); pick one.
All the tools are ready. The picture and sound tools need ComfyUI and their model once (see
"Picture and sound tools" below).

You can also just ask on the Home screen ("turn the call I added into notes", "read my story
aloud"): Joe sees the files waiting in Inbox and plans the right tool task. In a mission:

```
TASK: Tuesday meeting  TYPE: transcribe
INPUT: tools/transcribe/meeting.mp3        (files or folders in Inbox, comma-separated)
OPTIONS: subtitles, notes                  (or none; leave it out for both)
                                           (+ language spanish | language auto, notes-in english)
FORMAT: focus on dates and to-dos           (optional, for the notes)
```

**Transcribe a recording** makes, per recording, in `Output\<task name>\`:
`<name>.txt` (the transcript, a [mm:ss] time at the start of each paragraph), `<name>.srt`
(subtitles) and `<name>-notes.md` (summary, key points, decisions, to-dos, written by the
writing model from the transcript; anything unclear is marked [CHECK]). Long recordings are
noted in pieces, then combined. It needs Joe's voice add-on (Setup > System check) and FFmpeg
for anything but .wav. It uses the Hearing setting (Setup > Voice & Talk; Most accurate is
slower) and runs on the processor, so it can work while pictures draw. A stopped run picks up at
the next recording.

**Languages.** `language <name>` (Spoken in, on the form) is English by default; the others are
the same 23 as Translate, or `language auto` to let Joe find out (slower and less sure: pick it
if you know it). Anything but English uses Whisper's all-languages model (Fastest/Balanced/Most
accurate become tiny/base/small instead of tiny.en/base.en/small.en). The first time, Joe
downloads it once from Hugging Face (about 75-480 MB, only the model, never your recording).
The transcript says which language it is. Notes are written in the recording's language unless
you pick `notes-in english`. Big languages are heard best; check names and numbers.

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

**Picture tools** (Listings from photos, Read scans and receipts, Sort my photos) read .jpg,
.png, .webp, .bmp and .tif and use a vision model in Ollama (any installed model whose name
says it can see, like qwen2.5vl; Setup > System check offers one sized for your graphics
card). Each photo is turned upright and shrunk with FFmpeg before Joe looks at it (without
FFmpeg only JPG/PNG/WebP under 6 MB work). Originals are never changed or moved. A stopped
run carries on at the next picture.

- **Listings from photos** (`TYPE: photo-listing`, `OPTIONS: csv, doc`): `listings.csv`
  (File, Title, Description, Tags, Alt text) and `listings.md`. FORMAT tells Joe about the
  products and tone. Only what's visible is described; anything else is marked [CHECK].
- **Read scans and receipts** (`TYPE: read-scans`, `OPTIONS: as text|receipts|table`): text
  gives `<name>.md` per picture plus `all-text.md`; receipts gives `receipts.csv` (File, Date,
  Store, Total, Tax, Currency, Items) and `receipt-items.csv`; table gives `<name>.csv`. Words
  and numbers are copied as written, never fixed or guessed; unclear bits are marked [CHECK],
  and a receipt with no total is flagged. PDFs aren't read by this tool yet.
- **Sort my photos** (`TYPE: sort-photos`, `OPTIONS: folders` or none): `photo-list.csv`
  (File, Category, Tags, Caption) and, with folders, a copy of each photo in
  `<task>\<Category>\`. FORMAT `categories: family, garden, pets` gives the list (anything
  else goes to Other, or is flagged); without it Joe picks short categories and reuses them.

**Ask my files** (`TYPE: ask-files`) reads the same documents as Proofread (files or whole
folders). FORMAT holds the questions, one per line (or each ending with ?):

```
TASK: Lease questions  TYPE: ask-files
INPUT: tools/ask-files
FORMAT: Are pets allowed?
        When is rent due, and what's the late fee?
OPTIONS: summaries                      (optional: a summary of each document too)
```

Joe cuts the documents into pieces of about 220 words, finds the pieces that best fit each
question, and asks the writing model to answer only from those, naming the excerpts it used
([1], [2]...). If they don't answer it, he says so. `answers.md` has each question, the answer
and the excerpts (file, part, first words) so you can check. With no question, or with
**summaries**, `summaries.md` has a short summary of each document plus anything worth
knowing (dates, amounts, deadlines). Finding the pieces works by words straight away; with a
search model installed (Setup > System check offers nomic-embed-text, about 270 MB) it also
matches by meaning, which helps a lot in big folders. The search model's results are kept in
`Output\.joe\search\` so asking again is quick. Nothing leaves your computer.

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

### More writing, file and sound tools (new in 2.1)

These work like the ones above: a card on the Tools tab, or just ask on Home. None of them changes
your original files.

- **Summarize** (`TYPE: summarize`, `OPTIONS: length short|points|chapters`): an article, PDF, book
  or web page as a short summary, key points (the default) or chapter by chapter. Long documents
  are read in parts and joined; names, numbers and dates are copied as written.
- **Rewrite or change the tone** (`TYPE: rewrite`, `OPTIONS: style friendly|formal|shorter|simpler|email|resume|custom`):
  a new copy plus a "what changed" list. For a resume, paste the job post in the box; Joe never
  invents jobs, skills or results (missing things are marked [CHECK]).
- **Brainstorm** (`TYPE: brainstorm`, `OPTIONS: kind ideas|names|gifts|angles|outline|solutions, count 10|25|50`):
  say what you need ideas for; a file is optional. Keep a favorite with "park this: ...".
- **Study helper** (`TYPE: study`, `OPTIONS: level kid|teen|adult|expert` plus `explain`, `cards`,
  `quiz`, `teach`): uses only your material. Flashcards come as a Front,Back CSV for Anki or
  Quizlet; "teach" asks you questions first so you learn it.
- **Explain or review my code** (`TYPE: code-review`, `OPTIONS: explain, bugs, tests, tidy`): real
  line numbers; Joe reads the code and never runs it.
- **Get found by AI search** (`TYPE: ai-search`): from the business facts you give (or your About
  page), a FAQ, a short description, schema code and an llms.txt file, with a README saying where
  each goes. Missing facts are listed, never guessed.
- **Budget meal planner** (`TYPE: meal-plan`, `OPTIONS: days 3|5|7`): your budget, how many people
  and what to avoid. Joe adds up the list himself and says plainly if it goes over. Add a receipts
  spreadsheet for real prices; otherwise prices are estimates marked [CHECK].
- **Ask my spreadsheet** (`TYPE: ask-sheet`, questions one per line in FORMAT): the writing model
  only turns each question into a plan; Joe's own code does the math and shows how, with a bar
  chart when there are several rows.
- **Sort and rename my files** (`TYPE: sort-files`, `OPTIONS: folders, rename`): sorted COPIES with
  clear names ("2026-03-02 Electric bill.pdf"), in your own folders if you type them, plus a list of
  what went where.
- **Dates and to-dos to my calendar** (`TYPE: calendar-file`): `calendar.ics` from notes, emails or
  a transcript, for Google Calendar, Outlook or Apple Calendar. Joe never touches your calendar
  account; guessed dates are marked [CHECK].
- **Find a book to read aloud** (`TYPE: find-book`, `OPTIONS: aloud yes|no`): an ISBN, a title or a
  photo of the cover or barcode. Public-domain books come from Project Gutenberg and are queued
  for Read aloud; for books under copyright, scan your own pages. Needs online lookups on; only the
  ISBN or title is sent.
- **Clean up a recording** (`TYPE: clean-audio`, `OPTIONS: strength light|normal|strong, hum, level`):
  less noise and hum and an even volume, with FFmpeg in seconds, no AI. A video keeps its picture.
- **Cut out ums and long pauses** (`TYPE: tidy-speech`, `OPTIONS: fillers, pauses, pause 0.7|1.0|1.5|2.5`):
  Joe listens word by word and cuts the fillers and long silences, with a list of every cut.
- **Edit a video by its words** (`TYPE: edit-words`): two steps. Run it once and Joe writes what was
  said as a words file in Output. Delete the words you don't want (only delete, never retype), put
  the file in the Inbox next to the video and run it again: Joe cuts those words out.
- **Dub or voice-over a video** (`TYPE: dub-video`, `OPTIONS: to <language>, voice, voice-of man|woman, original low|half|off`):
  subtitles in the new language, and with `voice` Joe's voice says each line at its time over the
  original sound turned down. A machine translation: have it checked before publishing.
- **Add B-roll to a talking video** (`TYPE: b-roll`, `OPTIONS: amount few|some|lots`): the talking
  video plus your own clips and photos (name them for what they show, like `kiln-firing.mp4`). Joe
  cuts to them where they match what's said, keeping the speaker's sound, and lists every cutaway.
- **Privacy blur** (`TYPE: privacy-blur`, `OPTIONS: blur faces|plates|addresses|screens|kids`):
  the vision model finds them and FFmpeg blurs them hard; GPS details are left out of the copy.
  Nothing picked means faces, plates, addresses and screens. Always look before posting.
- **Social graphics and flyers** (`TYPE: social-graphic`, `OPTIONS: size ig-post|ig-portrait|story|fb-post|fb-cover|x-post|yt-thumb|pinterest|flyer|flyer-a4, place bottom|middle|top`):
  your exact words (first line = headline) on your photo or a plain color, with a real font, so
  no AI spelling mistakes.
- **Joe's screens in another language** (`TYPE: joe-language`, `OPTIONS: to <language>`): see
  "Joe's screens in other languages" above.

### Everyday paperwork tools (new in 2.2)

Nine tools for the jobs people usually pay a monthly fee for, or struggle to do alone. Same rules as the
rest: a card on the Tools tab, or just ask on Home ("join these PDFs", "explain this letter"). Your
files are only read, never changed; everything runs on your computer. Where the AI gives a number,
date or name, Joe's own code checks it against your file and marks anything it can't find **[CHECK]**.

- **PDF toolkit** (`TYPE: pdf-tools`, `OPTIONS: do merge|split|pages|rotate|compress|fill`, plus
  `turn right|left|upside`, `shrink safe|smaller`, `lock`): no AI. It uses **qpdf**, a small free
  program (Apache license) that System check installs with one click (winget, Homebrew or your Linux
  package manager; about 10 MB). What goes in the box (`FORMAT:`):
  - **Join**: nothing; drop the PDFs in the order you want them. You get `joined.pdf`.
  - **Pick or reorder pages**: the pages, like `3, 1, 2`, `1-4, 7`, `2 to 5 and last`, `odd`.
  - **Split**: empty = one file per page; `every 2`; or `1-3, 4-6` for those pieces.
  - **Turn pages**: empty = every page, or say which; pick the direction.
  - **Make it smaller**: "Nothing looks different" packs the file tighter without touching any
    picture; "Smaller" also re-saves photos as JPEG (scanned pages shrink a lot, a little softer). If
    the file can't get smaller, Joe says so and keeps nothing extra.
  - **Fill in a form**: run it once with the box empty. Joe saves `<name>-form-fields.txt` listing
    every field (with "tick box: yes or no" or the choices). Fill in after each colon, paste the
    lines into the box and run it again: you get `<name>-filled.pdf`. A field name Joe can't find,
    a choice that isn't on the list or a signature box is listed in `pdf-report.md`. Tick **Lock the
    filled form** for a final copy nobody can change. Letters outside the basic Latin set may not
    show in every PDF reader ([CHECK]).
  - A PDF locked with a password: open it in your PDF reader with the password, save or print a copy
    as PDF, and use that. A damaged file is named in the report.
- **Explain this letter** (`TYPE: explain-letter`, `OPTIONS: reply, calendar`): a bill, lease,
  insurance, benefits, tax, school or court letter (a document, or a photo of it with a vision
  model). You get `<name>-explained.md`: who it's from, what it's about, **dates and deadlines** with
  how many days are left (Joe counts them himself), money, who to contact and reference numbers
  (each checked against the letter), then what it means in plain words, what to do next and
  questions to ask. Common scam signs (gift cards, "pay today or else", a link to log in) are
  pointed out first. With `reply`, a polite draft to fill in (`<name>-reply.txt`); it never agrees to
  pay or admits anything unless you say so in the box. With `calendar`, the deadlines as an `.ics`
  file. Not legal or money advice: for anything serious, call the number on the letter or a free
  advice service.
- **Hide personal details** (`TYPE: hide-details`, `OPTIONS: names, style labels|blocks, key`):
  a cleaned copy to share. Joe's own patterns always find emails, phone numbers, card numbers (only
  real ones: they pass the card-number check), Social Security-style numbers, bank account (IBAN),
  account, policy, case and ID numbers, street addresses and birth dates. With `names` the writing
  model adds people's names and home addresses; Joe hides only words that are really in the text,
  never a guess. Labels keep it readable (`[NAME 1] called [NAME 2]`: the same person always gets
  the same label); blocks give ██████. In the box, type extra words to hide (one per line) and
  `keep: Acme Bakery` for words to leave. Word files come back as Word files with the formatting
  kept, and the author and reviewer names Word stores are blanked; text and CSV stay as they are;
  PDFs and web pages come back as plain text (blacking out a PDF by drawing boxes leaves the words
  underneath). `what-was-hidden.md` says how many of each were hidden, without the details. `key`
  saves `KEEP-PRIVATE-label-key.md` (which label stood for what): never share it. Joe can miss
  things: read the copy before you send it. For photos, use **Privacy blur**.
- **Meeting minutes** (`TYPE: meeting-minutes`, `OPTIONS: language <spoken in>, transcript, calendar`):
  a recording (or video) in, minutes out, in one step: Joe listens (like Transcribe), then writes a
  summary, decisions, a to-do table (what, who, by when), open questions and "who said what". Joe
  can't tell voices apart: a name is only given when the recording makes it clear (someone is
  called by name); names and dates that weren't heard word for word are marked [CHECK]. A
  transcript or subtitles file (`.txt`, `.srt`, `.vtt`, `.docx`) works too and needs no voice
  add-on. `calendar` puts the to-dos with a date in an `.ics` file.
- **Bank statement to budget** (`TYPE: bank-budget`, `OPTIONS: ai`): download your statement as CSV
  (or Excel) from your bank's website: one or more months, one or more accounts. Joe finds the date,
  description and amount columns himself (one Amount column, or Debit and Credit; US or day-first
  dates; `$1,234.56`, `(12.00)`, `1.234,56 €`). A transaction that's in two files is counted once.
  Well-known names are sorted by Joe; with `ai` the writing model sorts the rest **from the shop
  names only** (never your amounts or account numbers). All the math is Joe's: money in and out
  (transfers between your own accounts left out), spending by category and month, the biggest
  payments, and **regular payments** (the same amount on a weekly, monthly or yearly rhythm) with
  what they cost a year and any **price rise**. You get `budget.md` to read, plus
  `budget-transactions.csv` (change any category there) and `budget-by-category.csv` for a
  spreadsheet.
- **Resume tailor** (`TYPE: resume-tailor`, `OPTIONS: letter, word`): your resume plus the job
  posting (paste it in the box, or add it as a second file with "job" in its name). The writing
  model lists what the job asks for and finds each one in your resume; a match only counts when the
  quoted line is really in your resume. You get the tailored resume (your matching experience
  first, in the job's words), a cover letter (with `letter`) and `match-report.md` (every
  requirement: shown in your resume, with the quote, or not). **Nothing is invented**: any number or
  posting skill in the new resume or letter that isn't in your resume is marked
  `[CHECK: not in your resume]`, and the gaps are listed so you decide. `word` adds Word copies
  (needs Pandoc).
- **Mail merge** (`TYPE: mail-merge`, `OPTIONS: one, blank`): no AI. One letter (Word, `.txt` or
  `.md`) and one spreadsheet (CSV or Excel). In the letter, put a column name in curly brackets where
  it goes: `Dear {First name},` (also `{{Name}}`, `<<Name>>` or `«Name»`; letter case and spaces
  don't matter). Joe makes one letter per row in the `letters` folder (named like
  `001-ann-lee.docx`), keeping your Word formatting, headers and footers, plus `all-letters` with
  every one on its own page (`one`). An empty cell becomes `[CHECK: no Company]` so nothing goes out
  half-done (`blank` leaves it empty instead); a `{spot}` that matches no column is left and listed.
- **Picture descriptions (alt text)** (`TYPE: alt-text`, `OPTIONS: long, sidecar`): a short
  description of each picture for screen readers, websites and shop listings: one sentence, at most
  125 characters, most important thing first, never starting "image of". `long` adds 2-4 sentences
  of detail; `sidecar` a `.txt` per picture. People are never named or guessed at. Say what the
  pictures are for in the box ("product photos for my pottery shop"). Needs a vision model.
- **Duplicate photo finder** (`TYPE: duplicate-photos`, `OPTIONS: how exact|close|loose, sheets, copy`):
  no AI. Joe compares each photo's exact bytes and a tiny fingerprint of how it looks (with FFmpeg),
  so resized or re-saved copies are found too (`close`, the default); `loose` also groups burst
  shots. For each group he suggests a keeper (the biggest picture, then the sharpest, then the
  plainest name) and says why. **Nothing is moved or deleted**: `duplicates.md` lists the groups
  with a side-by-side picture of each (`sheets`), and `duplicates.csv` has every file. `copy` puts
  the keepers and every one-of-a-kind photo in a `keepers` folder (copies). Without FFmpeg only
  exact copies are found.

### Picture and sound tools

These five run in ComfyUI on the graphics card, using only ComfyUI's own built-in nodes (nothing
extra to install in ComfyUI, but it needs a recent version). Each needs a model pack once: the
Tools form shows a **DOWNLOAD IT** button with the size and license, and System check lists them
too. Packs come from Hugging Face into ComfyUI's models folders; restart ComfyUI afterwards.
Your originals are never changed; results go in `Output\<task name>\` with an `about.txt` naming
the models used.

```
TASK: Shop cutouts  TYPE: remove-bg        INPUT: tools/remove-bg     OPTIONS: background white, upscale 2x
TASK: Marble        TYPE: edit-picture     INPUT: mug.jpg             FORMAT: put the mug on a white marble counter
TASK: Old family    TYPE: restore-photo    INPUT: old-photos          OPTIONS: upscale 2x
TASK: Steam         TYPE: animate-photo    INPUT: mug.jpg             FORMAT: steam rising, slow push-in
TASK: Video music   TYPE: music            OPTIONS: kind music, length 60
FORMAT: calm acoustic guitar, warm | upbeat ukulele, cheerful
```

- **Remove background** (BiRefNet, MIT, under 1 GB): `background transparent` (PNG) or `white`
  (JPG, needs FFmpeg), `upscale none|2x|4x` (Real-ESRGAN x4, BSD-3, 70 MB; 2x is scaled down from
  4x for cleaner, smaller files), `keep all|main` (main subject only: drops smaller things the cut-out
  kept, like a brush lying next to a vase). A few seconds a photo.
- **Edit a picture by asking** (Qwen-Image-Edit 2511, Apache-2.0, about 31 GB with the 4-step
  Lightning add-on): FORMAT is the change, made to every picture. Medium/Low picture quality = 4
  steps (about 1-3 minutes on a 12 GB card, the rest of the model waits in normal memory); High =
  40 steps, much slower. Reads JPG, PNG and WebP.
- **Restore old photos**: `method true` (the default) is true to the photo: it undoes fading
  and the pink/orange cast of old prints, smooths grain, resizes (`upscale`) and sharpens a
  little, with FFmpeg only (`strength auto` by default: Joe measures how
  faded each photo is and picks strong, medium or light; you can pick one yourself). Then Joe takes a second look and uses the photo's own whites (sky, a white shirt, the print's border) as the guide, so they come out white instead of minty or yellow; greens are only nudged, so grass stays green. Nothing is redrawn, so faces stay exactly theirs. `method ai` uses
  the picture editor to also mend scratches, tears and date stamps (and `colorize` adds color),
  but it can make someone look like a different person: compare with the original.
  `sepia` (**Keep sepia tone**) is for brown-toned prints: the fixes above can turn them grey,
  so Joe restores the photo and then puts the warm tone back. Scanning tips: 300 dpi (600 for
  small prints), in color even for black-and-white photos, with the scanner's own auto-correct,
  auto-color and dust removal off, and the glass wiped clean.
  **AI repair keeps the real faces**: before the editor starts, the vision model finds the faces;
  afterwards Joe puts them back from a true-to-the-photo copy, so nobody turns into a stranger.
  Tick **Let AI repair redraw faces too** to skip that (with Add color it's skipped too).
- **Fix one spot**: add a picture, press **MARK THE SPOT**, paint over what to fix (a date stamp, a
  scratch, a stranger). Only the painted part is redrawn; the rest stays pixel for pixel. Leave
  the box empty to remove what's there, or say what goes there. The mark is saved next to the
  picture as `<name>-mask.png`.
- **Put pictures together**: 2 or 3 pictures plus how to combine them, called picture 1, 2 and 3
  in the order you added them.
- **Change the lighting**: golden hour, studio, soft window light, night, dramatic, candlelight or
  a cloudy day. Only the light and shadows change.
- **Redraw in a new style**: watercolor, oil painting, pencil sketch, anime, comic book, 3D cartoon,
  pixel art, stained glass, old photo or coloring page, or **Like my last picture** (the last picture
  you add is the style example for the others).
- **Change a picture a little or a lot**: say what it should look like and how much may change.
- **Make a picture wider or taller**: wider, taller, square or bigger all around. Your picture stays
  untouched in the middle and the AI paints the new parts around it.
- **Same character, new scenes**: one picture of a character plus one scene per line (or separated
  by ;). Same face, outfit and colors in every picture.
- **Character turnaround**: six views (front, three-quarter, sides, back) and a
  `character-sheet.png` with all of them side by side. `views quick` makes only front, side and back
  (about half the time); the plan shows how long it will take before it starts.

All of these use the Qwen picture editor that Edit a picture uses (offered once, about 31 GB).
On High quality, Joe's own pictures also get a second, 1.5x bigger detail pass.
- **Animate a photo**: Wan 2.2 5B image-to-video, 5 seconds, sized to the photo (landscape
  1280x704, portrait 704x1280, square 960x960). With the Turbo add-on about 2 minutes a clip.
- **Music and sound effects**: no files needed; one piece per line (in a mission, separate them
  with `|`). `kind music` = ACE-Step 1.5 Turbo (MIT, about 10 GB), instrumental, any style;
  `kind sfx` = Stable Audio Open 1.0 (about 5 GB, Stability AI Community License: free for people
  and businesses under US$1 million revenue a year), up to about 47 seconds. `length 10|30|60|120|180`.
  Saved as MP3.

**New model families** (each one offered once with its size and license; nothing downloads by
itself):
- **Sketch to picture**: add a drawing (a scan or phone photo of paper is fine) and say what it
  shows. `look auto|photo|illustration|anime|cartoon|painting|watercolor|render3d|fantasy|pixel|coloring`,
  `follow close|some|loose` (how strictly your lines are kept), `lines rough|clean`. Uses ControlNet
  Union SDXL ProMax (Apache-2.0, about 2.5 GB) with the SDXL picture model that suits the look; about
  30 seconds a picture. Needs an SDXL picture model.
- **Hidden-picture illusion**: write the scene; Joe hides `hidden spiral|circles|checker|waves|word|picture`
  in it. For a word add a line `word: JOE` (14 letters at most); for `picture` add a black-and-white
  shape or logo. `show hidden|clear|bold`, `versions 1|2|4` (each one looks different: keep the
  best). QR Code Monster SDXL (OpenRAIL++, about 5 GB). Needs an SDXL picture model.
- **Picture to 3D model**: one object or character, whole and centered, on a plain background works
  best. Joe pads it to a square on white and, when the background remover is installed, cuts the
  object out first. The result is a `.glb` shape (plain white, no colors) for Windows 3D Viewer,
  Blender, Unity, Unreal or a 3D printer's slicer. Hunyuan3D 2.1 (about 4.6 GB): Tencent's community
  license is free to use but does not apply in the European Union, the United Kingdom or South Korea.
- **Make shorts from a long video**: add a video where people talk (a podcast, a class, a stream,
  an interview). `count 3|5|8|12`, `length 30|45|60|90` (the most seconds per short; Joe aims for
  at least 40% of that), `crop face|center|fit` (face: the tall frame follows the speaker, found by
  the vision model; fit: the whole picture with blurred bars), `captions`, `title`, `posts`, and
  `language` like Transcribe. What Joe does: writes down every word with its time (whisper.cpp or
  the voice add-on), the writing model reads the transcript in pieces and picks moments that stand
  on their own, each pick is moved to whole words and the end of a sentence, then FFmpeg cuts
  1080x1920 clips with the captions burned in. `shorts.md` lists every clip with its times and why
  it was picked. Tips: clear sound matters more than the picture; tell Joe in the box what you want
  ("the funniest moments", "the best cooking tips"); always watch a clip before posting it, a moment
  can still need context.
- **Restyle a video**: add a video (and optionally one picture whose look to copy).
  `style anime|watercolor|oil|sketch|comic|cartoon|pixel|stained|vintage|coloring|own` (own = your
  words in the box), `length 5|10|20|30` seconds from the start, `follow close|loose`. Joe cuts
  5-second pieces, traces every frame's outlines, Wan 2.2 Fun Control 5B (Apache-2.0, about 10 GB
  when the video model is already there) paints the new look over them, then the pieces are joined
  and the original sound is put back. Slow: several minutes for every 5 seconds on a 12 GB card.
- **FLUX.2 [klein] 4B** (Apache-2.0, about 16 GB, Setup > Models > Pictures): a newer picture model
  that draws hands, faces and words far better, in 4 steps. When it's installed Joe uses it by
  himself for pictures with words in them ("a sign that says OPEN", "a poster with the title..."),
  when there's no SDXL model, or when a task says `MODEL: flux2`. To use it for every picture, pick
  it in Setup > Workflows > Pictures (or for one style only). Style add-ons (LoRAs) and the High
  quality second pass are for SDXL models, so they're skipped with it.

## Talking to Joe (F4)

Press **F4** to open Talk. The mic is open while that screen is up (MIC ON / MIC OFF button):
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
A chat is a whole session, not just Talk: what you asked for on the Home screen, Joe's plan,
each run that started (with its mission), and when it ends the results (every task, an
**OPEN** button for its folder, the pictures and videos it made, the report and the log).
Every time Joe opens you get a fresh chat and a clean screen; **+ NEW CHAT** does the same at
any time. A run that's still going stays on screen, and its results go into the chat it
started in. Click an old chat to read it (it opens on Talk), carry on where you left off (Joe
remembers what was said in it), or **RUN AGAIN** / **OPEN IN BUILDER** a mission from it. The **✕** next to a
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

### A voice to remember (optional)

With voice copy installed (above), Setup > Voice & Talk > **A VOICE TO REMEMBER** makes a voice from
a family recording of someone you miss: a phone video, a voicemail, an old home movie. Type their
name, pick the recording, and tick the three promises: you're family (or have the family's OK), it's
only for your family's own listening (never sold, posted or shared as if real), and it will never be
used to fool or pretend to be them to anyone. Joe takes the sound only, cleans it lightly, drops the
silences and keeps up to 25 seconds; a few clear seconds of them talking are enough.

Then use the tool **Hear it in a loved one's voice**: add a letter, a story or a note and type their
name. You get an MP3 plus "About this recording.txt" saying it was made by AI; Chatterbox also hides
an inaudible watermark in it. The voices live only in `%LOCALAPPDATA%\joe-ai\addons\voice\memory`
(on the drive for Portable Joe), never in backups or help files. DELETE removes one.

### Dropping files into Talk

Drag files onto Joe's window (or press ATTACH). They're copied to `Inbox\dropped\` and go with
your next message. Say "read it" to hear a file word for word, or ask anything about it.
Text, Markdown, CSV, JSON, Word (.docx), web pages and PDFs work (PDFs use the voice add-on's
Python; the PDF reader is added the first time). Pictures need a vision model in Ollama;
System check offers one that fits your graphics card.

A picture plus a request for work ("restore this photo", "remove the background", "colorize it",
"swap the sky for a sunset", "make it watercolor") goes straight to the right tool on exactly that
file: the plan shows under Joe's answer with RUN IT and OPEN IN BUILDER. No AI guesses at the plan,
so it can't pick the wrong file. A follow-up like "make it a new mission" right after means the same
picture. Questions about a picture ("what's in this?") go to the vision model.

Dropped on the Home screen, a file goes to Tools (F3) with every tool that can use it lit up: pick
what Joe should do. To ask Joe about a file instead, drop it on Talk (F4).

Spoken answers are kept to a few sentences; ask for detail ("explain in detail", "tell me more",
"walk me through it") and Joe says more. Some models "think out loud" in plain text; Joe spots it,
asks again with the thinking kept out of the answer, and remembers to do that for that model.

## Finished documents (EXPORT)

`EXPORT: docx, pdf, epub` on a writing task makes finished copies next to the .md when it's
done (also `odt`, `html`). In F7, P makes Word + PDF copies of any .md file. Needs Pandoc
(System check installs it); PDFs are printed by Microsoft Edge, so no LaTeX is needed.

**Templates** (Setup > Writing > TEMPLATES) decide how those copies look: page size, margins, body
and heading fonts, text size, line spacing, first-line indent, alignment, space between paragraphs,
centered headings, each chapter on a new page, and a title page. Joe's built-in ones:

| TEMPLATE | For | Joe's choices |
|---|---|---|
| `standard` | everyday documents (Word, PDF, web page by default) | Letter, 1 in, Georgia 12, 1.4 lines |
| `book` | a printed novel | 6 x 9 in, Garamond 11.5, justified, indents, chapters on new pages, title page |
| `manuscript` | sending to an editor or agent | Letter, 1 in, Times New Roman 12, double spaced, 0.5 in indents |
| `kids` | a children's picture book | 8.5 x 8.5 in square, big friendly letters (18 pt), centered, a new page per part, a picture on each page (up to 45% of it) |
| `ebook` | EPUB (the default for .epub) | light styling, since e-readers use their own settings |
| `report` | business reports | Calibri 11, block paragraphs |
| `largeprint` | older readers, low vision | Atkinson Hyperlegible 18, 1.5 lines, page numbers |
| `poetry` | poems, a chapbook | 5.5 x 8.5 in, every line kept as written, one poem per page |
| `screenplay` | scripts | Courier 12, 1.5 in left margin, scene headings, character names and dialogue set in, page numbers top right |
| `letter` | letters, cover letters | no printed title, block paragraphs |
| `resume` | a resume | compact, tight spacing, a line under each section heading, no printed title |
| `cookbook` | recipes | 7 x 10 in, one recipe per page, big pictures, page numbers |
| `recipecard` | recipe cards | 5 x 7 in (change to 4 x 6 for index cards), one recipe per card |
| `coloring` | coloring and activity books | one big picture per page, small caption |
| `school` | school papers (MLA) | Times 12, double spaced, last name + page number top right (put your name in Header text) |
| `sheet` | Excel copies of a spreadsheet (`EXPORT: xlsx` on a .csv task) | bold blue header that stays in place, filter buttons, fitted columns |
| `pricelist` | price lists, inventory (.xlsx) | money columns as $1,234.50, a totals row with real formulas, striped rows |

Settings in every document template: page size (now also 7 x 10, 5 x 7 and 4 x 6), margins, an
**extra inside margin for binding** and **mirror margins** (printed books), fonts, size, spacing,
indents, alignment, centered headings, a **line under section headings**, **new pages** at
chapters (#) or at every section (##), **print the title** on/off, title page, **page numbers**
(bottom middle, bottom outside corner, or top right with the **header text**: `{title}` = the
document's title), a **big first letter** in each chapter (PDF/EPUB/web), **keep line breaks as
written** (poems), **screenplay layout**, and **pictures fill the page**. Spreadsheet templates also
have **money columns** (auto = columns named price, cost, total, amount...), the **money sign**, and
a **totals row**. Word copies use the first font in the list that nearly every PC has (Garamond,
Georgia, Verdana, Courier New...), so they look right on other computers too. Screenplays: write
scene headings (INT./EXT.), character names in capitals on their own line and dialogue under them;
Joe sets each part where scripts put it, in Word too (styles Scene Heading, Character, Dialogue...).

Each is shown filled in; EDIT unlocks it and RESET THIS TEMPLATE brings Joe's back. Pick which one
each kind of file uses by default at the top, or put `TEMPLATE: book` (or kids, manuscript, ebook,
report) on a task.

**Picture books with pictures**: add a pictures task right after the story with
`FROM: <the story task's name>` (one picture per page, made from that page's words). When the
pictures are done, Joe makes the book's copies again with each picture on its page. Name the story
task with the book's own title (a name like "Kids picture book" gets the first page's title instead).
Asking for "a picture book about..." in plain words plans both tasks for you.

**Your own templates**: missing one (a church bulletin, a newsletter, your company's report style)?
At the bottom of the list, **ADD YOUR OWN TEMPLATE**: give it a name, pick the closest of Joe's to
start from, and Joe copies it (with any changes you made to that one). EDIT changes anything,
RESET THIS TEMPLATE takes it back to where it started, DELETE removes it. A task uses it with
`TEMPLATE:` and its name (`TEMPLATE: church bulletin`, or its id `my-church-bulletin`), and it can be
the default for a kind of file. Your templates are saved in your settings (up to 50); Joe's own are
never changed, and ASK A BIGGER AI tells the chatbot their names. Word copies get the template through a "reference document" Joe builds from
Pandoc's own; PDF, EPUB and web pages through a style sheet. A font must be on the computer that
opens the file; list a few (comma-separated) and the first one there is used (Word uses the first).

`EXPORT: social` on a list of posts (also on a `.csv` task) adds three files for posting tools:
`<name>-social.csv` (one row per post: the text, how long it is, which sites it fits, and empty
date/time/site/media columns to fill in), `<name>-social.json`, and `<name>-postiz.txt` (ready
command lines for Postiz's free `postiz` helper: put in your channel id and date). Mixpost or a
spreadsheet: copy from the CSV. Joe never posts by himself and never asks for your accounts.


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

**ComfyUI Desktop waits on its start screen?** Joe opens ComfyUI by himself, but ComfyUI
Desktop can stop on its start screen (the list of installs, or "New / GitHub / Cloud") and
wait for a click while Joe waits too. Set it once: ComfyUI menu (☰, top left) > **Desktop
Settings** > **Auto-launch on startup** > pick your install (not "None (show dashboard)").

**Video without a workflow file:** System check offers Wan 2.2 5B (Apache 2.0, about 18 GB,
needs an 8 GB+ graphics card). After it downloads, restart ComfyUI once. Then
`TASK: Shop tour  SAVE: clips/tour.mp4` (or `TYPE: video`) makes about 5-second 1280 x 704
clips at 24 fps, one per prompt. `SIZE` changes the size; `FPS` the speed.

For Flux, other video models or anything fancy, build it in ComfyUI, then
**Workflow → Export (API)** and drop the file in `Workflows\`. Joe finds the prompt box, seed, size, model and save node by
itself, or you can type `{{PROMPT}}`, `{{NEGATIVE}}`, `{{SEED}}`, `{{WIDTH}}`, `{{HEIGHT}}`
into the workflow before exporting. With your own video workflow, frames or GIFs are
turned into MP4 with FFmpeg (`FPS: 16`).

Or skip the copying: Setup > Images & video > **Your own workflows** > pick the exported file >
**IMPORT WORKFLOW**. Joe checks it's in API format and saves it to `Workflows\`. Give it a picture
style and Joe uses it for every picture in that style (`Workflows\style-<style>.json`); leave the
style blank to pick it per task with `WORKFLOW:`.

Each folder gets `_prompts.md` and `_media.json` (prompt, seed, model, review marks).
These are AI pictures: never present them as photos of real products.

## Storage (F9)

F9 shows how much room each folder takes, the disk's free space, and five CLEAN buttons
(each asks first and moves files to the Recycle Bin): pictures you marked X, old `_v2`/`_v3`
versions (the newest is kept, and picture folders with a K or S mark are never touched),
reports older than 30 days, leftover ComfyUI copies, and past missions (the saved plans in the
Step by step list; what they made stays in Output). Logs trim themselves at 2 MB.
ComfyUI keeps its own copy of every picture; Joe removes it once he has saved his
(Setup > Images & video, on by default). Only ComfyUI's `output\Joe` folder is ever touched.

Keys are UPPERCASE and must start a line or follow two spaces, so prose such as
"Note: …" inside a value is left alone. Values can span several lines.

## Running it

The installers bring everything Joe needs to start. Running from the source code instead needs
Python 3.11.4+ (python.org). For writing, Joe needs Ollama with a model (System check offers to
install both) or another writing program you already use (see "Use the programs and models you
already have").

**Double-click `Joe.pyw`.** A window opens (Microsoft Edge in app mode, no
tabs). Paste a mission, press **F5**. You can close the window; the run keeps going.
Double-click again to check on it. F1 shows all keys.

| Key | Screen |
|---|---|
| F1 | Help |
| F2 | Home: the box for plans and questions, progress, log (R = morning report, C there copies it) |
| F3 | Tools: ready-made jobs for your own files, pictures, sound and video |
| F4 | Talk: talk or type to Joe, drop a file to ask about it |
| F6 | Step by step: make a plan with simple forms |
| F7 | Files: arrows, Enter, Backspace; O = Explorer, E = Notepad, C = copy path; T = thumbnails, K/X/S = keep/reject/star, M = make MP4 |
| F5 | Run / stop |
| F8 | Report: what finished and what needs a look |
| F9 | Stats and storage: space used, clean-up buttons |
| (Help) | ABOUT JOE: the story, privacy and license |
| F10 | Setup: a side menu with System check, General, Writing, Images & video, Voice & Talk, Display & sound, Privacy, Stats & costs, plus a find box |

The status bar shows the GPU live: temperature, load, memory, power and fan (hover it for the
CPU load too). It flashes
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
python -m joeai mcp                  # Joe as an MCP connector on stdin/stdout
python -m joeai tonight              # start the plans saved for tonight (what the night shift runs)
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

## Updates and getting help

Release signing: every release's `SHA256SUMS.txt` (the checksum of each download) can also be signed
with the maker's private key (`SHA256SUMS.txt.sig`, Ed25519). Joe has the public key built in
(`SIGN_PUBLIC_KEY` in `joeai/__init__.py`) and refuses an update whose list isn't signed by it, so a
changed release can't slip through even if both the file and its checksum were swapped. The maker sets
it up once: `python installer/make_signing_key.py`, the private line goes into the GitHub secret
`JOE_SIGNING_KEY` (never anywhere else), the public line into `SIGN_PUBLIC_KEY`. Until then, updates are
checked against the checksums only. The signed list also names its version (`# joe-ai version X`), and
Joe refuses one whose version isn't the release being offered or isn't newer than his own, so an old
signed release can't be passed off as a new one.


**CHECK FOR UPDATES** (Setup > System check) asks GitHub for the newest release; Joe also checks when he
opens unless that's off. When Joe was installed with an installer, an update is one click: he
downloads the installer for your system, checks it against the release's `SHA256SUMS.txt` (and
refuses it if the checksum is missing or wrong), then on Windows runs it quietly and opens again,
on a Mac opens it for you to drag onto Applications, and on Linux swaps the AppImage and restarts.
Not while a run is going. A copy run from source (git) just gets the release page.

**MAKE A HELP FILE** (Setup > System check) saves `Joe-help-<date>.zip` in Output and shows it: Joe's
version and install type, the system and graphics, System check's findings, settings with every
key, topic and password hidden, and the last part of each log. Your home folder and user name
become `~` and `<user>`. It never holds your Inbox/Output files, chats, recordings or voices. Logs
can mention task and file names, so look inside before sending it.
