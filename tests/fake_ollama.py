"""A fake Ollama server for tests: no GPU or model needed."""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeOllama:
    def __init__(self, fail_first: int = 0, dup_every: int = 3, short_every: int = 4):
        self.fail_first = fail_first
        self.dup_every = dup_every
        self.short_every = short_every
        self.calls = 0
        self.embeds = 0
        self.requests: list[dict] = []     # every /api/chat body, newest last
        self.counter = 0
        self.prompts: list[str] = []
        self.systems: list[str] = []
        self.lock = threading.Lock()
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/version":
                    self._send(200, {"version": "0.fake"})
                elif self.path == "/api/tags":
                    self._send(200, {"models": [{"name": "qwen3:14b"}]})
                elif self.path == "/api/ps":
                    self._send(200, {"models": [{"name": "qwen3:14b", "size": 10, "size_vram": 10}]})
                else:
                    self._send(404, {})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/api/embed":                 # word-hash vectors: same words, close vectors
                    vecs = []
                    for t in req["input"]:
                        v = [0.0] * 64
                        for w in re.findall(r"\w+", t.lower()):
                            if len(w) > 3:
                                v[sum(map(ord, w)) % 64] += 1.0
                        vecs.append(v)
                    fake.embeds += len(req["input"])
                    self._send(200, {"embeddings": vecs})
                    return
                if self.path == "/api/generate":
                    self._send(200, {"done": True})
                elif self.path == "/api/chat":
                    code, obj = fake.chat(req)
                    self._send(code, obj)
                else:
                    self._send(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()

    def _reply(self, text):
        return {"message": {"role": "assistant", "content": text},
                "prompt_eval_count": 50, "eval_count": 80, "total_duration": 1_000_000_000}

    def _csv(self, user):
        import json as _j
        m = re.search(r"Write (?:exactly|only) (\d+)", user)
        want = int(m.group(1)) if m else 4
        cols = re.search(r"^CSV COLUMNS \(\d+\): (.+)$", user, re.M).group(1).split(",")
        out = ["```json"]
        for i in range(want):
            self.counter += 1
            c = self.counter
            if c % 5 == 0:
                out.append('{"name": "broken row, ')               # bad JSON
                continue
            row = {cols[0]: "same-every-row"}                       # like Type=simple
            for col in cols[1:]:
                row[col] = f"Round {c}" if col == "name" else f"30-06, Springfield {c}"
            out.append(_j.dumps(row))
        out.append("```")
        return self._reply("\n".join(out))

    def _guided(self, user):
        self.counter += 1
        c = self.counter
        short = "too short" not in user and c % 2 == 1      # first try short, retry long
        n = 10 if short else 70
        body = " ".join(["detail"] * n)
        text = (f"Sure! Here is the part.\n\n## Section {c}\n\n### Feature {c}a\n\n{body} [CHECK: value]"
                f"\n\n### Feature {c}b\n\n{body}\n\n| col | val |\n|---|---|\n| a | 1 |")
        return self._reply(text)

    def chat(self, req):
        with self.lock:
            self.calls += 1
            self.requests.append(req)
            if self.calls <= self.fail_first:
                return 500, {"error": "simulated crash"}
            user = req["messages"][-1]["content"]
            self.prompts.append(user)
            self.systems.append(req["messages"][0]["content"])
            if req["messages"][0]["content"].startswith("You write clear notes from a transcript"):
                return 200, self._reply("## Summary\nThe team planned the mug launch.\n## Key points\n"
                                        "- Ship on Friday\n## Decisions\n- Price list update [CHECK]\n"
                                        "## To-dos\n- Sam: update the price list")
            sysmsg = req["messages"][0]["content"]
            seen = req["messages"][-1].get("images")
            if sysmsg.startswith("You write shop listings from product photos"):
                if not seen:
                    return 200, self._reply("no picture?")
                name = re.search(r"file: ([^)]+)\)", user).group(1)
                if "blurry" in name:
                    return 200, self._reply("I can't tell what this is.")
                return 200, self._reply(json.dumps({"title": f"Blue mug ({name})", "description":
                    "A blue glazed mug with a round handle. Size [CHECK].", "tags": ["mug", "blue", "handmade"],
                    "alt_text": "A blue mug on a wooden table."}))
            if sysmsg.startswith("You read text from pictures"):
                if "receipt or invoice" in user:
                    return 200, self._reply(json.dumps({"date": "2026-03-02", "store": "Corner Shop", "total": "$12.50",
                        "tax": "$0.75", "currency": "$", "items": [{"name": "Milk", "price": "$3.00"},
                                                                   {"name": "Br[CHECK]ad", "price": "$9.50"}]}))
                if "Copy the table" in user and "sign" in user:
                    return 200, self._reply(json.dumps({"columns": [], "rows": []}))   # a sign has no table
                if "Copy the table" in user:
                    return 200, self._reply(json.dumps({"columns": ["Name", "Qty"], "rows": [["Mugs", "4"], ["Bowls", "2", "extra"]]}))
                return 200, self._reply(json.dumps({"text": "# Notice\n\nOpen 9 to 5. Closed S[CHECK]day."}))
            if sysmsg.startswith("You sort photos"):
                name = re.search(r"file: ([^)]+)\)", user).group(1)
                cat = "dogs" if "dog" in name.lower() else ("Beach days" if "beach" in name else "Food")
                if "Pick the category from this list" in user and cat == "Food":
                    cat = "Snacks"                                        # not on the list: flagged
                return 200, self._reply(json.dumps({"category": cat, "tags": [cat.lower(), "photo"],
                                                    "caption": f"A photo of {cat.lower()}."}))
            if sysmsg.startswith("You answer questions using ONLY the numbered excerpts"):
                ex = user.split("EXCERPTS:", 1)[1]
                q = user.split("QUESTION:", 1)[1].split("\n", 1)[0].lower()
                for block in re.split(r"\n\n(?=EXCERPT \[\d+\] \()", ex.strip()):
                    n = re.match(r"EXCERPT \[(\d+)\]", block).group(1)
                    hit = re.search(r"(refunds[^.]*\.)", block, re.I) if "refund" in q else None
                    if hit:
                        return 200, self._reply(f"The documents say: {hit.group(1)} [{n}]")
                return 200, self._reply("The documents don't seem to say.")
            if sysmsg.startswith("You summarize the person's document"):
                if "Notes for part" in user:
                    return 200, self._reply("- part note")
                return 200, self._reply("## Summary\nThe lease runs a year. Rent is $900 [CHECK].\n## Key points\n- Pets allowed")
            if sysmsg.startswith("You rewrite the person's text"):
                if "Compare the ORIGINAL" in user:
                    return 200, self._reply("- Friendlier tone\n- Same facts")
                body = re.search(r"<<<\n(.*)\n>>>", user, re.S).group(1)
                if "TOOSHORT" in body and "ONLY what was asked" not in user:
                    return 200, self._reply("Hi")
                return 200, self._reply("Sure, here it is:\n" + "\n".join("[RW] " + ln if ln.strip() else ln
                                                                          for ln in body.split("\n")))
            if sysmsg.startswith("You help a small business get found"):
                if "reply with ONLY JSON" in user or "Reply with ONLY JSON" in sysmsg:
                    return 200, self._reply('{"name": "Corner Bakery", "type": "Bakery", "description": "Fresh bread.", '
                                            '"street": "12 Main St", "city": "Springfield", "phone": "", "hours": ["Tu-Sa 07:00-15:00"], '
                                            '"services": ["Bread", "Cakes"]}')
                if "10 questions" in user:
                    return 200, self._reply("### Are you open Monday?\nNo, Tuesday to Saturday.\n### Do you deliver?\nContact us [CHECK].")
                return 200, self._reply("## Short description\nFresh bread in Springfield.")
            if sysmsg.startswith("You plan cheap, filling"):
                own = "THE PERSON'S PRICE LIST" in user
                return 200, self._reply(json.dumps({"meals": [{"day": "Day 1", "breakfast": "Oats", "lunch": "Beans", "dinner": "Rice"}],
                    "shopping": [{"item": "Rice", "amount": "10 lb", "price": 9.5, "from_list": own},
                                 {"item": "Beans", "amount": "4 lb", "price": "$6.25", "from_list": False},
                                 {"item": "Eggs", "amount": "5 dozen", "price": 80, "from_list": False}],
                    "tips": ["Cook beans from dry"]}))
            if sysmsg.startswith("You pull dates out of the person's notes"):
                return 200, self._reply(json.dumps({"events": [
                    {"title": "Dentist, Sam", "date": "2026-12-01", "start": "15:00", "end": "", "place": "Main St; Suite 2", "sure": True},
                    {"title": "Dentist, Sam", "date": "2026-12-01", "start": "15:00"},
                    {"title": "Party", "date": "2026-12-05", "start": "", "sure": False},
                    {"title": "Someday", "date": "soon"}],
                    "todos": [{"task": "Send the forms", "due": "2026-11-20", "who": "Ann"}, {"task": ""}]}))
            if sysmsg.startswith("You sort the person's documents"):
                name = re.search(r"Document file name: (.+)", user).group(1)
                if "bill" in name:
                    return 200, self._reply('{"category": "Bills", "title": "Electric bill: March", "date": "2026-03-02"}')
                return 200, self._reply('{"category": "Letters", "title": "School letter", "date": ""}')
            if sysmsg.startswith("You turn a question about a spreadsheet"):
                q = user.split("Question:", 1)[1].lower()
                if "per month" in q:
                    return 200, self._reply('{"op": "sum", "column": "Price", "group_by": "Month", "filters": [], "sort": "desc"}')
                if "mugs" in q:
                    return 200, self._reply('{"op": "sum", "column": "Price", "filters": [{"column": "Product", "is": "contains", "value": "mug"}]}')
                if "weather" in q:
                    return 200, self._reply('{"op": "none", "why": "the sheet has no weather"}')
                return 200, self._reply('{"op": "average", "column": "Nope"}')
            if sysmsg.startswith("You brainstorm"):
                return 200, self._reply("\n".join(f"{i}. Idea {i}" for i in range(1, 11)))
            if sysmsg.startswith("You are a patient tutor"):
                if "flashcards" in user:
                    return 200, self._reply('[{"front": "What is a cell?", "back": "The basic unit of life"}, {"front": "x", "back": ""}]')
                if "practice quiz" in user:
                    return 200, self._reply("1. What is a cell?\nA) a b c d\n## Answers\n1. A")
                return 200, self._reply("## Cells\nCells are tiny building blocks." + (" TEACHMODE" if "Teach-me" in user else ""))
            if sysmsg.startswith("You review code"):
                return 200, self._reply("## What it does\nAdds two numbers (line 1).\n## Likely bugs and risks\n- None found")
            if sysmsg.startswith("You summarize one of the person's documents"):
                return 200, self._reply("- A short summary.\n\nWorth knowing: nothing urgent.")
            if sysmsg.startswith("You fix spelling mistakes in spreadsheet cells"):
                rows = json.loads(re.search(r"^(\[.*\])$", user, re.M).group(1))
                fixes = [{"row": r["row"], "column": k, "find": "Bwol", "replace": "Bowl"}
                         for r in rows for k, v in r.items() if isinstance(v, str) and "Bwol" in v]
                fixes.append({"row": 999, "column": "Name", "find": "x", "replace": "y"})   # not a row: ignored
                return 200, self._reply(json.dumps(fixes))
            if sysmsg.startswith("You sort spreadsheet rows"):
                if "Suggest 3 to 8" in user:
                    return 200, self._reply('["Mugs", "Bowls"]')
                rows = json.loads(re.search(r"Rows as JSON:\n(\[.*\])", user, re.S).group(1))
                out = []
                for r in rows[:-1]:                                            # last row left out
                    text = " ".join(str(v) for v in r.values()).lower()
                    out.append({"row": r["row"], "category": "mugs" if "mug" in text else
                                "Bowls" if "bowl" in text else "Plates"})
                return 200, self._reply("```json\n" + json.dumps(out) + "\n```")
            if sysmsg.startswith("You split one spreadsheet column"):
                rows = json.loads(re.search(r"Rows as JSON:\n(\[.*\])", user, re.S).group(1))
                out = []
                for r in rows:
                    full = [v for k, v in r.items() if k != "row"][0]
                    a, _, b = full.partition(" ")
                    out.append({"row": r["row"], "First name": a, "Last name": b})
                return 200, self._reply(json.dumps(out))
            if req["messages"][0]["content"].startswith("You are a careful translator"):
                lang = re.search(r"into (\w+)", req["messages"][0]["content"]).group(1)
                body = re.search(r"<<<\n(.*)\n>>>", user, re.S).group(1)
                if "SHORTFIRST" in body and "ONLY the translated" not in user:
                    return 200, self._reply("Hola.")                          # far too short: retried
                out = "\n".join(f"[{lang[:2].upper()}] {ln}" if ln.strip() else ln for ln in body.split("\n"))
                out = out.replace("idiom", "idiom [CHECK]")
                return 200, self._reply(f"Here is the translation:\n```\n{out}\n```")
            if req["messages"][0]["content"].startswith("You are a careful proofreader"):
                fixes = [{"find": w, "replace": r, "why": "spelling"}
                         for w, r in (("teh cat", "the cat"), ("recieve", "receive")) if w in user]
                if "clearer wording" in user or "confusing" in req["messages"][0]["content"]:
                    fixes.append({"find": "words that are not in the text", "replace": "x", "why": "clarity"})
                if "Paris" in user:
                    fixes.append({"find": "Paris", "replace": "Paris", "why": "is this the right city?"})
                if "GARBLE" in user and "ONLY the JSON" not in user:
                    return 200, self._reply("Sure, here are my thoughts on your lovely text!")
                return 200, self._reply("```json\n" + json.dumps(fixes) + "\n```")
            first = req["messages"][1]["content"].lower().split("\n\n")[0] if len(req["messages"]) > 1 else ""
            if req["messages"][0]["content"].startswith("You turn a plain request") and "translate" in first:
                m = re.search(r"^- (\S+\.(?:txt|md|docx|pdf))$", req["messages"][1]["content"], re.M)
                return 200, self._reply("=== JOE MISSION ===\nTASK: Menu translations\nTYPE: translate\n"
                                        f"INPUT: {m.group(1) if m else 'x.txt'}\nOPTIONS: to spanish, to french\n"
                                        "=== END ===")
            if req["messages"][0]["content"].startswith("You turn a plain request") and \
                    ("aloud" in first or "proofread" in first):
                m = re.search(r"^- (\S+\.(?:txt|md|docx|pdf))$", req["messages"][1]["content"], re.M)
                doc = m.group(1) if m else "nothing.txt"
                kind = "read-aloud\nOPTIONS: none" if "aloud" in first else "proofread\nOPTIONS: copy"
                return 200, self._reply(f"=== JOE MISSION ===\nTASK: My story\nTYPE: {kind}\n"
                                        f"INPUT: {doc}\n=== END ===")
            if req["messages"][0]["content"].startswith("You turn a plain request") and \
                    "transcribe" in req["messages"][1]["content"].lower():
                m = re.search(r"^- (\S+)$", req["messages"][1]["content"], re.M)
                rec = m.group(1) if m else "nothing.mp3"
                return 200, self._reply(f"=== JOE MISSION ===\nTASK: Meeting notes\nTYPE: transcribe\n"
                                        f"INPUT: {rec}\nOPTIONS: subtitles, notes\n=== END ===")
            if req["messages"][0]["content"].startswith("You turn a plain request"):
                if "BADFIRST" in req["messages"][1]["content"] and "That didn't work" not in user:
                    return 200, self._reply("Sure! I'll get right on it.")      # no mission at all
                text = ("```\n=== JOE MISSION ===\nRULES: Warm, plain voice.\n"
                        "TASK: Menu blurbs\nCHUNKS: 6 x 8\nFORMAT: Dish name, then two sentences.\n"
                        "TASK: Menu sheet  SAVE: menu.csv  CHUNKS: 2 x 5\nHEADER: Dish,Price\n"
                        "TASK: Food pictures\nTYPE: image\nCHUNKS: 4 x 4\nFORMAT: Overhead shots, soft light.\n"
                        "=== END ===\n```")
                return 200, self._reply(text)
            if "You are Joe (real name" in req["messages"][0]["content"]:
                if "mission" in user.lower():
                    text = ("Sure thing, I'll handle that tonight.\n\n=== JOE MISSION ===\n"
                            "TASK: Tips  SAVE: talk/tips.md  CHUNKS: 1 x 3\nFORMAT: One short paragraph.\n"
                            "=== END ===")
                else:
                    text = "**Hi!** I'm Joe. Nothing is running right now."
                return 200, self._reply(text)
            if "CSV COLUMNS" in user:
                return 200, self._csv(user)
            if "Write ONLY this part" in user:
                return 200, self._guided(user)
            if "too short" in user:
                title = re.search(r"^## (.+)$", user, re.M).group(1)
                text = f"## {title}\n\n" + " ".join(["expanded"] * 80)
            else:
                want = int(re.search(r"Write exactly (\d+)", user).group(1))
                used = re.findall(r"^- (.+)$", user, re.M)
                out = []
                for _ in range(want):
                    self.counter += 1
                    c = self.counter
                    if used and c % self.dup_every == 0:
                        out.append(f"## {used[0]}\n\nDuplicate body text here.")
                        continue
                    words = 10 if c % self.short_every == 0 else 50
                    flag = " [CHECK: kiln temp]" if c % 5 == 0 else ""
                    out.append(f"## Item number {c}\n\n" + " ".join(["word"] * words) + flag)
                text = "Sure! Here you go:\n\n" + "\n\n".join(out)
            return 200, {"message": {"role": "assistant", "content": text},
                         "prompt_eval_count": 100, "eval_count": 200,
                         "total_duration": 2_000_000_000}
