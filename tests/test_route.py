import pytest

from joeai.route import classify


@pytest.mark.parametrize("text,cmd", [
    ("go", "run"), ("GO!", "run"), ("run it please", "run"), ("joe, stop", "stop"), ("Stop.", "stop"),
    ("?", "help"), ("help", "help"), ("pics", "files"), ("report", "report"), ("update", "updates"),
    ("settings", "setup"), ("new chat", "new"), ("tools", "tools"), ("fix it", "check"),
])
def test_commands(text, cmd):
    assert classify(text) == {"kind": "command", "cmd": cmd}


@pytest.mark.parametrize("text", [
    "hi", "thanks!", "what can a vision model do?", "how long will this take", "who are you",
    "is my run done?",
])
def test_chat(text):
    assert classify(text)["kind"] == "chat"


@pytest.mark.parametrize("text", [
    "fix my old photo", "20 captions for my candle shop", "make 8 pictures of mugs",
    "transcribe the recording", "can you write 10 emails for my bakery",
    "remove the background from my product photos",
])
def test_plan(text):
    assert classify(text)["kind"] == "plan"


@pytest.mark.parametrize("text", ["xy", "mugs", "blah"])
def test_unclear(text):
    r = classify(text)
    assert r["kind"] == "unclear" and "go, stop, help" in r["say"]
