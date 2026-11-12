"""One run of an agent (2.3): the one engine all five templates share (agents.py has the list).

What makes it an agent (Joseph's measure, 2026-11-11: a model as the brain that perceives, reasons
about a goal, plans the steps, acts with tools and keeps going until the goal is met):

  1. PLAN FIRST. The model breaks the owner's job into a few points that must each be done. The plan
     is shown in AGENT REPORT.md with a tick beside each point as it gets done.
  2. STEPS. Each step is one action the template allows (ACTIONS below): look something up, read a
     page or a file, write, use one of the ticked tools, suggest file changes (the clerk), send the
     digest to the phone (the briefing), make a reminder or a list entry, start another agent (the
     assistant). The model picks the step; Joe checks it is allowed before doing it.
  3. JOE CHECKS BEFORE ASKING AGAIN. After every step, the plan's points are ticked off against what
     was made and found. When every point is done the run finishes (no more asking the model "what
     next?": Joseph's PC test, where a finished job went on for four more steps). A "done" from the
     model with points still open is sent back once, saying which points.
  4. THE RESET RULE (Joseph's idea, from his 1990s programs that restarted to dump memory leaks).
     Every RESET_EVERY steps, and whenever a step fails twice, Joe writes a checkpoint (the job, the
     plan, what's done, what was learned, what's left, and a look at whether the work is still on
     the job), throws the working context away and starts the next step clean from the owner's job
     plus that checkpoint only. A wrong turn is caught at the next checkpoint.
  5. FINISH ONLY WHEN EACH POINT IS DONE, then the quality check (agents.quality_check) and, with
     lookups on, the FACT CHECK: the checkable claims (numbers, dates, names, prices) are looked up
     under the search-words rule and marked confirmed / not found / contradicted with their source;
     contradicted ones get [CHECK] in the text. With lookups off the report says plainly that nothing
     was checked.
  6. A PLAIN LOG (AGENT LOG.txt) of everything Joe did, and the live status for the strip on every tab.

Safety (tests/test_dev23_agent_engine.py has one test per rule): see agents.py and agentweb.py.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from . import agents
from .agents import RULES, _data, _plain_name
from .fsutil import atomic_write_text

RESET_EVERY = 3              # steps between checkpoints (the reset rule)
READ_CHARS = 12000           # of one file read whole
CONTEXT_CHARS = 2500         # of one step's result carried in the working context
MAX_POINTS = 8
MAX_CLAIMS = 6

PLAN_SYS = "You make the plan for one of Joe's agents."
PICK_SYS = "You are the planner inside one of Joe's agents."
TICK_SYS = "You tick off the points of an agent's plan."
REVIEW_SYS = "You review an agent's progress at a checkpoint."
CLAIMS_SYS = "You pull the checkable facts out of an agent's finished work."
VERDICT_SYS = "You compare one claim with what was found online."

# action -> (what the planner is told, the JSON it answers with, the ability it needs or "")
ACTIONS = {
    "search": ("look something up online", '{"action": "search", "query": "<a few search words>"}', "lookups"),
    "read": ("read a whole page found by a search, or one of the files listed",
             '{"action": "read", "url": "<an address from the results>"} or {"action": "read", "file": "<a file from the list>"}',
             ""),
    "write": ("write a document or a list (the sources and files read so far are given to the writer)",
              '{"action": "write", "title": "<a short title>", "instruction": "<what to write>", "input": ["<files to use>"]}',
              ""),
    "tool": ("use one of the tools listed on files from the list",
             '{"action": "tool", "tool": "<tool id>", "input": ["<file>"], "options": [], "instruction": "<one or two sentences>"}',
             ""),
    "propose": ("suggest a new name and folder for files in the agent's folder (nothing changes until the owner says OK)",
                '{"action": "propose", "changes": [{"from": "<file>", "to": "<Folder/New name.ext>"}]}', "files"),
    "send": ("send the finished digest (the last thing written) to the owner's phone, once",
             '{"action": "send"}', "phone"),
    "remind": ("make a reminder on the owner's phone",
               '{"action": "remind", "text": "at 5pm to call the vet"}', "phone"),
    "list": ("add things to one of the owner's lists",
             '{"action": "list", "list": "<list name>", "things": "milk, eggs"}', ""),
    "calendar": ("make a calendar entry (.ics file) from the request",
                 '{"action": "calendar", "instruction": "<the date, time and what>"}', ""),
    "start": ("start another of the owner's agents that exists",
              '{"action": "start", "agent": "<its name>", "request": "<what it should do this time>"}', ""),
}


class Stuck(Exception):
    pass


class Run:
    def __init__(self, engine, mission, job, st, agent: dict):
        from .agentweb import Lookups
        from .tools import tool_dir
        self.engine, self.mission, self.job, self.st, self.agent = engine, mission, job, st, agent
        self.sb = engine.sb
        self.tpl = agents.TEMPLATES[agent["template"]]
        self.folder = tool_dir(engine, job, st)
        self.run_rel = st.output
        # The job the owner typed: the agent's job, plus what was asked this time (Talk, the phone).
        self.request = agent["job"] + (f"\nThis time: {job.format.strip()}" if (job.format or "").strip() else "")
        self.t0 = time.monotonic()
        self.deadline = self.t0 + agent["minutes"] * 60
        self.log_lines: list[str] = []
        self.names = agents.allowed_tools()
        self.tools = [t for t in agent["tools"] if t in self.names]       # re-checked: a removed tool drops out
        self.actions = [a for a in self.tpl["actions"] if not ACTIONS[a][2] or agents.ability_on(agent, ACTIONS[a][2])]
        if "tool" in self.actions and not [t for t in self.tools if t != "text"]:
            self.actions.remove("tool")
        self.web = Lookups(engine.s, agent, self.request, self.log)
        if "search" in self.actions and not self.web.on:
            self.actions = [a for a in self.actions if a != "search"]
        self.outside = self._outside_files()
        self.allowed = list(self.outside)
        self.web.tainted = bool(self.outside)          # the search-words rule (agentweb.py)
        self.plan: list[dict] = []
        self.steps: list[dict] = []
        self.made: list[str] = []
        self.context: list[str] = []                   # the working context: thrown away at each checkpoint
        self.checkpoint = ""
        self.checkpoints = 0
        self.sources: dict[str, dict] = {}             # url -> {"n", "title", "url", "file"}
        self.facts: list[dict] = []
        self.sent = False
        self.proposed: list[dict] = []

    # -- the plain log -----------------------------------------------------
    def log(self, msg: str) -> None:
        self.engine.log(msg)
        self.log_lines.append(f"{datetime.now():%H:%M:%S} {msg.strip()}")
        try:
            atomic_write_text(self.folder / "AGENT LOG.txt", "\n".join(self.log_lines) + "\n")
        except OSError:
            pass

    def live(self, doing: str, n: int = 0) -> None:
        agents.live_set(name=self.agent["name"], template=self.tpl["name"], step=n, of=self.agent["steps"],
                        doing=doing, folder=self.run_rel, t0=time.time() - (time.monotonic() - self.t0),
                        plan=[{"point": p["point"], "done": p["done"]} for p in self.plan],
                        steps=[f"{x['n']}. {x['what']}: {x['status']}" for x in self.steps[-12:]])
        self.st.note = f"step {n} of {self.agent['steps']}: {doing}" if n else doing
        self.engine._save_state(self.job, self.st)

    # -- what a run may read ----------------------------------------------
    def _outside_files(self) -> list[str]:
        from .sandbox import SandboxError
        out: list[str] = []
        for rel in self.job.inputs:
            try:
                p = self.sb.resolve_input(rel)
            except SandboxError:
                continue
            if p.is_file() and _plain_name(p.name):
                out.append(str(p.relative_to(self.sb.root)).replace("\\", "/"))
        af = agents.agent_folder(self.sb, self.agent)
        if not self.job.inputs and af.is_dir():
            out += [str(p.relative_to(self.sb.root)).replace("\\", "/") for p in sorted(af.iterdir())
                    if p.is_file() and _plain_name(p.name)][:50]
        return out

    # -- model calls -------------------------------------------------------
    def ask(self, system: str, user: str, tokens: int = 500) -> dict | None:
        return agents._ask_json(self.engine, system, user, tokens)

    def plan_text(self) -> str:
        return "\n".join(f"{'[x]' if p['done'] else '[ ]'} {i}. {p['point']}" for i, p in enumerate(self.plan, 1))

    def make_plan(self) -> None:
        d = None
        try:
            d = self.ask(PLAN_SYS + " Break the owner's job into the 2 to 6 points that must each be done for "
                         "the job to be finished, in order. Each point is one short sentence about a result, "
                         'not a tool. Reply with ONLY JSON: {"points": ["...", "..."]}',
                         f"The owner's job:\n{self.request}\n\nWhat this agent can do: " +
                         "; ".join(ACTIONS[a][0] for a in self.actions), 300)
        except Exception as e:                         # noqa: BLE001
            self.log(f"  Couldn't make a plan with the model ({e}); the job itself is the plan.")
        pts = [" ".join(str(x).split())[:200] for x in ((d or {}).get("points") or []) if str(x).strip()]
        self.plan = [{"point": p, "done": False} for p in pts[:MAX_POINTS]] or [{"point": " ".join(self.request.split())[:200], "done": False}]
        self.log("Plan:\n" + self.plan_text())
        self.write_notes()

    def files_for_model(self) -> list[str]:
        return self.allowed[:60]

    def pick(self, fix_note: str) -> dict | None:
        lines = [f"- {a}: {ACTIONS[a][0]}. Answer: {ACTIONS[a][1]}" for a in self.actions]
        tool_lines = []
        if "tool" in self.actions:
            from .tools import TOOLS
            for t in self.tools:
                if t != "text":
                    tool_lines.append(f"- {t}: {self.names[t]}. {TOOLS[t].blurb if t in TOOLS else ''}")
        user = (f"The owner's job:\n{self.request}\n\nThe plan ([x] = done):\n{self.plan_text()}\n\n"
                "What you may do (one per step):\n" + "\n".join(lines) +
                ("\n\nTools:\n" + "\n".join(tool_lines) if tool_lines else "") +
                "\n\nFiles you may use (exact names):\n" + ("\n".join(f"- {a}" for a in self.files_for_model()) or "(none)") +
                (f"\n\nCHECKPOINT (your notes so far; start from here):\n{self.checkpoint}" if self.checkpoint else "") +
                ("\n\nSince then:\n" + "\n\n".join(self.context[-6:]) if self.context else "") +
                (f"\n\nStill to do: {fix_note}" if fix_note else ""))
        d = self.ask(PICK_SYS + " You pick ONE next step at a time toward the owner's job, using only what is "
                     "listed. " + RULES + ' Reply with ONLY one JSON object (one of the answers listed), or '
                     '{"done": true} when every point of the plan is done.', user)
        if not d:
            return None
        if d.get("done") is True:
            return {"done": True}
        act = str(d.get("action") or ("tool" if d.get("tool") else "")).strip().lower()
        if act == "tool" and str(d.get("tool", "")) == "text":
            act = "write"
        if act not in self.actions:
            asked = act or str(d.get("tool", ""))
            self.log(f"  Agent: the model asked for '{asked[:40]}', which this agent may not do; ignored.")
            return None
        d["action"] = act
        if act == "tool":
            tool = str(d.get("tool", "")).strip()
            if tool not in self.tools or tool == "text":
                self.log(f"  Agent: the model asked for '{tool[:40]}', which isn't ticked for this agent; ignored.")
                return None
            d["tool"] = tool
        if act in ("tool", "write"):
            d["input"] = self.check_files(d.get("input") or [])
        return d

    def check_files(self, raw) -> list[str]:
        raw = raw if isinstance(raw, list) else [raw]
        norm = {a.lower(): a for a in self.allowed}
        out = []
        for r in raw[:20]:
            k = str(r).strip().replace("\\", "/").lower()
            if k in norm:
                out.append(norm[k])
            else:
                self.log(f"  Agent: '{str(r)[:60]}' isn't a file this agent may use; left out.")
        return out

    # -- the steps ---------------------------------------------------------
    def do(self, n: int, step: dict) -> dict:
        act = step["action"]
        return getattr(self, "do_" + act)(n, step)

    def _source_file(self, url: str, title: str, text: str) -> dict:
        src = self.sources.get(url)
        if not src:
            k = len(self.sources) + 1
            src = self.sources[url] = {"n": k, "title": title or url, "url": url,
                                       "file": f"sources/S{k}.md"}
        p = self.folder / src["file"]
        p.parent.mkdir(parents=True, exist_ok=True)
        old = p.read_text(encoding="utf-8") if p.exists() else ""
        body = f"# [S{src['n']}] {src['title']}\n\n{url}\n\n{text}\n"
        if len(body) > len(old):
            atomic_write_text(p, body)
        rel = f"Output/{self.run_rel}/{src['file']}"
        if rel not in self.allowed:
            self.allowed.append(rel)
        return src

    def do_search(self, n, step):
        q, res = self.web.search(str(step.get("query") or ""))
        if not q:
            return {"status": "failed", "note": "no search was made", "what": "look up", "ctx": ""}
        lines = []
        for r in res[:8]:
            s = self._source_file(r.url, r.title, r.text) if r.url.startswith("http") else None
            lines.append(f"[S{s['n']}] {r.title} {r.url}\n{r.text[:400]}" if s else f"{r.title}\n{r.text[:400]}")
        ctx = f"Step {n}: searched '{q}', {len(res)} result(s):\n" + _data("\n\n".join(lines), CONTEXT_CHARS)
        return {"status": "done" if res else "failed", "note": f"'{q}': {len(res)} result(s)", "what": f"look up '{q}'",
                "ctx": ctx}

    def do_read(self, n, step):
        if step.get("url"):
            if "search" not in self.tpl["actions"] or not self.web.on:
                return {"status": "failed", "note": "this agent may not read pages online", "what": "read a page", "ctx": ""}
            page = self.web.read(str(step["url"]))
            if not page:
                return {"status": "failed", "note": "that page couldn't be read", "what": "read a page",
                        "ctx": f"Step {n}: couldn't read {str(step['url'])[:100]}"}
            s = self._source_file(page["url"], page["title"], page["text"])
            return {"status": "done", "note": page["url"][:100], "what": f"read [S{s['n']}]",
                    "ctx": f"Step {n}: read [S{s['n']}] {page['title']}:\n" + _data(page["text"], CONTEXT_CHARS)}
        rel = self.check_files([step.get("file", "")])
        if not rel:
            return {"status": "failed", "note": "not a file this agent may read", "what": "read a file", "ctx": ""}
        p = self.sb.root / rel[0]
        if p.suffix.lower() not in (".md", ".txt", ".csv", ".srt", ".vtt", ".html", ".json", ".ics"):
            return {"status": "failed", "note": f"{p.name} isn't a text file (use a tool on it)", "what": "read a file", "ctx": ""}
        if not rel[0].startswith(f"Output/{self.run_rel}/"):
            self.web.tainted = True
        text = p.read_text(encoding="utf-8", errors="replace")[:READ_CHARS]
        return {"status": "done", "note": p.name, "what": f"read {p.name}",
                "ctx": f"Step {n}: read {p.name}:\n" + _data(text, CONTEXT_CHARS)}

    def _run_step(self, n: int, text: str, what: str) -> dict:
        from . import tools as tools_mod
        from .engine import Stopped
        from .mission import MissionError, parse
        try:
            sm = parse(text)
        except MissionError as e:
            return {"status": "failed", "note": str(e)[:200], "what": what, "ctx": ""}
        sj = sm.jobs[0]
        if sj.tool:
            problem = tools_mod.needs_problem(self.engine.s, sj)
            if problem:
                raise Stuck(f"{self.names.get(sj.type, sj.type)} can't run on this PC yet: {problem}")
        before = set(agents._files_in(self.folder, self.sb))
        sst = self.engine._load_state(sm, sj)
        sst = self.engine._guard(sj, sst, self.engine.run_job, sm, sj, sst) or sst
        self.engine._mission = self.mission
        new = [f for f in agents._files_in(self.folder, self.sb) if f not in before]
        if sst.status == "stopped":
            raise Stopped()
        self.made += new
        self.allowed += ["Output/" + f for f in new if "Output/" + f not in self.allowed]
        ex = agents._excerpt(self.sb, new)
        return {"status": sst.status, "note": (sst.note or "")[:200], "what": what, "made": new,
                "ctx": f"Step {n}: {what}: {sst.status}" + (f"; made {', '.join(Path(m).name for m in new[:5])}" if new else "")
                       + (f"\n{ex}" if ex else "")}

    def do_write(self, n, step):
        inputs = list(dict.fromkeys(step.get("input") or []))
        srcs = [f"Output/{self.run_rel}/{s['file']}" for s in sorted(self.sources.values(), key=lambda x: x["n"])]
        inputs = (inputs + [s for s in srcs if s not in inputs])[:20]
        instr = str(step.get("instruction") or self.request)
        if srcs:
            instr += (" Use the sources given (files named S1, S2...): put the source number in brackets after a "
                      "fact, like [S2]. Don't invent sources; if the sources don't say, say so.")
        text = agents._step_mission(self.agent, n, "text", inputs, [], instr, self.run_rel, self.job.name,
                                    title=str(step.get("title") or ""))
        r = self._run_step(n, text, "write")
        if r["status"] in ("done", "partial") and self.sources:
            for m in r.get("made", []):
                if m.lower().endswith(".md"):
                    self._add_sources(self.sb.output / m)
        return r

    def _add_sources(self, p: Path) -> None:
        lines = ["", "## Sources", "", "Joe found these online while working. Check important facts against them."]
        lines += [f"- [S{s['n']}] [{s['title']}]({s['url']})" for s in sorted(self.sources.values(), key=lambda x: x["n"])]
        try:
            with open(p, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError:
            pass

    def do_tool(self, n, step):
        tool = step["tool"]
        if step["input"] and any(not i.startswith(f"Output/{self.run_rel}/") for i in step["input"]):
            self.web.tainted = True
        opts = step.get("options") or []
        opts = [str(o) for o in (opts if isinstance(opts, list) else [opts])][:6]
        text = agents._step_mission(self.agent, n, tool, step["input"], opts, str(step.get("instruction") or ""),
                                    self.run_rel, self.job.name, title=str(step.get("title") or ""))
        return self._run_step(n, text, self.names.get(tool, tool))

    def do_calendar(self, n, step):
        return self._run_step(n, agents._step_mission(self.agent, n, "calendar-file", [], [], str(step.get("instruction") or self.request),
                                                      self.run_rel, self.job.name, title="Calendar"), "calendar entry") \
            if "calendar-file" in self.tools else {"status": "failed", "note": "Dates and to-dos to my calendar isn't ticked", "what": "calendar", "ctx": ""}

    def do_propose(self, n, step):
        base = agents.agent_folder(self.sb, self.agent)
        base_rel = str(base.relative_to(self.sb.root)).replace("\\", "/") + "/"
        out, bad = [], []
        for c in (step.get("changes") or [])[:50]:
            if not isinstance(c, dict):
                continue
            src = self.check_files([c.get("from", "")])
            if not src or not src[0].startswith(base_rel):
                bad.append(str(c.get("from", ""))[:60])
                continue
            frm = src[0][len(base_rel):]
            to = clean_target(str(c.get("to", "")), Path(frm).suffix)
            if not to or to == frm:
                bad.append(frm)
                continue
            out.append({"from": frm, "to": to})
        if not out:
            return {"status": "failed", "note": "no usable suggestion" + (f" (left out: {', '.join(bad[:5])})" if bad else ""),
                    "what": "suggest names", "ctx": ""}
        seen = {c["from"] for c in out}
        self.proposed = [c for c in self.proposed if c["from"] not in seen] + out
        L = ["# Suggested names and folders", "",
             "Nothing has been changed. Open Tools > AGENTS and press APPLY to do these (it asks first, "
             "and UNDO puts everything back).", ""]
        L += [f"- {c['from']}  ->  {c['to']}" for c in self.proposed]
        p = self.folder / "PROPOSED CHANGES.md"
        atomic_write_text(p, "\n".join(L) + "\n")
        rel = str(p.relative_to(self.sb.output)).replace("\\", "/")
        if rel not in self.made:
            self.made.append(rel)
        agents.set_pending(self.agent["id"], self.run_rel, self.proposed)
        return {"status": "done", "note": f"{len(out)} suggestion(s), waiting for your OK", "what": "suggest names",
                "made": [rel], "ctx": f"Step {n}: suggested {len(out)} change(s) (waiting for the owner's OK)"}

    def _phone(self) -> tuple:
        c = self.engine.s.comfort
        return (c.ntfy_server, (c.ntfy_topic or "").strip())

    def do_send(self, n, step):
        if self.sent:
            return {"status": "failed", "note": "the digest was already sent in this run", "what": "send", "ctx": ""}
        if self.web.tainted:                   # nothing read from a file leaves the PC
            return {"status": "failed", "note": "not sent: this run read your files, and nothing from them goes out",
                    "what": "send", "ctx": ""}
        server, topic = self._phone()
        if not topic:
            return {"status": "failed", "note": "phone pings aren't set up (Setup > Display & sound)", "what": "send", "ctx": ""}
        last = next((m for m in reversed(self.made) if m.lower().endswith(".md")), "")
        if not last:
            return {"status": "failed", "note": "nothing written yet to send", "what": "send", "ctx": ""}
        body = (self.sb.output / last).read_text(encoding="utf-8", errors="replace")
        body = re.sub(r"(?s)\n## Sources.*", "", body).strip()[:1800]
        from . import notify
        err = notify.send_ntfy(server, topic, body, title=f"Joe: {self.agent['name']}")
        if err:
            return {"status": "failed", "note": f"didn't go out ({err})", "what": "send", "ctx": ""}
        self.sent = True
        return {"status": "done", "note": "sent to your phone", "what": "send to phone", "ctx": f"Step {n}: sent the digest to the phone"}

    def do_remind(self, n, step):
        if self.web.tainted:
            return {"status": "failed", "note": "not sent: this run read your files", "what": "reminder", "ctx": ""}
        from . import reminders
        text = re.sub(r"^\s*remind me\s+", "", " ".join(str(step.get("text", "")).split()))[:200]
        r = reminders.add(self.sb, self.engine.s, text)
        return {"status": "done" if r.get("ok") else "failed", "note": (r.get("say") or r.get("error") or "")[:200],
                "what": "reminder", "ctx": f"Step {n}: reminder: {(r.get('say') or r.get('error') or '')[:200]}"}

    def do_list(self, n, step):
        from . import reminders
        r = reminders.list_add(self.sb, str(step.get("list") or "shopping")[:40], str(step.get("things", ""))[:300])
        return {"status": "done" if r.get("ok") else "failed", "note": (r.get("say") or r.get("error") or "")[:200],
                "what": "list", "ctx": f"Step {n}: {(r.get('say') or r.get('error') or '')[:200]}"}

    def do_start(self, n, step):
        other = agents.get(str(step.get("agent", "")))
        if not other or other["id"] == self.agent["id"] or other["template"] == "assistant":
            return {"status": "failed", "note": "no other agent by that name", "what": "start an agent", "ctx": ""}
        if other.get("paused"):
            return {"status": "failed", "note": f"the {other['name']} agent is paused", "what": "start an agent", "ctx": ""}
        q = self.sb.missions / "Queue"
        q.mkdir(parents=True, exist_ok=True)
        req = "" if self.web.tainted else str(step.get("request") or "")
        name = f"agent-{other['id']}-{datetime.now():%Y%m%d-%H%M%S}.txt"
        atomic_write_text(q / name, agents.mission_text(other, None, req) + "\n")
        return {"status": "done", "note": f"queued the {other['name']} agent", "what": f"start {other['name']}",
                "ctx": f"Step {n}: queued the {other['name']} agent"}

    # -- Joe's own check after every step, the reset rule ------------------
    def tick_off(self) -> None:
        open_pts = [(i, p) for i, p in enumerate(self.plan, 1) if not p["done"]]
        if not open_pts:
            return
        found = [f"- searched '{s['query']}' ({len(s['results'])} results)" for s in self.web.searches]
        found += [f"- read [S{s['n']}] {s['title']}" for s in self.sources.values() if s["url"] in self.web.pages]
        found += [f"- {x['what']}: {x['status']} ({x['note'][:120]})" for x in self.steps if x["action"] in ("send", "remind", "list", "start", "propose")]
        ex = agents._excerpt(self.sb, [m for m in self.made if m.lower().endswith((".md", ".txt", ".csv"))][-3:])
        d = None
        try:
            d = self.ask(TICK_SYS + " " + RULES + " Judge only by what was made and done. Reply with ONLY JSON: "
                         '{"done": [<numbers of the points that are now fully done>]}',
                         f"The owner's job:\n{self.request}\n\nThe plan:\n{self.plan_text()}\n\nDone so far:\n" +
                         ("\n".join(found) or "(no lookups)") + "\n\nFiles made: " +
                         (", ".join(Path(m).name for m in self.made) or "(none)") + (f"\n\nExcerpts:\n{ex}" if ex else ""), 120)
        except Exception:                              # noqa: BLE001 (no tick this time)
            return
        for k in (d or {}).get("done") or []:
            try:
                i = int(k)
            except (TypeError, ValueError):
                continue
            if 1 <= i <= len(self.plan) and not self.plan[i - 1]["done"]:
                self.plan[i - 1]["done"] = True
                self.log(f"  Done: point {i} ({self.plan[i - 1]['point'][:80]})")

    def all_done(self) -> bool:
        return bool(self.plan) and all(p["done"] for p in self.plan)

    def do_checkpoint(self, n: int, why: str) -> None:
        """THE RESET RULE: write down where we are, throw the working context away, start clean."""
        self.checkpoints += 1
        done_lines = [f"- step {x['n']} {x['what']}: {x['status']}" + (f" ({x['note'][:100]})" if x["note"] else "")
                      for x in self.steps]
        review = None
        try:
            review = self.ask(REVIEW_SYS + " Re-read the owner's job and compare the progress with it. Is the work "
                              "still on the job, or has it drifted onto something else? Reply with ONLY JSON: "
                              '{"on_track": true|false, "note": "<one sentence: what to do next to stay on the job>"}',
                              f"The owner's job:\n{self.request}\n\nThe plan:\n{self.plan_text()}\n\nSteps so far:\n" +
                              "\n".join(done_lines[-12:]), 150)
        except Exception:                              # noqa: BLE001
            pass
        note = " ".join(str((review or {}).get("note") or "").split())[:240]
        off = (review or {}).get("on_track") is False
        left = [p["point"] for p in self.plan if not p["done"]]
        self.checkpoint = "\n".join(
            [f"Checkpoint {self.checkpoints} (after step {n}; {why}).",
             f"The owner's job: {self.request}", "The plan:", self.plan_text(),
             "Done:", *(done_lines[-10:] or ["- nothing yet"]),
             "Files made: " + (", ".join(self.made[-10:]) or "none"),
             "Sources found: " + str(len(self.sources)),
             "Left: " + ("; ".join(left) or "nothing")] +
            ([("OFF THE JOB: " if off else "Next: ") + note] if note else []))
        self.context = []                              # thrown away: the next step starts clean
        self.log(f"Checkpoint {self.checkpoints} ({why}): wrote down where I am, cleared my working notes and "
                 "restarted from the job and this checkpoint." + (f" Off the job: {note}" if off else ""))
        self.write_notes()

    def write_notes(self) -> None:
        L = [f"# Agent notes: {self.agent['name']}", "", "## The job", "", self.request, "", "## The plan", "", self.plan_text()]
        if self.checkpoint:
            L += ["", "## Latest checkpoint", "", self.checkpoint]
        try:
            atomic_write_text(self.folder / "AGENT NOTES.md", "\n".join(L) + "\n")
        except OSError:
            pass

    # -- the fact check ------------------------------------------------------
    def fact_check(self) -> None:
        texts = [m for m in self.made if m.lower().endswith(".md") and not m.endswith("PROPOSED CHANGES.md")]
        if not texts or not self.web.on:
            return
        target = self.sb.output / texts[-1]
        body = target.read_text(encoding="utf-8", errors="replace")
        main = re.sub(r"(?s)\n## Sources.*", "", body)
        self.live("checking facts")
        try:
            d = self.ask(CLAIMS_SYS + " " + RULES + " List the facts in it that can be checked: numbers, dates, "
                         "names, prices, places. Copy each one exactly as written. Reply with ONLY JSON: "
                         '{"claims": [{"claim": "<exact words from the text>", "search": "<a few search words>"}]}',
                         _data(main, 6000), 600)
        except Exception:                              # noqa: BLE001
            d = None
        claims = [c for c in ((d or {}).get("claims") or []) if isinstance(c, dict) and str(c.get("claim", "")).strip()]
        for i, c in enumerate(claims[:MAX_CLAIMS], 1):
            if self.engine.stop.is_set() or time.monotonic() > self.deadline:
                break
            claim = " ".join(str(c["claim"]).split())[:300]
            self.live(f"checking facts ({i} of {min(len(claims), MAX_CLAIMS)})")
            q, res = self.web.search(str(c.get("search") or claim))
            verdict, src, fix = "not found", "", ""
            if res:
                ctx = "\n\n".join(f"[{k}] {r.title} ({r.url})\n{r.text[:800]}" for k, r in enumerate(res[:5], 1))
                try:
                    v = self.ask(VERDICT_SYS + " " + RULES + ' Reply with ONLY JSON: {"verdict": "confirmed" | '
                                 '"not found" | "contradicted", "source": <number of the result>, "correct": '
                                 '"<what the sources say instead, if contradicted>"}',
                                 f"The claim: {claim}\n\nWhat was found:\n{_data(ctx, 4500)}", 150)
                except Exception:                      # noqa: BLE001
                    v = None
                verdict = str((v or {}).get("verdict") or "not found").lower().strip()
                if verdict not in ("confirmed", "not found", "contradicted"):
                    verdict = "not found"
                try:
                    k = int((v or {}).get("source") or 0)
                except (TypeError, ValueError):
                    k = 0
                if 1 <= k <= len(res):
                    src = res[k - 1].url
                fix = " ".join(str((v or {}).get("correct") or "").split())[:200]
            self.facts.append({"claim": claim, "verdict": verdict, "source": src, "correct": fix, "query": q})
            if verdict == "contradicted" and claim in main:
                mark = f"{claim} [CHECK: the sources say {fix}]" if fix else f"{claim} [CHECK]"
                main = main.replace(claim, mark, 1)
        if any(f["verdict"] == "contradicted" for f in self.facts):
            atomic_write_text(target, main + body[len(re.sub(r"(?s)\n## Sources.*", "", body)):])
        self.log(f"Fact check: {len(self.facts)} checked, "
                 f"{sum(f['verdict'] == 'confirmed' for f in self.facts)} confirmed, "
                 f"{sum(f['verdict'] == 'contradicted' for f in self.facts)} contradicted.")

    # -- the whole run -------------------------------------------------------
    def go(self) -> str:
        """Returns '' when the job is done, else why I got stuck."""
        from .engine import Stopped
        if not self.engine._text_ready(self.st):
            raise Stuck("the writing model isn't running, and I need it to plan and pick my steps.")
        self.live("making a plan")
        self.make_plan()
        n, since_reset, fails_in_row, bad_answers, last_key = 0, 0, 0, 0, ""
        fix_note, pushed_done, finish_asked, quality_left = "", False, False, 1
        while True:
            if self.engine.stop.is_set():
                raise Stopped()
            if time.monotonic() > self.deadline:
                raise Stuck(f"I ran out of time ({self.agent['minutes']} minutes).")
            if self.all_done() or finish_asked:
                if not self.all_done():
                    left = [p["point"] for p in self.plan if not p["done"]]
                    raise Stuck("I was told the job was done, but these points of the plan aren't: " + "; ".join(left)[:400])
                miss = agents.quality_check(self.engine, self.agent, self.request, self.made) if self.made and quality_left else ""
                if not (miss and n < self.agent["steps"]):
                    return ""
                quality_left -= 1
                fix_note, finish_asked = miss, False
                self.steps.append({"n": n, "action": "check", "what": "quality check", "status": "sent back",
                                   "note": miss, "made": []})
                self.plan.append({"point": miss, "done": False})
                self.log(f"  Quality check sent it back: {miss}")
            if n >= self.agent["steps"]:
                left = [p["point"] for p in self.plan if not p["done"]]
                raise Stuck(f"I used all {self.agent['steps']} steps before the job was done" +
                            (f" (still to do: {'; '.join(left)[:300]})." if left else "."))
            if n and (since_reset >= RESET_EVERY or fails_in_row >= 2):
                self.do_checkpoint(n, "a step failed twice" if fails_in_row >= 2 else f"every {RESET_EVERY} steps")
                since_reset, fails_in_row = 0, 0
            self.live("picking the next step", n + 1)
            try:
                step = self.pick(fix_note)
            except Exception as e:                     # noqa: BLE001
                raise Stuck(f"I couldn't reach the writing model to pick my next step ({e}).") from None
            if step is None:
                bad_answers += 1
                if bad_answers >= 2:
                    raise Stuck("twice I couldn't work out a next step I'm allowed to take.")
                continue
            if step.get("done"):
                left = [p["point"] for p in self.plan if not p["done"]]
                if left and not pushed_done:
                    pushed_done = True
                    fix_note = "these points of the plan aren't done yet: " + "; ".join(left)[:400]
                    self.log("  The model said done, but not every point is: sent back once.")
                    continue
                if not self.made and not self.steps:
                    raise Stuck("I was told the job was done before I did anything.")
                finish_asked = True
                continue
            fix_used, fix_note = fix_note, ""
            key = json.dumps({k: v for k, v in step.items() if k not in ("title",)}, sort_keys=True, default=str)[:600]
            if key == last_key and not fix_used:
                raise Stuck(f"I was about to do the same step again ({step['action']}).")
            last_key = key
            n += 1
            since_reset += 1
            self.live(ACTIONS[step["action"]][0].split(" (")[0], n)
            self.log(f"  Agent step {n}: {step['action']}")
            r = self.do(n, step)
            self.steps.append({"n": n, "action": step["action"], "what": r.get("what", step["action"]),
                               "status": r["status"], "note": r.get("note", ""), "made": r.get("made", [])})
            if r.get("ctx"):
                self.context.append(r["ctx"])
            if r["status"] == "failed":
                fails_in_row += 1
                last_key = ""                          # a failed step may be tried once more
                continue
            fails_in_row = 0
            self.tick_off()                            # Joe's own check BEFORE asking for another step

    def report(self, stuck: str) -> Path:
        mins = (time.monotonic() - self.t0) / 60
        a = self.agent
        L = [f"# Agent report: {a['name']} ({self.tpl['name']})", "", f"Job: {self.request}", "",
             f"Finished {datetime.now():%Y-%m-%d %H:%M}, {len([x for x in self.steps if x['action'] != 'check'])} step(s), "
             f"{mins:.1f} minutes" + (f", {self.checkpoints} checkpoint(s)" if self.checkpoints else "") + ".", ""]
        if stuck:
            L += ["## I got stuck", "", stuck, "", "What would help:"]
            low = stuck.lower()
            if "time" in low:
                L.append("- Give me more minutes (Tools > AGENTS > EDIT), or a smaller job.")
            if "steps" in low or "same step" in low or "work out" in low:
                L.append("- Say the job more exactly, or split it in two. A higher step limit helps a long job.")
            if "can't run on this pc" in low or "model isn't running" in low:
                L.append("- Setup (F10) > System check can install what's missing.")
            L += ["- Or run the steps yourself from the Tools tab.", ""]
        L += ["## The plan", ""] + [f"- [{'x' if p['done'] else ' '}] {p['point']}" for p in self.plan] + [""]
        L += ["## Steps", ""]
        for x in self.steps:
            L.append(f"- Step {x['n']}, {x['what']}: {x['status']}" + (f" — {x['note']}" if x["note"] else ""))
            for m in x["made"][:20]:
                L.append(f"    - {m}")
        if not self.steps:
            L.append("- (none)")
        L += ["", "## Looked up online", ""]
        if not self.web.on:
            why = ("it's off for this agent" if not agents.ability_on(a, "lookups") else
                   "Setup > Voice & Talk > Let Joe look things up online is off")
            L.append(f"- Nothing: looking things up online is off ({why}). No search or page went out.")
        else:
            L += [f"- '{s['query']}': {len(s['results'])} result(s)" for s in self.web.searches] or ["- No searches were needed."]
            if self.web.tainted:
                L.append("- This run read your files, so every search used only words from the job you typed.")
        if self.sources:
            L += ["", "## Sources", ""] + [f"- [S{s['n']}] [{s['title']}]({s['url']})"
                                           for s in sorted(self.sources.values(), key=lambda x: x["n"])]
        L += ["", "## Facts checked", ""]
        if not self.web.on:
            L.append("Nothing was checked online: looking things up is off for this run. Treat numbers, dates, "
                     "names and prices as unchecked.")
        elif not self.facts:
            L.append("No checkable facts were found in what was written (or there was no time left to check).")
        else:
            mark = {"confirmed": "confirmed", "not found": "not found (couldn't confirm it)", "contradicted": "CONTRADICTED"}
            for f in self.facts:
                L.append(f"- {mark[f['verdict']]}: {f['claim']}" + (f" — sources say: {f['correct']}" if f["correct"] else "")
                         + (f" ({f['source']})" if f["source"] else ""))
        if self.proposed:
            L += ["", "## Waiting for your OK", "", f"{len(self.proposed)} suggested name(s) or folder(s): see PROPOSED "
                  "CHANGES.md. Nothing has changed yet. Tools > AGENTS > APPLY does them (it asks first; UNDO puts them back)."]
        L += ["", f"Files made: {len(self.made)}. Nothing was deleted; everything is in this folder. "
                  "AGENT LOG.txt lists every step Joe took.", ""]
        rep = self.folder / "AGENT REPORT.md"
        atomic_write_text(rep, "\n".join(L))
        return rep


def clean_target(to: str, ext: str) -> str:
    """A suggested 'Folder/New name.ext' inside the agent's folder: at most one folder deep, no '..',
    names Windows accepts, the file's own extension kept."""
    from .filing import clean_name
    raw = [p.strip() for p in re.split(r"[\\/]+", to or "")]
    if any(p in (".", "..") for p in raw):
        return ""
    parts = [p for p in raw if p]
    if not parts or len(parts) > 2:
        return ""
    stem = clean_name(re.sub(r"\.[A-Za-z0-9]{1,5}$", "", parts[-1]), 80)
    folder = clean_name(parts[0], 40) if len(parts) == 2 else ""
    if not stem or (len(parts) == 2 and not folder) or stem.startswith(("_", ".")):
        return ""
    return (f"{folder}/" if folder else "") + stem + ext


def run(engine, mission, job, st):
    """The engine's hook for TYPE: agent (agents.run calls this)."""
    from .engine import Stopped
    agent = agents.get(job.options[0] if job.options else "")
    if agent is None:
        st.status, st.note = "failed", "That agent doesn't exist any more (Tools > AGENTS)."
        engine._save_state(job, st)
        return st
    if agent.get("paused"):
        st.status, st.note = "skipped", f"The {agent['name']} agent is paused."
        engine._save_state(job, st)
        return st
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    r = Run(engine, mission, job, st, agent)
    engine._save_state(job, st)
    r.log(f"Agent '{agent['name']}' ({r.tpl['name']}): up to {agent['steps']} steps and {agent['minutes']} min. "
          f"May: {', '.join(r.actions)}. Looking things up: {'on' if r.web.on else 'off'}.")
    stuck = ""
    try:
        try:
            stuck = r.go()
        except Stuck as e:
            stuck = str(e)
        if r.made and not r.engine.stop.is_set() and time.monotonic() < r.deadline:
            r.fact_check()
    except Stopped:
        st.status, st.note = "stopped", "stopped (the run was stopped)"
        r.report("The run was stopped before I finished.")
        engine._save_state(job, st)
        agents.live_clear()
        raise
    except Exception:
        agents.live_clear()
        raise
    report = r.report(stuck)
    failed_all = r.steps and all(x["status"] == "failed" for x in r.steps if x["action"] != "check")
    st.status = "failed" if (stuck and not r.made) or (failed_all and not r.made) else ("partial" if stuck else "done")
    if stuck and not r.made and r.steps and any(x["status"] == "done" for x in r.steps):
        st.status = "partial"
    st.note = (f"I got stuck: {stuck}" if stuck else f"{len(r.made)} file(s) made") + f" (see {report.name})"
    st.items = len(r.made)
    st.titles = [Path(m).name for m in r.made[:200]]
    st.finished = datetime.now().isoformat(timespec="seconds")
    st.parts_done = st.parts_total = 1
    engine._save_state(job, st)
    agents._note_run(agent["id"], {"when": st.finished, "status": st.status, "folder": r.run_rel, "note": st.note[:200],
                                    "plan": [p["point"] for p in r.plan], "done": sum(p["done"] for p in r.plan)})
    r.log(f"Agent '{agent['name']}' {st.status}: {st.note}")
    agents.live_clear()
    return st
