# Joe security review checklist

A guide for an outside reviewer. Joe is a desktop app: a Python program (standard library only)
that runs a small web server on the user's own PC, shows its window in a browser view, and drives
other programs (Ollama, ComfyUI, FFmpeg, a private Python for voice). Nothing here is a cloud
service, but Joe does download things, start programs and accept plans written by other AIs, so
those are the places to look hardest.

How to run it: `python Joe.pyw` (or `python -m joeai`), tests with `python -m pytest -q`
(`tests/conftest.py` sets `JOE_OFFLINE=1`, so tests never touch the network).

Please note each finding as **file:line, what can happen, who can trigger it**, and open an issue
(or a private message if it's serious).

## Who could attack Joe (threat model)

| Who | How they reach Joe | Main worry |
|---|---|---|
| A web page in the user's normal browser | `http://127.0.0.1:<port>` | Calling Joe's API (CSRF, DNS rebinding) |
| Another program or user on the same PC | The local port, Joe's files | Reading results, queueing work |
| A chatbot answer ("ASK A BIGGER AI") or an MCP app | The mission text it writes | Paths outside the workspace, running programs, huge jobs |
| A file the user drops in the Inbox | The tools that read it | Zip/docx/xlsx tricks, huge files, model files that run code |
| A download source (GitHub, Hugging Face, PyPI, Ollama) | Joe's installers and updates | A swapped or tampered file |

## 1. The local web server (`joeai/server.py`)

- [ ] Binds to `127.0.0.1` only, never `0.0.0.0` (search `ThreadingHTTPServer`).
- [ ] `_host_ok()`: only `Host: 127.0.0.1` or `localhost` is answered (DNS rebinding). Is it applied
      to every route, including `/raw`, `/player`, `/mcp` and the static files?
- [ ] `_authed()`: every `/api/*` call needs the per-launch token (`secrets.token_urlsafe(24)`,
      compared with `compare_digest`). The token is NOT in the page (anything on the PC can fetch
      `/`): Joe's window gets it in the address's `#t=` part (`app.py`), keeps it in
      sessionStorage, and it is accepted as `?t=` only on `/raw` and `/player`. Can it leak through `Referer` headers,
      logs or the help zip (`support.py` scrubs it)?
- [ ] `/mcp` over HTTP skips the window token and needs `Authorization: Bearer <settings.mcp_key>`
      instead (`_mcp_http()`, `compare_digest`). The key is made once and shown in Setup.
- [ ] Request bodies are capped at 2 MB (`_body()`); voice uploads and `/api/restore` read raw
      bodies: check their limits.
- [ ] `/raw` and `/player` go through `app.rel_path()` -> `Sandbox.check()`: is anything outside
      the workspace reachable (symlinks, junctions, `\\?\` paths, 8.3 short names, case tricks on
      Windows)?
- [ ] The API can change settings, including `comfy.start_command` (a program Joe will start).
      That's by design, behind the token, but worth confirming that nothing unauthenticated
      reaches it.

## 2. The workspace sandbox (`joeai/sandbox.py`)

- [ ] `Sandbox.resolve()` rejects absolute paths, drive letters, `..`, reserved device names
      (CON, NUL, ...), bad characters and anything that lands outside after resolving symlinks.
- [ ] Every SAVE / INPUT / FROM path from a mission goes through it (`mission.py`, `engine.py`,
      `tools.py`). Look for any path built with `/` or `os.path.join` that skips it.
- [ ] Results are written "fresh" (`_v2`, `_v3` names) and never overwrite the user's own files.

## 3. Plans from other AIs (`joeai/bigger.py`, `joeai/mission.py`, `joeai/mcp.py`)

- [ ] A pasted answer is only parsed as data: no `eval`, no template execution, no shell.
- [ ] `bigger.tidy()` rewrites keys; can it produce a key or value the checker would have refused?
- [ ] Size limits: very large CHUNKS, VARIANTS, video counts or file lists (disk-space check is
      `system.room_problem`; is there an upper bound on work?).
- [ ] MCP (`mcp.py`): which tools can an MCP app call (queue, run tools on Inbox files, read
      Output files, stop)? `_inside_output()` must keep reads inside Output.
- [ ] `connect.py` edits other apps' config files (Claude Desktop and others): it keeps a copy
      of the old file and only touches Joe's own entry. Check the JSON merge and the backup.

## 4. Downloads and installs (`addons.py`, `doctor.py`, `picturetools.py`, `whispercpp.py`, `update.py`, `upkeep.py`)

- [ ] Every download is HTTPS from a fixed host (GitHub releases, Hugging Face, PyPI/PyTorch
      index, the Ollama registry). No URL comes from a mission or a chatbot.
- [ ] **Joe's own updates** (`update.py`): `download()` refuses a file without a matching line in
      `SHA256SUMS.txt`; `sign.py` (pure-Python Ed25519) verifies that file once
      `joeai.SIGN_PUBLIC_KEY` is set (it is, since 2.1): an update without a matching
      signature is refused. The signature covers the checksum list, not the version number
      (an old signed release could be offered again). Windows Authenticode isn't done yet.
- [ ] **Third-party files are not pinned:** uv, whisper.cpp and some others use `releases/latest`;
      the Kokoro voice files and the picture/video model packs are fetched by URL without a
      fixed hash. Is pinning a version + SHA-256 worth it (at the cost of manual bumps)?
- [ ] Archives: `zipfile.extractall` in `whispercpp.py`, `portable.py`, `upkeep.py`, `addons.py`
      (Python strips `..` and drive letters, but check for zip bombs / huge files);
      `tarfile.extractall(..., filter="data")` in `portable.py` (needs Python 3.11.4+, which
      `pyproject.toml` and `Joe.pyw` require).
- [ ] Every install asks first (`approved=True` is only passed after a click). Check that no
      route starts an install without it.

## 5. Starting other programs (`services.py`, `system.py`, `addons.py`, `update.py`, `app.py`)

- [ ] No `shell=True` for anything Joe builds himself: commands are argument lists. The one
      exception is a start line the person typed in Setup (`comfy.start_command`,
      `ollama.engine_start`): `system.popen_detached` runs a text command through the shell, as
      typed. Those two settings can't come from a mission, the phone, MCP or a restored backup.
- [ ] `comfy.start_command` and the Ollama path come from settings or the program finder
      (`finder.py`): could a file in a world-writable folder be picked up as "ComfyUI"?
- [ ] The voice helpers run as `python -I` (isolated) in their own private environment.
- [ ] `update.launch()` runs the downloaded installer silently: only after the checksum check.
- [ ] Ollama / ComfyUI are set to lower priority during long runs; nothing is run as admin.

## 6. Files the user gives Joe (`tools.py`, `sheets.py`, `doctemplates.py`, `comfy.py`, `modelcheck.py`)

- [ ] .xlsx is read with `zipfile` + `xml.etree.ElementTree` (`sheets.py`); .docx text is pulled
      out with regexes after a size check (`attach._docx_text`, 200 MB cap). ElementTree doesn't fetch external entities, but entity expansion
      ("billion laughs") and huge unzipped sizes are worth a look.
- [ ] PDFs, audio and video go to FFmpeg / other tools: Joe passes them as arguments, not shell
      text.
- [ ] Model files: `.ckpt/.pt/.pth/.bin` can run code when loaded; Joe prefers `.safetensors`
      (`comfy.is_pickle`) and `modelcheck.py` reads `.safetensors` headers without loading them.
      Should Joe warn (or refuse) when only a pickle file is available?

## 7. Secrets and privacy (`config.py`, `support.py`, `backup.py`, `websearch.py`)

- [ ] API keys (web search, MCP key) live in the settings file in the user's config folder.
      Back-ups include them only when the user ticks the box.
- [ ] MAKE A HELP FILE (`support.py`) scrubs keys, tokens, the home folder and the user name.
      Try to get one of them through.
- [ ] Online lookups (`websearch.py`) send only the search words; what leaves the PC is listed in
      the README's internet table. Check nothing else is sent (no file content, no user name).
- [ ] No telemetry: `HF_HUB_DISABLE_TELEMETRY=1` for the voice helpers. Background internet use
      is the update check (GitHub API), the weekly model-list check (GitHub) and model-update
      checks against the Ollama registry (`upkeep.py`), all listed in the README. Confirm nothing
      else leaves the PC.

## 8. Release and supply chain (`.github/workflows/`, `installer/`)

- [ ] CI builds the installers, runs the tests, does a silent install + start/ping/quit smoke
      test, and publishes `SHA256SUMS.txt`.
- [ ] Generate the signing key (`installer/make_signing_key.py`), keep the private key off GitHub
      (a repository secret for `release.yml`), put the public key in `joeai.SIGN_PUBLIC_KEY`.
- [ ] GitHub Actions: pin third-party actions to a commit SHA, least-privilege `permissions:`.

## Already in place (for context)

Local-only server, Host check, per-launch token, workspace sandbox with tests, ask-first installs,
checksum-checked self-updates, `tar` data filter, `.safetensors` preferred, isolated voice
Python, no `shell=True`, help-file scrubbing, tests that run offline.
