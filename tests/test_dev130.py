"""dev130: Talk keeps spoken replies short, never thinks out loud, and dropped pictures go to the right tool."""
from joeai import chat


def test_brief_cuts_long_replies_unless_asked():
    b = chat.Brief("what's the weather like?")
    out = "".join(b.feed(p) for p in ["One. ", "Two. ", "Three. ", "Four. ", "Five. ", "Six."])
    assert out.strip() == "One. Two. Three. Four."
    assert b.trim("One. Two. Three. Four. Five. Six.") == "One. Two. Three. Four."
    long = chat.Brief("explain in detail how restore works")
    assert "".join(long.feed(p) for p in ["One. ", "Two. ", "Three. ", "Four. ", "Five. "]) == "One. Two. Three. Four. Five. "
    m = chat.Brief("make 40 captions")
    said = "".join(m.feed(p) for p in ["Sure. ", "=== JOE MISSION ===\nTASK: x"])
    assert "JOE MISSION" not in said and said == "Sure. "
    m2 = chat.Brief("make 40 captions")
    assert m2.feed("Okay, here it is.\n=== JOE MISSION ===\nTASK: x") == "Okay, here it is.\n"


def test_thinking_aloud_is_spotted():
    assert chat.thinking_aloud("Okay, the user wants me to create a new mission after")
    assert chat.thinking_aloud("Let me check the context first.")
    assert chat.thinking_aloud("First, the user mentioned a photo")
    assert not chat.thinking_aloud("Okay! I made a plan for your photo.")
    assert not chat.thinking_aloud("Sure, here's a short answer.")
    assert chat.after_thinking('blah. So the reply would be: "I am restoring your photo now, check the plan."') == \
        "I am restoring your photo now, check the plan."


class FakeApp:
    def __init__(self):
        self.chat_history = []

    def check(self, text):
        return {"ok": True}


def test_dropped_picture_goes_to_the_right_tool():
    app = FakeApp()
    pic = [{"kind": "image", "name": "image000000(3).jpg", "rel": "Inbox/dropped/image000000(3).jpg"}]
    r = chat.picture_mission(app, "restore this photo", pic)
    assert "TYPE: restore-photo" in r["mission"] and "INPUT: dropped/image000000(3).jpg" in r["mission"]
    r = chat.picture_mission(app, "remove the background please", pic)
    assert "TYPE: remove-bg" in r["mission"]
    r = chat.picture_mission(app, "colorize it", pic)
    assert "TYPE: restore-photo" in r["mission"] and "colorize" in r["mission"]
    r = chat.picture_mission(app, "swap the sky for a sunset", pic)
    assert "TYPE: edit-picture" in r["mission"] and "sunset" in r["mission"]
    assert chat.picture_mission(app, "what's in this picture?", pic) is None   # the vision model looks
    assert chat.picture_mission(app, "restore this photo", []) is None


def test_follow_up_uses_the_picture_from_just_before():
    app = FakeApp()
    pic = [{"kind": "image", "name": "a.jpg", "rel": "Inbox/dropped/a.jpg"}]
    app.talk_pics = (pic, 0)
    app.chat_history = [{}, {}]
    assert chat._recent_pics(app, "lets make it a new mission") == pic
    app.chat_history = [{}, {}, {}, {}]                       # two exchanges later: forgotten
    assert chat._recent_pics(app, "lets make it a new mission") == []


def test_follow_up_mission_reuses_what_was_asked(monkeypatch):
    app = FakeApp()
    pic = [{"kind": "image", "name": "a.jpg", "rel": "Inbox/dropped/a.jpg"}]
    app.talk_pics = (pic, 0)
    hist = [{"role": "user", "content": "restore this photo\n\n[attached a.jpg]\n"}, {"role": "assistant", "content": "x"}]
    app.chat_history = hist
    monkeypatch.setattr(chat, "busy_drawing", lambda a: False)
    p = chat.prepare(app, hist, "lets make it a new mission")
    assert "TYPE: restore-photo" in p["final"]["mission"] and "dropped/a.jpg" in p["final"]["mission"]


def test_true_restore_whites_guide(tmp_path):
    """Faded color print: the brightest near-colorless parts steer the highlights to white,
    green only a little (so grass doesn't turn purple)."""
    import shutil
    import subprocess
    import pytest
    from joeai import picturetools as pt
    ff = shutil.which("ffmpeg")
    if not ff:
        pytest.skip("no FFmpeg")
    img = tmp_path / "warm.png"          # a warm-white (yellowed) picture: sky-like bright area
    subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "color=c=0xF0EBDC:s=160x160", "-frames:v", "1",
                    str(img)], check=True)
    fix = pt.white_fix(ff, img)
    assert fix.startswith("colorbalance=") and "bh=0.05" in fix and "rh=-" in fix
    gh = float(fix.split("gh=")[1].split(":")[0])
    assert abs(gh) <= 0.015
    neutral = tmp_path / "white.png"
    subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "color=c=0xEEEEEE:s=160x160", "-frames:v", "1",
                    str(neutral)], check=True)
    assert pt.white_fix(ff, neutral) == ""
    cmd = pt.true_restore_command(ff, img, tmp_path / "o.png", 1, 0, "strong", True, False, fix)
    assert fix in ",".join(cmd)
