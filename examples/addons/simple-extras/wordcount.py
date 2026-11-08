"""Word count for Joe's example add-on: python wordcount.py <input> <output> [--longest]"""
import re
import sys

src, out = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8", errors="replace").read()
words = re.findall(r"[^\W_]+(?:['-][^\W_]+)*", text)
sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
lines = [f"# Word count: {src.replace(chr(92), '/').split('/')[-1]}", "",
         f"- Words: {len(words)}", f"- Sentences: {len(sentences)}", f"- Paragraphs: {len(paras)}",
         f"- About {max(1, round(len(words) / 200))} minute(s) to read"]
if "--longest" in sys.argv[3:]:
    lines += ["", "## Longest sentences", ""]
    lines += [f"{i}. ({len(s.split())} words) {s}" for i, s in enumerate(sorted(sentences, key=lambda s: -len(s.split()))[:5], 1)]
open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
