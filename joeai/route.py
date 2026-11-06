"""One box for everything: decide what a short, plain message wants before any AI runs.

  command -> something Joe does right away (run, stop, open a screen...); no model needed
  chat    -> a question or small talk: Joe answers in Talk
  plan    -> work to be made: Joe drafts a plan to check and RUN
  unclear -> too short to tell: Joe suggests what to say

People type the shortest thing that comes to mind ("go", "pics", "stop it", "?"), so the
commands accept many spellings. Anything longer or unknown goes to the AI as before.
"""
from __future__ import annotations

import re

# command id -> words/phrases that mean it (the whole message, ignoring "please", "joe", punctuation)
COMMANDS: dict[str, tuple[str, ...]] = {
    "run": ("run", "go", "start", "run it", "do it", "start it", "go ahead", "begin", "start the run",
            "run the plan", "make it", "do the plan", "start working", "get to work", "f5"),
    "stop": ("stop", "pause", "halt", "cancel", "stop it", "stop the run", "quit it", "enough"),
    "help": ("help", "?", "??", "what can you do", "how does this work", "commands", "help me",
             "how do i use this", "what do i do", "instructions", "guide", "f1"),
    "report": ("report", "results", "morning report", "the report", "show report", "what did you make",
               "what did you do", "show results", "f8"),
    "files": ("files", "my files", "output", "pics", "pictures", "photos", "images", "videos", "folder",
              "open folder", "show files", "show pictures", "show my files", "f7"),
    "tools": ("tools", "tool", "show tools", "f3"),
    "setup": ("setup", "set up", "settings", "options", "preferences", "config", "f10"),
    "check": ("check", "system check", "check my pc", "check my computer", "is everything ok",
              "fix", "fix it", "fix joe", "repair", "doctor"),
    "updates": ("update", "updates", "check for updates", "update everything", "update joe",
                "update models", "upgrade"),
    "new": ("new", "new chat", "clear", "start over", "reset", "fresh start"),
    "talk": ("talk", "chat", "let's talk", "f4"),
    "builder": ("builder", "build", "step by step", "f6"),
    "stats": ("stats", "statistics", "storage", "space", "how much space", "f9"),
}
_LOOKUP = {p: cid for cid, ps in COMMANDS.items() for p in ps}

_FILLER = re.compile(r"\b(please|pls|plz|joe|hey|ok|okay|now|can you|could you|would you|just|the)\b", re.I)
_GREETING = re.compile(r"^(hi|hey|hello|yo|sup|thanks|thank you|thx|ty|good (morning|night|evening)|"
                       r"how are you|who are you|what are you|bye|goodbye|lol|cool|nice|great|ok|okay)\b", re.I)
_QUESTION = re.compile(r"^(what|whats|what's|why|how|who|when|where|which|is|are|was|were|do|does|did|"
                       r"can|could|should|would|will|tell me|explain|describe what|define)\b", re.I)
_WORK = re.compile(r"\b(make|write|create|draw|draft|generate|build|design|turn|convert|fix|restore|"
                   r"remove|edit|translate|transcribe|proofread|resize|sort|tag|list|give me|i need|"
                   r"i want|need|want|produce|render|animate|summari[sz]e|tidy|clean up|read .* aloud)\b",
                   re.I)


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"[!.,;:]+$", "", t).strip()
    if t in _LOOKUP:
        return t
    t2 = _FILLER.sub(" ", t)
    return re.sub(r"\s+", " ", re.sub(r"[!.,;:]+", " ", t2)).strip()


_PARK = re.compile(r"^\s*(?:please\s+)?(?:park\s+(?:this|that|it|an?\s+idea|idea|the\s+idea|this\s+idea)\b|"
                   r"park\s*(?=[:\-])|save (?:this|an?) idea|idea for later|note (?:this )?for later)"
                   r"\s*[:\-,]?\s*(.*)$", re.I | re.S)


def classify(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {"kind": "unclear", "say": "Tell Joe what you need, in your own words."}
    pm = _PARK.match(raw)
    if pm and (pm.group(1).strip() or raw.lower().strip(" .!") in ("park this", "park that", "park it")):
        return {"kind": "command", "cmd": "park", "idea": pm.group(1).strip()}
    n = _norm(raw)
    if raw.strip().lower() in _LOOKUP:
        return {"kind": "command", "cmd": _LOOKUP[raw.strip().lower()]}
    if n in _LOOKUP:
        return {"kind": "command", "cmd": _LOOKUP[n]}
    words = n.split()
    if _GREETING.match(n or raw.lower()) and len(words) <= 5:
        return {"kind": "chat"}
    if raw.endswith("?") or (_QUESTION.match(raw) and not _WORK.search(raw)):
        return {"kind": "chat"}
    if len(raw) < 4 or (len(words) <= 1 and not _WORK.search(raw)):
        return {"kind": "unclear", "say": unclear_hint(raw)}
    return {"kind": "plan"}


def unclear_hint(word: str) -> str:
    return (f"I'm not sure what \"{word.strip()[:30]}\" means yet. Try a few more words, like "
            "\"20 captions for my candle shop\", \"fix my old photo\" or \"what can you do?\". "
            "Short words work too: go, stop, help, report, files, tools.")
