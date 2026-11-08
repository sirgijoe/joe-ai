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
    "help": ("help", "?", "??", "how does this work", "commands", "help me",
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
    "hush": ("stop talking", "be quiet", "quiet", "shh", "shhh", "shush", "hush", "stop reading", "shut up",
             "that's enough talking", "quiet please", "mute", "stop speaking"),
    "repeat": ("say that again", "repeat that", "repeat", "repeat it", "what did you say", "come again",
               "pardon", "say again", "say it again", "one more time", "huh"),
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


_HEY = r"^\s*(?:(?:hey|ok|okay)\s+)?(?:joe[,!]?\s+)?(?:please\s+|can you\s+|could you\s+)?"
_REMIND = re.compile(_HEY + r"(?:remind (?:me|us)\b|(?:set|make|add|create) (?:me )?a reminder\b(?:\s+(?:for|to))?|"
                     r"(?:don'?t|do not) let me forget\b|reminder:|"
                     r"(?:ping|text|message|notify|alert|buzz)\s+(?:me|my phone)(?:\s+on my phone)?\b(?=.*\b(?:in|at|tomorrow|tonight|today|noon|midnight|on (?:mon|tue|wed|thu|fri|sat|sun))\b)|"
                     r"send (?:me )?a (?:ping|text|notification|message)(?: to my phone)?\b(?=.*\b(?:in|at|tomorrow|tonight|today)\b))"
                     r"\s*(.*?)[.!?]*$", re.I | re.S)
_LIST = r"(?:my\s+|the\s+)?(?:([a-z][a-z -]{0,20}?)\s+)?list"
_LIST_ADD = re.compile(_HEY + r"(?:add|put)\s+(.+?)\s+(?:to|on)\s+" + _LIST + r"[.!?]*$", re.I)
_LIST_DONE = re.compile(_HEY + r"(?:take|cross|remove|delete|check)\s+(.+?)\s+off(?:\s+of)?\s+" + _LIST + r"[.!?]*$", re.I)
_LIST_SHOW = re.compile(_HEY + r"(?:what(?:'s| is)\s+on|read(?:\s+me)?|show(?:\s+me)?)\s+" + _LIST + r"[.!?]*$", re.I)
_LIST_SEND = re.compile(_HEY + r"send\s+" + _LIST + r"\s+to\s+my\s+phone[.!?]*$", re.I)


_DIRECTIONS = re.compile(_HEY + r"(?:give me\s+|get\s+|show me\s+)?(?:directions|the way|a route|route)\s+to\s+(.+?)[.!?]*$|"
                         + _HEY + r"(?:how (?:do|can) i get|navigate|take me)\s+to\s+(.+?)[.!?]*$", re.I)
_SHOP = re.compile(_HEY + r"(?:where (?:can|do|should) i (?:buy|get|find)|shop for|find (?:me )?(?:a |an |the )?(?:cheap |best )?deal on|"
                   r"(?:find|look up) (?:the )?(?:price|prices) (?:of|for)|compare prices (?:of|for|on))\s+(.+?)[.!?]*$", re.I)


def assistant(raw: str) -> dict | None:
    """Reminders and lists ("remind me at 3 to...", "add milk to my shopping list"), directions and shopping."""
    m = _DIRECTIONS.match(raw)
    if m:
        return {"kind": "command", "cmd": "directions", "text": (m.group(1) or m.group(2) or "").strip()}
    m = _SHOP.match(raw)
    if m:
        return {"kind": "command", "cmd": "shop", "text": m.group(1).strip()}
    m = _REMIND.match(raw)
    if m:
        return {"kind": "command", "cmd": "remind", "text": m.group(1).strip()}
    for rx, cmd in ((_LIST_SEND, "list-send"), (_LIST_SHOW, "list-show")):
        m = rx.match(raw)
        if m:
            return {"kind": "command", "cmd": cmd, "list": (m.group(1) or "").strip()}
    for rx, cmd in ((_LIST_ADD, "list-add"), (_LIST_DONE, "list-done")):
        m = rx.match(raw)
        if m:
            return {"kind": "command", "cmd": cmd, "items": m.group(1).strip(), "list": (m.group(2) or "").strip()}
    return None


_ASKQ = r"^\s*(?:(?:hey|ok|okay)\s+)?(?:joe[,!]?\s+)?(?:please\s+)?(?:tell me\s+|do you know\s+)?"
_TIME = re.compile(_ASKQ + r"(?:what(?:'s| is)?\s+the\s+time|what time is it|the time)(?:\s+(?:now|right now))?[?.!]*$", re.I)
_DATE = re.compile(_ASKQ + r"(?:what(?:'s| is)?\s+(?:the\s+)?(?:date|day)(?:\s+(?:is it\s+)?today|\s+is it)?|"
                   r"what day is it(?: today)?|today'?s date)[?.!]*$", re.I)
_MATH = re.compile(_ASKQ + r"(?:what(?:'s| is)\s+|calculate\s+|how much is\s+)?([\d\s.,+\-*/x()%^]+|.*?\d.*?)[?=.!]*$", re.I)
_MATH_WORDS = ((r"\bplus\b", "+"), (r"\bminus\b", "-"), (r"\b(?:times|multiplied by)\b", "*"),
               (r"\bdivided by\b", "/"), (r"\bover\b", "/"), (r"(?<=\d)\s*x\s*(?=\d)", "*"), (r"\^", "**"))


def _calc(expr: str) -> float | None:
    """Plain arithmetic only ("12 times 7", "15% of 80", "(3+4)*2"); None for anything else."""
    import ast
    import operator as op
    e = expr.lower().replace(",", "")
    m = re.fullmatch(r"\s*([\d.]+)\s*%\s*of\s*([\d.]+)\s*", e) or re.fullmatch(r"\s*([\d.]+)\s*percent\s*of\s*([\d.]+)\s*", e)
    if m:
        return float(m.group(1)) * float(m.group(2)) / 100
    for rx, sym in _MATH_WORDS:
        e = re.sub(rx, sym, e)
    if not re.fullmatch(r"[\d\s.+\-*/()]+", e) or not re.search(r"\d\s*(?:\*\*|[+\-*/])\s*[\d(]", e):
        return None
    ops = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.Pow: op.pow,
           ast.USub: op.neg, ast.UAdd: op.pos}

    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in ops:
            if isinstance(n.op, ast.Pow) and abs(ev(n.right)) > 100:
                raise ValueError("too big")
            return ops[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in ops:
            return ops[type(n.op)](ev(n.operand))
        raise ValueError("not arithmetic")
    try:
        return float(ev(ast.parse(e.strip(), mode="eval").body))
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
        return None


def _num(x: float) -> str:
    return f"{x:,.0f}" if abs(x - round(x)) < 1e-9 and abs(x) < 1e15 else f"{x:,.4f}".rstrip("0").rstrip(".")


def quick(raw: str, now=None) -> dict | None:
    """Answers Joe knows without any AI or internet: the time, today's date, plain arithmetic."""
    from datetime import datetime
    now = now or datetime.now()
    if _TIME.match(raw):
        return {"kind": "command", "cmd": "quick", "say": "It's " + now.strftime("%I:%M %p").lstrip("0") + "."}
    if _DATE.match(raw):
        return {"kind": "command", "cmd": "quick", "say": "Today is " + now.strftime("%A, %B ") + str(now.day) + now.strftime(", %Y") + "."}
    m = _MATH.match(raw)
    if m:
        v = _calc(m.group(1))
        if v is not None:
            return {"kind": "command", "cmd": "quick", "say": f"{m.group(1).strip()} = {_num(v)}"}
    return None


def classify(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {"kind": "unclear", "say": "Tell Joe what you need, in your own words."}
    hit = assistant(raw) or quick(raw)
    if hit:
        return hit
    pm = _PARK.match(raw)
    if pm and (pm.group(1).strip() or raw.lower().strip(" .!") in ("park this", "park that", "park it")):
        return {"kind": "command", "cmd": "park", "idea": pm.group(1).strip()}
    from . import abilities                     # "what can you do?" / "how does restore photo work?"
    ab = abilities.answer(raw)
    if ab:
        return ({"kind": "command", "cmd": "abilities"} if ab["kind"] == "overview"
                else {"kind": "command", "cmd": "explain", "id": ab["id"]})
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
