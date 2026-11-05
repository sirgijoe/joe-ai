"""dev93: fixes from the 2026-11-04 stress test."""
from joeai.engine import Engine, thin_reply_words
from joeai.items import loose_items
from joeai.tools import apply_changes, how_long, loose_find


def test_only_writing_thinks():
    assert "write" in Engine.THINK_KINDS and "proofread" not in Engine.THINK_KINDS
    assert "prompt" not in Engine.THINK_KINDS and "translate" in Engine.BEST_MODEL_KINDS


def test_thin_reply_threshold():
    assert thin_reply_words(0, 0) == 80
    assert thin_reply_words(1500, 1) == 400
    assert thin_reply_words(600, 2) == 100
    assert 21 < thin_reply_words(900, 1)


def test_loose_items_bold_and_numbered():
    t = "Here you go:\n\n1. **Happy Clay Pup**\nA cheerful pup made of clay, soft light.\n\n**Mug Buddy**\nA mug with a face."
    got = loose_items(t)
    assert [i.title for i in got] == ["Happy Clay Pup", "Mug Buddy"]
    assert "cheerful" in got[0].body


def test_proofread_finds_retyped_quotes_and_spaces():
    text = "She said “dont” go\nthere — ok."
    m = loose_find(text, 'She said "dont" go there - ok.')
    assert m and m.start() == 0
    out, applied, _, missed = apply_changes(text, [{"find": 'said "dont"', "replace": 'said "don\'t"', "why": ""}])
    assert applied and not missed and "don't" in out


def test_loose_find_needs_one_match():
    assert loose_find("a b. a b.", "a  b") is None


def test_how_long():
    assert how_long(33) == "33 s" and how_long(0.2) == "1 s"
    assert how_long(600) == "10 min" and how_long(5400) == "1 h 30 min"
