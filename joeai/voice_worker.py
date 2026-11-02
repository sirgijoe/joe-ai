"""Joe's voice helper. Runs inside the private voice environment (NOT Joe's own Python).

Reads one JSON request per line on stdin, writes one JSON reply per line on stdout:
  {"cmd": "warmup", "stt_model": "base.en"}
  {"cmd": "stt", "audio": "C:/.../clip.webm", "stt_model": "base.en"}  -> {"ok": true, "text": "..."}
  {"cmd": "tts", "text": "...", "out": "C:/.../reply.wav", "voice": "am_adam", "speed": 1.0}
Everything runs on the CPU so it never fights the night's work for the graphics card.
"""
import json
import os as _os
import sys as _sys

# Never import Joe's own modules (joeai/http.py etc.) in place of the standard library.
_here = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:] = [p for p in _sys.path if _os.path.abspath(p or ".") != _here]
import os
import re
import sys

MODELS = os.environ.get("JOE_VOICE_MODELS", "")
_stt = {}
_tts = None


def stt_model(name):
    if name not in _stt:
        from faster_whisper import WhisperModel
        _stt[name] = WhisperModel(name, device="cpu", compute_type="int8",
                                  download_root=os.path.join(MODELS, "whisper"))
    return _stt[name]


def tts_model():
    global _tts
    if _tts is None:
        from kokoro_onnx import Kokoro
        _tts = Kokoro(os.path.join(MODELS, "kokoro-v1.0.int8.onnx"), os.path.join(MODELS, "voices-v1.0.bin"))
    return _tts


def chunks(text, size=380):
    """Kokoro speaks best in sentence-sized pieces."""
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
    cmd = req.get("cmd")
    if cmd == "ping":
        import http.client                      # proves the standard library isn't shadowed
        return {"ok": True, "http": http.client.__name__}
    if cmd == "warmup":
        stt_model(req.get("stt_model", "base.en"))
        tts_model()
        return {"ok": True}
    if cmd == "stt":
        audio = req["audio"]
        if audio.lower().endswith(".wav"):
            # Read the WAV ourselves (16 kHz mono from Joe's window), so faster-whisper never
            # needs its PyAV decoder (newer PyAV versions break it).
            import numpy as np
            import soundfile as sf
            data, rate = sf.read(audio, dtype="float32", always_2d=True)
            data = data.mean(axis=1)
            if rate != 16000:                    # simple resample if a different rate arrives
                n = int(len(data) * 16000 / rate)
                data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data).astype("float32")
            audio = data
        segs, _ = stt_model(req.get("stt_model", "base.en")).transcribe(
            audio, beam_size=1, vad_filter=True, language="en")
        return {"ok": True, "text": " ".join(s.text.strip() for s in segs).strip()}
    if cmd == "tts":
        import numpy as np
        import soundfile as sf
        k = tts_model()
        audio, rate = [], 24000
        for piece in chunks(req.get("text", "")[:6000]):
            samples, rate = k.create(piece, voice=req.get("voice", "am_adam"),
                                     speed=float(req.get("speed", 1.0)), lang="en-us")
            audio.append(samples)
            audio.append(np.zeros(int(rate * 0.18), dtype=samples.dtype))   # small pause
        sf.write(req["out"], np.concatenate(audio) if audio else np.zeros(1), rate)
        return {"ok": True, "out": req["out"]}
    return {"ok": False, "error": f"unknown command {cmd!r}"}


def main():
    # Libraries print progress and warnings to stdout; only our JSON replies may go there.
    reply_out = sys.stdout
    sys.stdout = sys.stderr
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            reply = handle(json.loads(line))
        except Exception as e:                     # report, keep serving
            reply = {"ok": False, "error": f"{type(e).__name__}: {e}"[:400]}
        reply_out.write("@@JOE@@" + json.dumps(reply) + "\n")
        reply_out.flush()


if __name__ == "__main__":
    main()
