"""Stands in for joeai/voice_worker.py in tests (no speech libraries needed)."""
import json
import sys

print("some library chatter on stdout", flush=True)
for line in sys.stdin:
    req = json.loads(line)
    print("Downloading model... 50%", flush=True)
    if req["cmd"] == "stt":
        head = open(req["audio"], "rb").read(12)                 # wav-check: Joe sends plain WAV
        if not req["audio"].endswith(".wav") or head[:4] != b"RIFF":
            out = {"ok": False, "error": "expected a WAV recording"}
        else:
            out = {"ok": True, "text": "make me a mission with three tips"}
    elif req["cmd"] == "transcribe":
        head = open(req["audio"], "rb").read(12)
        if head[:4] != b"RIFF":
            out = {"ok": False, "error": "expected a WAV recording"}
        else:
            out = {"ok": True, "seconds": 9.0, "segments": [
                {"s": 0.0, "e": 2.0, "t": "Welcome to the planning meeting."},
                {"s": 2.1, "e": 4.0, "t": "We will ship the new mugs on Friday."},
                {"s": 7.5, "e": 9.0, "t": "Sam will update the price list."}]}
    elif req["cmd"] == "tts":
        open(req["out"], "wb").write(b"RIFF\x24\x00\x00\x00WAVEfmt ")
        out = {"ok": True, "out": req["out"]}
    else:
        out = {"ok": True}
    print("@@JOE@@" + json.dumps(out), flush=True)
