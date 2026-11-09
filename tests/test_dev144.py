"""Three writing-model choices per card size (tester: the Qwen pick refused news and Chinese history
questions): Joe's pick, an alternative, and one with little to no filtering, each with a plain note."""
import io
import json
import urllib.error
from pathlib import Path

from joeai import doctor, upkeep
from joeai.config import OllamaSettings
from joeai.ollama import OllamaClient

PICKS = json.loads((Path(__file__).resolve().parents[1] / "joeai" / "model_picks.json").read_text(encoding="utf-8"))


def test_every_size_has_three_roles_and_honest_notes():
    assert upkeep.valid_picks(PICKS)
    for row in PICKS["writing"]:
        allc = [row] + row["others"]
        assert [c["role"] for c in allc] == ["recommended", "alternative", "free"]
        for c in allc:
            assert c["label"] and c["maker"] and 20 < len(c["note"]) <= 200
        for c in row["others"]:
            assert "Downside" in c["note"]            # be up front about what the other choices cost
        assert not row["name"].startswith("qwen")    # the default answers news and history plainly


def test_choices_for_a_card(monkeypatch):
    monkeypatch.setattr(upkeep, "picks", lambda fetch=None: PICKS)
    ch = upkeep.writing_choices(12)
    assert [c["name"] for c in ch] == ["gemma4:12b", "qwen3:14b", "mistral-nemo:12b"]
    assert ch[0]["recommended"] and ch[2]["role"] == "free"
    assert "Setup > Writing > Model" in doctor.choices_text(ch)
    assert upkeep.writing_choices(0)[0]["name"] == "llama3.2:1b"


def test_old_picks_file_without_others_still_works(monkeypatch):
    old = {"writing": [{"min_vram": 0, "name": "qwen3:4b", "size_gb": 2.6}]}
    assert upkeep.valid_picks(old)
    monkeypatch.setattr(upkeep, "picks", lambda fetch=None: old)
    ch = upkeep.writing_choices(8)
    assert len(ch) == 1 and doctor.choices_text(ch) == ""


def test_bad_other_name_is_rejected():
    bad = json.loads(json.dumps(PICKS))
    bad["writing"][0]["others"][0]["name"] = "x; rm -rf /"
    assert not upkeep.valid_picks(bad)


def test_model_that_cant_think_just_writes(monkeypatch):
    """High writing quality asks to think first; Llama, Gemma 3, Mistral... can't, so Joe retries without."""
    from joeai import ollama as om
    sent = []

    def fake(method, url, payload=None, timeout=10, headers=None):
        sent.append(payload["think"])
        if payload["think"]:
            raise om.HttpError('HTTP 400 from x: {"error":"\\"dolphin3:8b\\" does not support thinking"}')
        return {"message": {"content": "hi"}, "eval_count": 1}
    monkeypatch.setattr(om, "request_json", fake)
    r = OllamaClient(OllamaSettings()).chat([{"role": "user", "content": "x"}], model="dolphin3:8b", think=True)
    assert r.text == "hi" and sent == [True, False]
