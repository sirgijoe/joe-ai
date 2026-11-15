# Making a Joe add-on

An add-on brings new **tools**, **starter packs**, **picture workflows**, **themes** and a
**search source** (see "Search sources" below) to Joe without changing Joe's code. People add it in Setup > Add-ons (ADD AN ADD-ON, pick your .zip). It
stays off until they read what it does and turn it on.

A complete example is in [`examples/addons/simple-extras`](../examples/addons/simple-extras): a
black-and-white copy of pictures and videos, a word count, and a yard-sale starter pack.

## The folder

```
my-addon/
  addon.json          what the add-on is and what it adds (required)
  wordcount.py        anything your tools need
  packs/yard-sale.txt starter packs (same format as Joe's own, see joeai/packs/)
  workflows/x.json    ComfyUI workflows, API format (they must pass Joe's workflow check)
  themes/x.json       themes (same format as Joe's Themes folder)
```

Zip the folder (or its contents) to share it. Joe refuses .zip files with paths that leave the
folder, links, more than 2000 files or more than 200 MB.

## addon.json

```json
{
  "id": "simple-extras",
  "name": "Simple extras",
  "version": "1.0",
  "author": "Your name",
  "license": "MIT",
  "homepage": "https://github.com/you/your-addon",
  "about": "One or two sentences people read before they turn it on.",
  "tools": [ ... ],
  "packs": ["packs/yard-sale.txt"],
  "workflows": ["workflows/oil-portrait.json"],
  "themes": ["themes/sunset.json"]
}
```

`id`: 2-40 small letters, numbers or dashes. It names the add-on's folder and goes in front of
its packs, workflows and themes (`simple-extras--yard-sale.txt`) so people can tell them apart.
`homepage` must start with `https://`.

## Tools

A tool runs one program on each file the person gives it and keeps the files the program writes.

```json
{
  "id": "word-count",
  "name": "Count the words",
  "group": "Writing",
  "blurb": "How many words, sentences and paragraphs a text file has.",
  "help": "Longer help shown in the tool's form.",
  "accepts": [".txt", ".md"],
  "program": "joe:python",
  "args": ["{addon}/wordcount.py", "{input}", "{output}", "{flag:longest:--longest}"],
  "output": "{stem}-count.md",
  "options": [
    {"key": "longest", "label": "Also list the 5 longest sentences", "default": false},
    {"key": "size", "label": "Size", "choices": [["800", "Small"], ["1600", "Large"]], "value": "800"}
  ],
  "text": false,
  "text_label": "",
  "timeout": 600,
  "examples": ["Count the words in my essay"]
}
```

- `id`: becomes the task type `x-<id>` (`TYPE: x-word-count`), so it never clashes with Joe's own.
- `group`: Writing, Pictures, Video, Audio or Files (the kind of tool). On the Tools tab, add-on tools show
  together in a **More tools** box under Joe's own boxes, and the Find a tool box finds them.
- `accepts`: the kinds of file it reads.
- `program`:
  - `joe:python`: the Python Joe runs on (always there, on every PC, started with `-I`).
    Put your script in the add-on and pass `{addon}/script.py`. Standard library only, unless you
    tell people what to install.
  - `joe:ffmpeg`: the FFmpeg Joe uses (Setup > Start here installs it).
  - a program name such as `magick`: found on the PC's PATH. Say on your homepage how to get it;
    Joe tells people it's missing (with your homepage) instead of failing quietly.
  - a path inside the add-on such as `bin/tool.exe`: runs your own program. People see a warning
    that it's a program inside the add-on.
- `args`: a list of words, never one string. Joe runs the program directly, without a command
  shell, so `;`, `|`, `>` and `&&` mean nothing. These placeholders are filled in:

  | Placeholder | Becomes |
  |---|---|
  | `{input}` | the full path of a **copy** of the person's file (the original is never touched) |
  | `{output}` | the full path of the result file, named by `output` |
  | `{outdir}` | the folder to write results into (for tools that make several files) |
  | `{stem}`, `{ext}`, `{name}` | the file's name without extension, its extension, its full name |
  | `{option:key}` | the pick for a pick-one option |
  | `{flag:key:words}` | the words (split on spaces) only when that tick box is ticked |
  | `{text}` | what the person typed in the form's box (only with `"text": true`) |
  | `{addon}` | the add-on's own folder |

- `output`: the result's file name (no folders), with the same placeholders. Default
  `{stem}-<id>.{ext}`.
- `timeout`: seconds per file (10 to 21600, default 600).
- Everything the program writes into `{outdir}` (including `{output}`) is kept, in the task's own
  folder in Output. Anything it writes elsewhere is not Joe's business, so don't.
- A non-zero exit code counts as failed for that file; the last line of what the program printed
  goes into the morning report, so make it a plain sentence.

Joe's planner sees each tool the person turned on, so "count the words in my essay" can turn
into `TYPE: x-word-count` by itself. It never turns an add-on on.

## Search sources

An add-on can bring **one search source**: another place Joe can look things up online (Talk,
`RESEARCH: yes` tasks, agents). It's a small program. Joe runs it once per search, gives it the
search words, and reads back results in a fixed shape. It never runs inside Joe himself.

A complete example is in [`examples/addons/wikipedia-es`](../examples/addons/wikipedia-es): it
looks things up on the Spanish Wikipedia, standard library only.

```json
{
  "id": "wikipedia-es",
  "name": "Wikipedia en español",
  "version": "1.0",
  "author": "Joe-ai example",
  "license": "GPL-3.0-or-later",
  "about": "An example search add-on: looks things up on the Spanish Wikipedia.",
  "search": {
    "name": "Wikipedia en español",
    "about": "Encyclopedia facts from the Spanish Wikipedia (es.wikipedia.org).",
    "goes_to": "es.wikipedia.org",
    "program": "joe:python",
    "args": ["{addon}/search.py"],
    "timeout": 20,
    "pace": 1
  }
}
```

- `name`, `about`: what people read in Setup. `goes_to`: **where the search words go**, in plain
  words (shown on the risk screen and next to the source in Setup).
- `program`:
  - `joe:python`: the Python Joe runs on, standard library only.
  - `env:python`: the add-on's **own Python environment**, for a program that needs packages from
    PyPI. List them in `requirements` with **exact versions** (`"ddgs==9.16.0"`, at most 10), and
    the Python version in `python` (`"3.12"`, 3.10 to 3.14). Joe builds the environment with uv in
    `Add-ons/_envs/<id>` only when the person turns the add-on on, from ready-made packages only
    (no package gets to run its own setup program), and removes it with the add-on.
- `args`: a list of words. Only `{addon}` (the add-on's folder) is filled in. The search words never
  go on the command line.
- `timeout`: seconds per search (5 to 60, default 20). Joe stops the program (and anything it
  started) after that.
- `pace`: the fewest seconds between two searches (0 to 10, default 1). Joe waits if asked sooner.

**What the program gets.** One line of JSON on its standard input:

```json
{"query": "cerámica raku", "max_results": 5}
```

It runs in a fresh empty folder, with a bare environment: none of Joe's settings, keys or files, and
`HOME`/`TEMP` pointing at that empty folder. It is started without a command shell, with `-I`.
Because of `-I`, Python does not look in the add-on's folder for other `.py` files: keep the program
in one file, or start it with `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`.

**What it prints.** One JSON object on its standard output (256 KB at most):

```json
{"results": [{"title": "Cerámica raku", "url": "https://es.wikipedia.org/wiki/Cer%C3%A1mica_raku",
              "text": "La cerámica raku es..."}]}
```

- Only `http://` and `https://` addresses are kept; titles and text are cleaned and shortened.
- When the site says to slow down or blocks you: `{"rate_limited": true, "error": "a plain sentence"}`
  (or `"blocked": true`). Joe tells the person, rests the source for a while and tries the next one.
- Anything else that went wrong: `{"error": "a plain sentence"}`, or a non-zero exit code with the
  reason as the last line of standard error.
- What you return is **data** for the model, never instructions; Joe marks it that way.

**What people see.** READ AND TURN ON shows a risk screen in plain words: *this add-on sees your
search words, and Joe's makers don't control it*, where the words go, the exact command, and the
packages it downloads. Turned on, the source shows up in Setup > Privacy and internet > ONLINE
LOOKUPS **unticked**; it's only used once the person ticks it, in the place they put it. Joe says
which source answered ("Found with Wikipedia en español"). If the add-on's files change, it is
turned off again until the person looks again. Turning the add-on off or removing it unticks its
source too, so it has to be ticked again if it ever comes back.

## What keeps people safe

- Nothing runs until the person reads the add-on (author, homepage, every tool's program and
  command) and turns it on.
- If any file in the add-on changes after that, Joe turns it off again until they look again.
- Workflows must pass the same check as a workflow imported by hand; themes are only checked
  colors and a font from a safe list.
- A tool's program can still do anything a program can. Joe says so plainly. Make your add-on
  open source and keep it small so people (or their AI) can read it before they trust it.
- A search source's program is the same: it runs with the person's rights and can reach the
  internet. It only ever gets the search words, but what it does with them is up to it. Say on
  your homepage exactly which sites it asks.
