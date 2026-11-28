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
      Output files, stop)? Two kinds of reads, with different reach:
      - `joe_read_file` (and `joe_list_files`): Output only, through `_inside_output()`, never a
        folder whose name starts with a dot (`Output/.joe` = chats and run state); text types only;
        at most 200,000 characters (`MAX_READ`).
      - `joe_shrink` / `joe_summarize` (`_shrink_source`): Output only while `Settings.mcp_folders`
        is off (the default; checked on the resolved path, so a link in Output to the Inbox is
        refused too, before any model is asked). When the person ticks Setup > Other AI apps > "Apps
        connected to Joe may read my Inbox and other folders", also Inbox, Projects, Missions,
        Workflows and Themes (`Sandbox.resolve`, so the person's own dropped files in Inbox are
        readable). The setting changes only through the window's `/api/settings` route (window
        token); the phone, the connector and missions have no way to set it, and Setup > Reset turns
        it off. Never a folder whose name starts with a dot
        (`check_not_private`); text types only (`SHRINK_EXT`); `joe_shrink` returns at most
        20,000 characters a call whatever `max_chars` says (`MAX_SHRINK`). `joe_summarize` sends
        the shrunk text only to Joe's model server when it is on this PC (`shrink.is_local`), and
        returns the answer with the line numbers it came from.
      - NOT YET REVIEWED (added 2026-11-27, wants a fresh-chat review before release):
        `joe_count_tokens` (`Joe.count_tokens`, `tokens.py`). Same reach as `joe_shrink`
        (`_allowed_path`: Output only while `mcp_folders` is off, checked on the resolved path before
        the model is asked anything; never a dot folder), with two differences: any file that isn't
        binary counts (no `SHRINK_EXT` list, so `.hua`, `.rs` and the like work), and a folder path
        counts every file under it (each one checked again with `Sandbox.check` and
        `check_not_private`, so a link leading outside is skipped). Only numbers and the file names
        asked for come back, never file text. The text goes only to the writing program when it is
        on this PC (`shrink.is_local`), with nothing written (`num_predict` 0, or a tokenizer
        call). Caps: 200 files, 5,000,000 characters, 5,000 lines a call. To check: can the counts
        of chosen pieces leak a closed file's content (no: a closed path raises before any count),
        and can a huge `texts` list tie up the model (bounded by the character cap).
        Added 2026-11-27 10:15, NOT YET REVIEWED: `project=` lets it count files inside a listed dev project
        (`Joe._project_files`): Dev tools must be on and the project listed; the path is inside that folder
        by realpath (no `..`, no full path, no link out) and never in a dot folder (`.git`); numbers only.
      - REVIEWED ONCE 2026-11-27 by a fresh agent that hadn't seen it built (findings and what was done about
        each are at the end of this item); the fixes themselves are new code and want a second look, and the
        Windows behaviour is reasoned, not tested. **Dev tools**
        (`Settings.dev_tools`, off by default; `Settings.dev_projects`; `devprojects.py`,
        `repostatus.py`, `pcstatus.py`; connector tools `joe_run_command`, `joe_repo`, `joe_computer`,
        hidden from `tools/list` while off and answering `devprojects.OFF` if called anyway). This is the
        first connector path that runs a program outside Joe's own tools and reads folders outside his
        workspace, so it wants the hardest look.
        - Who can change the switch or the list: only `/api/settings` with the window token
          (`test_only_the_window_can_turn_it_on_or_change_the_list`); no connector tool takes either;
          a connector an app started re-reads the settings file on every call (`Joe._dev`). Setup >
          Reset turns the switch off and keeps the list.
        - `joe_run_command`: reads two strings (project, command) and nothing else from the app; both
          must equal a listed name after trimming and lower-casing (`devprojects.said`, so "../tests"
          and "tests --x" match nothing). The command line is the person's own text, started with
          `subprocess.Popen` and no shell (Windows: the string as typed to CreateProcess; elsewhere
          `shlex.split`), `cwd` the listed folder (must be a full path to a real folder), stdin closed,
          one at a time (`Output/dev/_running.txt`), ended with its whole process tree at the person's
          time limit, at 20 MB of output, or when STOP is pressed (see "Always viewable" below). To check: a `.bat`/`.cmd` target on Windows goes through
          cmd.exe by Windows' own rule; `shell_words` only warns about `| > &&`, it doesn't block.
        - `joe_repo`: the folder is a listed project's; the bundle must resolve inside that folder or
          Joe's Inbox (`Joe._bundle_path`, realpath check, so a link out is refused); `pull` acts only
          on a real JSON true. `repostatus._git`: argv only, hooks/fsmonitor/pager/credential helper/
          local filters switched off per call, `GIT_ALLOW_PROTOCOL=file`, read-only calls take no
          locks; pull is `fetch` from the bundle file then `merge --ff-only <checked commit>`, refused on
          uncommitted changes. Known gaps (from the build): `hook.<name>.command` config hooks in very
          new git and `core.alternateRefsCommand` are not overridden; global/system filters (Git LFS)
          still run by design.
        - Always viewable (2026-11-28, the owner's rule "there will never be anything done on Joe that isn't
          viewable"): `joe_run_command` and `joe_repo pull=true` first check that Joe's window is open
          (`mcp._window_open`) and otherwise start Joe the way he normally starts (`mcp._open_joe`: this
          Python with `Joe.pyw`, pythonw on Windows, the AppImage on Linux, the same `JOE_CONFIG`; Joe opens
          his own window, never a browser) and wait up to 45 s; if he doesn't come up, nothing runs and the
          answer says why. "Open" means Joe's PAGE is showing, not that Joe answers: the page polls
          `GET /api/devrun` every 2 s (that token-checked branch alone stamps `app.ui_seen`), `/api/ping`
          reports `"window"` = polled within 75 s, and `pagehide` posts `/api/window/bye` (token, keepalive)
          to zero it. The connector's pings stamp nothing and no longer keep Joe from idling out. Over the
          HTTP port the same test applies (the app opens the window and waits for the first poll); a run
          going with no window makes Joe reopen it (once a minute) and he doesn't idle-exit mid-run. Joe
          is never opened in the person's own browser for an app: `_open_joe` refuses when his window
          would fall back to `webbrowser.open` (no app-mode browser) or `JOE_NO_WINDOW` is set. A lock
          keeps two first requests from starting two Joes. The window reads
          `GET /api/devrun` (token needed; the run's note, the last 40 lines of its log read from the file's
          end only, and the end of `_runs.txt`; a log outside `Output/dev` is never read) and `POST
          /api/devrun/stop` (token needed; the connector key can't reach it). STOP and `joe_stop_command`
          write a stop file; the minder ends the whole tree (`devrun.kill_tree`: `taskkill /PID n /T /F` on
          Windows, the program's own process group elsewhere, never Joe's own group) and writes "STOPPED by
          ..." to `_runs.txt`; if it doesn't answer in 8 s, STOP ends the minder and the program itself.
          `joe_stop_command` stops only the run named by its two names, only while it is going, only with
          Dev tools on. The time limit and the output cap use the same `kill_tree`. A bundle pull takes the
          same "running" note (so a run and a pull never overlap) and can't be stopped half way. Windows:
          written to the same pattern as Mac/Linux but not run on Windows here.
        - `joe_computer`: program names and numbers only (no command lines, window titles, paths or
          user names; `tasklist` without `/V`, `ps` with `comm` only, `/proc/<pid>/stat` only); nothing
          is ended or changed. Shows which programs are open to the connected app: said plainly in Setup.
        - The 2026-11-27 review's findings (each proved with a script unless marked) and the answer:
          1. HIGH: a restored backup switched Dev tools on with its own commands. Fixed: `dev_tools`,
             `dev_projects` and `mcp_folders` are in `backup.NEVER_RESTORED`, left out of `backup.make`,
             and blanked in `portable.portable_settings`.
          2. HIGH: `joe_repo pull=true` then `joe_run_command` runs whatever the bundle brought in.
             Answer: pulling needs a per-project tick (`pull`, off by default, window only), every pull is
             written to `Output/dev/_runs.txt`, and Setup says plainly what a pull means. With the tick
             on this is still true and is the feature: only tick it where bundles are trusted.
          3. MEDIUM: a filter set through `include.path` wasn't switched off, so `joe_repo` alone could
             run a program after a pull. Fixed: `git config --includes` in `repostatus._local_filters`.
          4. MEDIUM: a run outlived the connector with no limit or output cap. Fixed: a separate minder
             program (`devrun.py`) holds both; the "running" note is in the settings folder
             (`devprojects.state_dir`), made in one step, and stops counting when the minder is gone.
          5. MEDIUM: an old uncollected result was handed over as fresh. Fixed: the command line is part
             of the job's key, a result older than 10 minutes is dropped, a late one says how late.
          6. MEDIUM (partly proved): a project folder overlapping Joe's workspace. Fixed: refused for
             commands and pulls (`devprojects.overlaps`).
          7. LOW: commands were tidied and cut at 500 characters. Fixed: kept as typed; too long or
             two lines is left out, never cut. The 20 MB cap is now exact (the minder copies the output).
             A bundle argument must end in `.bundle` (it was a does-this-file-exist probe).
             `shrink.is_local` took any host starting "127."; now a real loopback address only.
          Left open, on purpose or for later: a refused pull has already stored the bundle's objects
          (`fetch.fsckObjects` didn't apply to bundle fetches on git 2.43; checkout protection held);
          Stale notes: a "running" note written before the PC last started (boot time: `GetTickCount64`,
          `/proc/uptime`, `sysctl kern.boottime`) is deleted with its program and stop notes, since program
          numbers are handed out again after a restart; `kill_tree` never ends Joe's own program or his
          parent; `_alive` on Windows asks OpenProcess + GetExitCodeProcess. Windows Job Object (DONE, NEEDS A
          WINDOWS CHECK; ctypes, only mocks cover it here): the minder puts the program in a
          kill-on-close job right after starting it (a program that starts a child in the first
          milliseconds, before it is assigned, can escape; taskkill /T stays as the fallback) and ends the
          job when the program ends normally; Mac/Linux end the leftover process group then.
          `CREATE_BREAKAWAY_FROM_JOB` is asked for when starting the minder and any detached program, and
          retried without if Windows refuses. Still true on Windows: not run there; global or system git filters other than LFS still run on pulled files; `http.py` uses the
          system proxy settings even for local addresses; an add-on runs as an ordinary program and
          could write the settings file itself; Joe's daily restart doesn't wait for a dev run (the
          minder carries on and finishes it).
- [ ] `connect.py` edits other apps' config files (Claude Desktop and others): it keeps a copy
      of the old file and only touches Joe's own entry. Check the JSON merge and the backup.

## 4. Downloads and installs (`addons.py`, `doctor.py`, `picturetools.py`, `whispercpp.py`, `update.py`, `upkeep.py`)

- [ ] Every download is HTTPS from a fixed host (GitHub releases, Hugging Face, PyPI/PyTorch
      index, the Ollama registry). No URL comes from a mission or a chatbot.
- [ ] **Joe's own updates** (`update.py`): `download()` refuses a file without a matching line in
      `SHA256SUMS.txt`; `sign.py` (pure-Python Ed25519) verifies that file once
      `joeai.SIGN_PUBLIC_KEY` is set (it is, since 2.1): an update without a matching
      signature is refused. The signed list also carries the version (`release.yml` adds
      `# joe-ai version X` before signing; `update.listed_version` reads it back): Joe installs it
      only when that version is the one offered and newer than his own, so an older signed release
      can't be offered as new. Windows Authenticode isn't done yet.
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
- [ ] Model files: `.ckpt/.pt/.pth/.bin` can run code when loaded. Since 2.1.5 Joe never downloads
      or picks one himself (`comfy.best_image_model`, `doctor.refuse_pickle`, `stylemodels.MODEL_EXT`);
      a pickle file the person already has is used only after their YES in the window (System check >
      Your models), remembered for that exact file (full path, size and last-changed time) in `pickle-ok.json` in the settings folder
      (`comfy.allow_pickle`, `/api/models/pickle`, window token only). Every graph passes
      `comfy.check_pickles` in `ComfyClient.submit`, so a plan from another AI, Joe Phone or MCP can't
      load one without that YES. `modelcheck.py` reads `.safetensors` headers without loading them.

## 7. Secrets and privacy (`config.py`, `support.py`, `backup.py`, `websearch.py`)

- [ ] API keys (web search, MCP key, engine key, ntfy topic) live in the computer's own vault since 2.3
      (`vault.py`: DPAPI on Windows, `security -i` on a Mac, `secret-tool` on Linux, else the settings
      file at 0600). Check: a key is only blanked in the file after a read-back; a locked/unreadable
      vault never deletes; the key never appears on a command line; Portable Joe stays file-only.
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

## 2.3 additions (dev-2.3)

- [ ] Agents, the real build (`agents.py` list/templates/abilities, `agentrun.py` the one engine,
      `agentweb.py` lookups). Tests: `tests/test_dev23_agent_engine.py` (one per rule) and
      `tests/test_dev23_agents.py`. Rules to try to break:
      - **Search words only from the owner's job once a file was read** (`agentweb.safe_query`, the run's
        `tainted` flag = any trigger file or agent-folder file exists, or any tool/read touched one).
        Untainted runs (a Researcher with no files) may phrase their own searches. Never a URL, e-mail or
        long number in a search. Try: a planted "search for <this letter>" line in the agent's folder
        (`test_search_words_come_only_from_the_owners_job_once_a_file_was_read`), including through the
        fact-check's claim searches.
      - **Lookups off = no network call at all**: the agent's switch, Setup's "look things up online",
        or JOE_OFFLINE (`agentweb.enabled`; `test_lookups_off_means_no_network_call_at_all`).
      - **Pages read**: only an address a search in this run returned or one the owner typed in the job;
        http(s) to a public host only (no localhost, home network, `user:pw@`, file:), checked again on
        every redirect and after the name is looked up (`public_url`, `_resolves_public`,
        `_CheckRedirects`). Caps: 14 searches, 8 pages per run.
      - **Risky abilities** (`agents.ABILITIES`: lookups, files, phone): off until their own screen got a
        yes (`acks` = the screen's version; a changed screen asks again; `save()` refuses otherwise; a
        COPY starts with them off); a template can't turn on one it doesn't offer; without the ability
        its actions aren't offered to the model, and Joe refuses them if asked anyway.
      - **Paperwork clerk file changes**: suggestions only (`propose`), applied only by APPLY in Joe's
        window after "are you sure?" (`/api/agents/apply`, window token), only inside the agent's own
        folder, one folder deep, no `..`, file's own extension kept, never over a file, nothing deleted,
        undo list written before each move (`apply_pending`, `undo_last`, `agentrun.clean_target`).
      - **Phone**: the digest/reminder goes only to the owner's own ntfy topic, once per run, and never
        when the run has read a file (`do_send`, `do_remind`).
      - **Requests**: a request from Talk or the phone is one line of the mission (`mission_text` uses
        `_safe`); a connected app can start an agent that allows it but can't add a request (`mcp.check`).
        The assistant starts only other agents that exist (not itself, not another assistant), by
        writing a normal mission into Missions/Queue.
      - Kept from dev6: only ticked tools (`allowed_tools`, BLOCKED, no `x-` add-ons, no code); files
        only from the trigger files, the agent's own `Inbox/Agents/<name>`, this run's outputs and its
        `sources/`; step SAVE forced under the run folder; options and titles from the model can't add
        a line to a step's mission; DATA markers can't be closed early (`_data`), for web results too;
        create/change only via window-token routes `/api/agents/*`; phone `agent-start` and MCP
        `joe_start_agent` respect `start.remote` and `paused`.
      - Not built, on purpose (Joseph): anything that clicks through websites, anything that connects to
        an inbox. Nothing an agent does sends to other people.
- [ ] Agents, review fixes (2.3.0.dev15; `tests/test_dev23_review15.py`, one test each):
      - **Pages: the connection itself is checked** (`agentweb._checked_connect`): the address the socket
        really reached must be a public one, so a name that passes `_resolves_public` and then points at
        this PC or the home network (DNS rebinding) is refused before anything is sent. IPv4 written
        inside IPv6 (`::ffff:`, `64:ff9b::`, 6to4) counts as the IPv4 address (`_global_ip`). Page
        downloads don't use a proxy (the check needs the real connection).
      - **One agent starting another** (`do_start`): once per agent per run, and the request passed on
        keeps only words the owner typed (`agentweb.owner_words`), because the other agent takes its
        request for its owner's words (they may go into its searches).
      - **Phone**: the same reminder is never made twice and a run makes 3 at most (`do_remind`). The
        "agent paused" ping is Joe's fixed words plus the agent's name, nothing from a file or the model.
      - **The clerk's folder**: Joe's own `_UNDO *.json` is never offered to an agent or taken for new
        work, and files renamed by APPLY don't start another run (`_mark_seen`). APPLY's "are you sure?"
        lists the changes themselves.
      - **Fail-safes** (Joseph): `max_fails` per agent (1-100, default 10; `save()` never stores "no
        limit"), repeats of any earlier step, 6 steps without progress, 3 bad runs in a row = paused.
      - **Abilities**: an ack that isn't the screen's version (a word, a list) never counts (`save`,
        `ability_on`). Lookups alone can't tick the last point of a plan (`tick_off`).
      - Known and left as is: in a run that has read files, the choice and order of the owner's own job
        words in a search could carry a few bits; a mission the Talk model writes and the owner starts
        counts as the owner's words.
- [ ] Online lookups redo (2.3, overnight 2026-11-15; NEEDS A FABLE REVIEW BEFORE MERGING):
      - **Search sources** (`websearch.py`): only the search words go to each source; sources are off
        until ticked (default list = the old Ollama-then-Wikipedia); a refused key / 429 / failure rests the
        source; per-task cap; results are data (`as_context`). `tests/test_lookups.py`.
      - **LangSearch and "your own search source"** (`websearch.py`, 2026-11-15; REVIEWED 2026-11-24, see the end): two more
        sources, off until ticked. LangSearch: search words + its key to `api.langsearch.com` only. Own
        source: the address the person typed (http(s) only, no user:pw, may be on the home network like
        SearXNG), `{query}` percent-encoded into the address or JSON-escaped into the posted body; the key
        goes only to that address (header name limited to letters, digits and `-`; `{key}` in the address is
        percent-encoded); result links must be http(s). Both keys are in `vault.SECRETS`, `backup.KEY_PATHS`,
        blanked on a portable copy, kept on reset. `tests/test_more_sources.py`.
      - **SearXNG help** (`searxng.py`): `make_folder` writes only `<Joe folder>/SearXNG/config/settings.yml`
        (never over an existing file) and makes `data/`; Joe never runs Docker, he only shows the command
        (bound to 127.0.0.1). `check` asks only the address in the box. `tests/test_searxng_setup.py`.
      - **Page reader** (`pagereader.py`, used only when "read whole result pages" is on): http(s) only, no
        user:pw, usual ports only (80/443/8080/8443), names like localhost/*.local/one-word refused, number
        tricks (127.1, 0x7f.1, 2130706433) refused, every resolved address must be public, Joe connects to
        the checked address and checks the socket's peer again, redirects re-checked (3 at most), text
        types only, packed answers refused, 2 MB / 20 s hard limits (a timer closes a dripping socket),
        HTML parsed for words only (script/style/svg/iframe... dropped), odd charsets fall back to UTF-8,
        no cookies/Referer/auth sent, never raises. Ollama's web_fetch never gets a home address either.
        `tests/test_pagereader.py`. Try: IPv6 tricks, DNS rebinding, redirect chains, slow drips, a huge
        page, a page that pretends to be HTML but is a program.
      - **The Tester's box** (`codebox.py`, 2026-11-21; REVIEWED 2026-11-24, see the end): the only place code Joe wrote is
        run (Joe-AiGent's "code" action, `agentrun.do_code`; ability "code", off until its screen is OK'd).
        A second Python (`-I -S -B`) per test run: files written to a fresh temp folder outside the Joe
        folder (plain names only, text only), deleted after; bare environment (no keys, no PATH, HOME/TEMP
        = the box); an audit hook installed before any task code loads (refuses: opening/changing anything
        outside the box except reading Python's own library, every `socket.*`/`http.client`/`urllib`
        event, `subprocess`/`os.system`/`os.exec*`/`os.spawn*`/`os.fork`/`_winapi.CreateProcess`,
        `ctypes.*`, `winreg.*`, `os.kill`, `mmap`, `fcntl`, raising its own limits); rlimits (memory, CPU,
        file size) on Linux/Mac, EXCEPT memory on a Mac: macOS doesn't keep to the memory rlimit (found on
        GitHub's Mac run, 2026-11-22), so there `codebox.MemoryWatch` reads the box's process group with
        `ps` ten times a second from Joe's side and kills the group when it is over (REVIEWED 2026-11-24, see the end, and
        first proven on GitHub's Mac: a watch is slower than a limit, a quick grab can pass between two
        looks; no `ps` = no watch and the fence list doesn't claim one); a Windows Job Object (memory,
        one process, kill-on-close); wall-clock
        timeout that kills the process group; output cap; Linux `unshare --user --net` / Mac
        `sandbox-exec (deny network*)` when they work. The verdict line carries a one-time word sent on
        stdin, so task code can't print its own verdict. KNOWN LIMIT, said in the guide and on the
        ability's screen: an audit hook is not a security boundary against code written to escape (C
        extension tricks, bugs in CPython); it is a fence against wrong code. A WebAssembly box is the
        planned real boundary. `tests/test_codebox.py` tries each fence with real forbidden code;
        `tests/test_aigent.py::test_code_runs_only_in_the_box`. Try: escapes through `gc`/frames/`pickle`,
        `os.open` flag tricks, symlinks made inside the box pointing out, `shutil` paths, huge output, fork
        bombs via threads, reading other users' files through Python's library folders, Windows-only paths
        (`\\?\`, short names, drive-relative), the Job Object on a PC where Joe already runs in a job.
      - **The Tester's box, AFTER THE INDEPENDENT REVIEW of 2026-11-22** (an Opus helper starting cold; 19 findings,
        the box ones fixed the same day; the fixes themselves are REVIEWED 2026-11-24, see the end). As the code is now: a guard
        inside the box's Python refuses reading outside the box and Python's own library; writing, deleting or
        renaming outside the box (the library included); changing folder outside the box; folder handles (dir_fd);
        SQLite reaching outside (ATTACH, VACUUM INTO, "file:" names, extensions); named pipes; network; other
        programs; ctypes; the Windows registry. Limits: time (every system); memory (rlimit on Linux, Job Object on
        Windows, a watch from outside ten times a second on a Mac, no longer claimed if "ps" stops answering);
        20 MB a file (Linux and Mac only); 200 MB / 5000 files in all, looked at from outside four times a second on
        every system (a fast writer gets a quarter second's writing past it); output: the box is stopped past 6 MB
        printed and Joe never holds more than 3 MB of it. Exiting while loading, async or generator tests and
        exiting with no verdict are failures, never passes. Old box folders are swept after a day.
        NOT COVERED (code written on purpose to get out): faking the verdict through frames / gc, changing the
        guard's insides, posix._exit / posix.mkfifo / _sqlite3 called directly, undoing SQLite's fence on its own
        connection, os.stat seeing whether outside files exist, signalling Joe through a pidfd (Linux), _winapi and
        UNC paths (Windows: realpath on a UNC path can contact a file server). From the review: a web page or
        file an agent read can steer what the Coder writes (finding 8), so "code only for the owner's job" was
        not strictly true. DECIDED by Joseph, 2026-11-23 (REVIEWED 2026-11-24, see the end): text from outside can carry
        instructions, so once a run has read any, it doesn't write or run code. `agentrun.Run.read_outside` is
        true from the moment the run took in a file (`web.tainted`: a trigger file, a file in its folder, a tool
        run on one) or something found online (a search that returned results, a page read), and stays true for
        the rest of the run; the run's own outputs don't count by themselves. From then on `do_code` is refused
        before any Coder, Tester or box (`CODE_AFTER_READING` is the reason, in the log and once in the report),
        and code is no longer offered to the model or listed to the planner. A run that codes first and reads
        later keeps the code it already made (the Improver still runs on it: its card is the code, its test and
        the task written before the reading). A run that starts outside-read says so at its start. The "code"
        ability screen says it (version 1 -> 2, so it is asked again). `tests/test_agent_code_after_reading.py`.
        Not covered: words the owner pasted into the job, a request handed on by another agent (only words of
        that agent's own job pass), memory notes and add-on tools. Could not be run on
        Windows or a Mac: the pipe reader thread, the Job Object order, Python 3.14's shutil inside the box.
      - **Wake word** (`ui/app.js` wakeSplit, 2026-11-21; REVIEWED 2026-11-24, see the end): off unless ticked. The open mic
        then stays on outside Talk; each utterance goes through the same local `/api/voice/listen` (the
        recording file is deleted as before; with `X-Joe-Wake` no mic levels are logged) and is dropped in
        the page unless it starts with the wake words. Nothing is shown, kept or sent for dropped speech.
        `tests/test_wake_word.py`. Try: a wake phrase inside a played video, very long wake words.
        Rolling second (`ui/app.js` micRing, 2026-11-22; REVIEWED 2026-11-24, see the end): while the open mic listens, the
        last 1 s of sound is kept in the page's memory only, so the first syllable isn't cut off; never
        written or sent alone; cleared when a recording starts, while Joe speaks, and in openMicStop; not
        used by push-to-talk. `tests/test_open_mic.py`. Try: stop the mic mid-sentence, check nothing is sent.
      - **Wake word and open mic, AFTER THE INDEPENDENT REVIEW of 2026-11-22** (fixed the same day by Joseph's
        decisions; the fixes are REVIEWED 2026-11-24, see the end and need his microphone). Only words that start with the wake
        words count, on any screen AND on Talk once "Hey Joe" brought it there: after Joe answers he waits for them
        again until the person opens Talk themselves (Talk tab, F4, TALK TO JOE, sending typed text, the mic
        button, a saved chat, a dropped file). Everything else is dropped in the window before it is routed.
        Only "Joe" as speech-to-text writes it wakes him (joe, jo, joel, joe's, joh, jow); Joseph, Joey and Joan
        don't; a person's own wake words match exactly or with an s. A TV, video or song can still wake him.
        Through the wake word Joe ASKS FIRST ("Start the plan now? Say yes or no.") before go / run, any agent
        start, remember / forget, reminders, changing or sending a list, parking an idea, directions or shopping
        pages; only a clear yes within 10 seconds after he stops talking (30 at most) does it. A question that
        wakes him is handled like a Talk question (model, talk log, saved chats, maybe an online lookup).
        The recording goes in a temporary heard_* file with a unique name and is deleted in a finally; older ones
        are swept each time Joe listens; wake recordings add no line to MAKE A HELP FILE. Up to 3 words before the
        wake words are allowed and dropped with them (the rolling second can carry quiet speech said just before).
        Only one mic start at a time; a start that was stopped or failed lets go of the microphone completely.
        While the box is ticked the mic comes on by itself every time Joe opens (Joseph: keep, but say so; the
        note under the tick box says it).

      - **Preview copies** (`thumbs.py`, `/thumb`): the path goes through the same `app.rel_path` sandbox
        check as `/raw`; FFmpeg (guarded: local files only) writes a 320 px JPEG into the temp folder
        `joe-ai-previews` (0700), named by a hash; never into the Joe folder. The BIG WINDOW (`/player`)
        now carries one inline script behind a per-page nonce (`script-src 'nonce-...'`), only when the
        folder has more than one picture; file names are escaped. `tests/test_dev2_3_28.py`.
      - **Search add-ons** (`community.py` "search"): program is joe:python or env:python only (no other
        programs), first arg must be the add-on's own script, no `..`, only `{addon}` filled in; the
        search words go on stdin as JSON, never on the command line; bare environment (no keys, no JOE_*
        variables, HOME/TEMP = a fresh empty folder), no shell, `-I`, its own process group, time limit
        (5-60 s) stops it and its children, output read with a 256 KB cap (stopped at once past it),
        stderr 4 KB, results cleaned (http(s) addresses only), pace between searches, a 429-style answer
        rests it. Own environment: uv, exact versions only, `--no-build` (wheels only), built only when
        turned on, removed with the add-on. Risk screen before turning on; still unticked as a source
        after. Changed files = turned off (fingerprint). `tests/test_search_addons.py`.
        Known and left as is: its program can reach the internet and anything the user's account can;
        transitive dependencies of an env:python add-on are not pinned (uv picks them).
      - **Agents** call `websearch.agent_find` (the one line changed in `agentweb.py`): same sources, a
        session per run, and no lookups at all when the run reads e-mail (e-mail files in the agent's
        folder, or an ability/tool named for mail).
      - **Fable review 2026-11-15** (found and fixed, each with a test): the page reader took IPv4
        written the old ways inside IPv6 (`::127.0.0.1`, `::ffff:0:127.0.0.1`) and the old site-local
        block (`fec0::/10`) for internet addresses (now IPv6 must be in `2000::/3`); a page claiming
        `charset=punycode` kept Joe busy for minutes, past the time limit (now only real web character
        sets are honoured); picking the words out of a page had no time limit (now 5 s); `<embed>` or a
        page-wide `<form>` lost the page's words; parts marked hidden (`hidden`, `aria-hidden`,
        `display:none`) were kept though the notes said dropped (now dropped). Ollama search results
        kept non-web addresses (now http(s) only, titles cleaned). The Setup list could show a source
        unticked that SAVE still turned on (list reloaded with unsaved ticks). A search add-on turned
        off or removed stayed ticked in the saved list. Agents: an e-mail that started the run (or one
        in a sub-folder) didn't switch lookups off; agents now read pages with `pagereader.py` (the
        older reader in `agentweb.py` is gone); the report names the sources really asked.
        Still open (Joseph): see "Open decisions" in NEXT_STEPS.md (the review entry itself is now in
        NOTES_HISTORY.md, 2026-11-15).
- [ ] Daily restart (`dailyrestart.py`): starts a new Joe the same way as RESTART JOE (`app.restart`,
      `joe_command("restart")`, no shell); never while a run, the queue, a plan being written, a
      download or an install is going (`busy`); a failed start leaves this Joe running. Tests:
      `tests/test_dev23_restart.py`.
- [ ] Memory (`memory.py`): opt-in; `memory.json` in the config folder; `ORIGIN` set to phone/connector
      in `phone.ask` and `mcp.handle`; `joe_memory` is not listed or callable unless shared; changes only
      from the window (and the phone when allowed); backup only with "include memory".
- [ ] Filing / tidy (`filing.py`): tidy only moves inside Output, never overwrites, writes an undo list;
      `_repoint` rewrites run state and reports; `translate_input` can't point outside Output.
- [ ] FFmpeg guard (`ffguard.py`): `-protocol_whitelist file,pipe,fd` before every `-i` for any ffmpeg
      process started from Joe's Python (subprocess.Popen is wrapped).
- [ ] Pinned downloads: uv 0.13.7 and whisper.cpp 1.9.2 with SHA-256 (`addons.UV_SHA256`,
      `whispercpp.WIN_ZIP_SHA256`): cross-check the sums with the release pages.
- [ ] Secure connections (`http.py`, 2026-11-15): on Windows Joe builds his own trusted list for https:
      the same certificates Python loads (Windows' ROOT and CA lists, the same "trusted for web sites"
      rule) minus the ones that have run out (`trusted_certs`, `cert_facts` reads the end date with a
      small reader of Joe's own; one Joe can't read is kept and left to OpenSSL). Everything else is
      `ssl.create_default_context` (certificate required, name checked). Nothing is ever added to the
      list and Windows' own list is never changed. `http.install()` (from `joeai/__init__.py`) puts it
      under every `urllib` request; the page reader uses the same `tls_context()`. Any trouble reading
      the list falls back to Python's own. Check: no path turns checking off (`CERT_NONE`,
      `check_hostname = False`, `_create_unverified_context` appear nowhere), and a site no trusted
      certificate vouches for is still refused. Tests: `tests/test_secure_connections.py` (pretend
      certificates in `tests/pretend_certs.py`; its one private key only answers as "localhost").
- [ ] Audit fixes, 2026-11-23 (REVIEWED 2026-11-24, see the end; from `AUDIT_2026-11-23.md`):
      - **Request guards** (`server.py` `H._length`, `_mcp_http`; `phone.py` `_body`): a raw body's
        `Content-Length` must be a whole number from 0 to the route's limit, else the route gives its
        usual "empty or too big" answer; the `/mcp` key is compared as bytes, so a key with odd characters
        gets a 401 answer instead of a dropped connection; a missing window file answers 404. Try: no
        length, `Content-Length: abc`, a negative or huge length, `Authorization: Bearer é`, on every
        raw-body route and on Joe Phone.
      - **Build stamp** (`app.build_stamp`, `App.stamp`): for a copy not made by an installer (no
        `joeai/_install.json`), a short hash of the names, sizes and change times of `joeai/*.py` and the
        window's files goes in the lock file and `/api/ping`. A running Joe is reused only when version
        and stamp match (or he is mid-run); when his files were edited he says "Joe's files changed since
        this window opened. Restart Joe to use them." Installer builds have no stamp and behave as before.
      - **Connector cap** (`mcp.py` `MAX_SHRINK`, `Joe.shrink`, `Joe.read_file`): `joe_shrink` returns at
        most 20,000 characters a call (a `max_chars` that isn't a number means 8,000); `joe_read_file`
        reads only its 200,000 characters from the file. What each read tool can reach is in section 3.
      - **Connector folders** (`config.py` `Settings.mcp_folders`, `mcp.py` `Joe._shrink_source`): off by
        default, so `joe_shrink` / `joe_summarize` read Output only and refuse the Inbox, Projects,
        Missions, Workflows and Themes with a message telling the app where the person can open them.
        Changed only by the tick box on Setup > Other AI apps, through window-token routes
        (`/api/settings`; Setup > Reset puts it back off). The HTTP connector sees a change at once;
        the stdio connector (`mcp.serve`) reads settings at its first tool call and keeps them until the
        AI app restarts it, the same as `memory.connector`. Try: Inbox paths with it off, a link in Output
        pointing into the Inbox, setting it from `/mcp`, Joe Phone or without the token.
      - **Model-call options** (`ollama.py`, `textengines.py`): a call can ask for a low temperature
        (`DECIDE_TEMP`, only where the reply is read as a choice, a category or JSON) and a JSON shape
        (`format` / `response_format`); a server that refuses the shape is asked once more without it, and
        the old reading of the reply stays as the fallback. Nothing new leaves the PC: these go only to
        the writing program already in use.
      - **No code after reading** (`agentrun.py` `Run.read_outside`, `do_code`, `offered`; finding 8 of the
        2026-11-22 review, decided by Joseph): a run that has read a file, a search result or a web page is
        refused a code step, isn't offered one, and says why once. See the Tester's box above.
        `tests/test_agent_code_after_reading.py`. Try: a run that reads in a way that doesn't set the flag.

## Review of 2026-11-24 (Opus, before the 2.3 release)

Done in the same working session as the day's other 2.3 changes, not in a fresh chat. The reviewer wrote
none of the code below except the three changes marked (new today), which therefore still want a second
pair of eyes. Read every item marked NOT YET REVIEWED above; tried the "Try:" lists where this PC (Linux)
can; ran the matching tests (all pass).

- **Found and fixed: keys followed redirects to other sites** (`http.py` `_KeysStayHome`, new today).
  Python's own redirect handler copies every header to wherever a redirect points, so LangSearch, your own
  search source, Ollama web search or a writing service could pass Joe's key to another host, or from https
  down to plain http, just by answering with a redirect. Shown with two local servers before the fix. Now a
  redirect to another scheme, host or port carries only User-Agent, Accept and Content-Type; the same site
  keeps them. `tests/test_security_review_1124.py`.
- **LangSearch and your own search source**: keys go only to their own address (with the fix above); the
  search words are percent-encoded into the address or JSON-escaped into the body (a word can't add JSON
  fields: an unquoted {query} with quotes in it just fails as bad JSON); header names letters/digits/- only;
  result links http(s) only.
- **The Tester's box** (Linux, real code): reading /etc and /proc, a symlink pointing out, listing /,
  copying out, SQLite ATTACH, posix.system, and swapping posixpath.abspath inside the box were all refused;
  nothing escaped. Not checked here: the Windows Job Object and Windows paths, the Mac memory watch (no
  Windows or Mac on this PC; GitHub runs the box tests on both). The listed NOT COVERED escapes stand: the box
  is a fence against wrong code, not a vault.
- **No code after reading**: every way a run takes in outside text sets the flag: trigger and folder files
  (tainted from the start, and they are the only outside files a step may name), reading a file outside the
  run, a tool on outside files, a search with results, a page read. No tool an agent may use reaches the
  internet (find-book is blocked) and a step can't turn on RESEARCH. Known gaps unchanged (owner's pasted
  words, a handed-on request, memory notes).
- **Wake word and ask-first** (code read, no microphone here): words without the wake words are dropped
  before anything is routed; every command is sorted into ask-first or fine and the window asks for exactly
  the first group (a test checks both lists against route.py and the window); a yes counts only within the
  time limit and only from the fixed yes words; recordings are temp files with a fixed extension, deleted in
  a finally and swept. Still needs Joseph's microphone for the live part.
- **The 2026-11-23 audit fixes**: request guards, build stamp, connector cap, connector folders (a link in
  Output to the Inbox counts as the Inbox), model-call options: as described; tests pass.
- **New today, still wanting a second look**: the connector reads a refused request's small body (64 KB at
  most) before its 401, so Windows doesn't reset the connection (`server.py` `_drain`); kids' picture
  prompts lose nudity and sexual words before drawing (`styles.kid_safe`), the record shows the cleaned
  prompt, and the picture check after is unchanged.
