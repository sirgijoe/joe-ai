"""Joe's voice-copy helper (optional add-on). Runs in the voice-copy environment, not Joe's
own Python. Same JSON-lines protocol as voice_worker.py:
  {"cmd": "warmup"}
  {"cmd": "tts", "text": "...", "out": ".../reply.wav", "ref": ".../reference.wav"}
Chatterbox adds Resemble AI's inaudible watermark to everything it makes.
"""
import json
import os as _os
import sys as _sys

# Never import Joe's own modules (joeai/http.py etc.) in place of the standard library.
_here = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:] = [p for p in _sys.path if _os.path.abspath(p or ".") != _here]
import re
import sys

_model = None


def model():
    global _model
    if _model is None:
        import torch
        from chatterbox.tts import ChatterboxTTS
        _model = ChatterboxTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
    return _model


def chunks(text, size=280):
    parts, cur = [], ""
    for s in re.split(r"(?<=[.!?;:])\s+|\n+", text):
        s = s.strip()
        if not s:
            continue
        if len(cur) + len(s) + 1 > size and cur:
            parts.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        parts.append(cur)
    return parts or [text[:size]]


def handle(req):
    if req.get("cmd") in ("ping",):
        return {"ok": True}
    if req.get("cmd") == "warmup":
        model()
        return {"ok": True}
    if req.get("cmd") == "tts":
        import torch
        import torchaudio
        m = model()
        pieces = []
        for piece in chunks(req.get("text", "")[:4000]):
            wav = m.generate(piece, audio_prompt_path=req["ref"])
            pieces += [wav, torch.zeros(1, int(m.sr * 0.18))]
        torchaudio.save(req["out"], torch.cat(pieces, dim=1), m.sr)
        return {"ok": True, "out": req["out"]}
    return {"ok": False, "error": f"unknown command {req.get('cmd')!r}"}


def main():
    # Libraries print progress and warnings to stdout; only our JSON replies may go there.
    reply_out = sys.stdout
    sys.stdout = sys.stderr
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            reply = handle(json.loads(line))
        except Exception as e:
            reply = {"ok": False, "error": f"{type(e).__name__}: {e}"[:400]}
        reply_out.write("@@JOE@@" + json.dumps(reply) + "\n")
        reply_out.flush()


if __name__ == "__main__":
    main()
