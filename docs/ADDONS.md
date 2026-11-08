# Making a Joe add-on

An add-on brings new **tools**, **starter packs**, **picture workflows** and **themes** to Joe
without changing Joe's code. People add it in Setup > Add-ons (ADD AN ADD-ON, pick your .zip). It
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
- `group`: Writing, Pictures, Video, Audio or Files (where the card sits on the Tools tab).
- `accepts`: the kinds of file it reads.
- `program`:
  - `joe:python`: the Python Joe runs on (always there, on every PC, started with `-I`).
    Put your script in the add-on and pass `{addon}/script.py`. Standard library only, unless you
    tell people what to install.
  - `joe:ffmpeg`: the FFmpeg Joe uses (System check installs it).
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

## What keeps people safe

- Nothing runs until the person reads the add-on (author, homepage, every tool's program and
  command) and turns it on.
- If any file in the add-on changes after that, Joe turns it off again until they look again.
- Workflows must pass the same check as a workflow imported by hand; themes are only checked
  colors and a font from a safe list.
- A tool's program can still do anything a program can. Joe says so plainly. Make your add-on
  open source and keep it small so people (or their AI) can read it before they trust it.
