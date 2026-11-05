"""dev101: stress-test round 2: one-line lists, proofread noise."""
from joeai.items import loose_items
from joeai.tools import apply_changes, is_doubt


def test_one_line_list_items():
    t = "Here are some names:\n1. **Bolt** - quick and strong\n2. Pip: small and friendly\n3. Ember \u2014 warm"
    got = loose_items(t)
    assert [i.title for i in got] == ["Bolt", "Pip", "Ember"] and got[0].body == "quick and strong"


def test_correct_sentences_not_flagged():
    text = "All good here. Maybe recieve."
    _, applied, noted, _ = apply_changes(text, [
        {"find": "All good here.", "replace": "All good here.", "why": "spelling"},
        {"find": "Maybe", "replace": "Maybe", "why": "unsure: is 'maybe' the word meant here?"},
        {"find": "recieve", "replace": "receive", "why": "spelling"}])
    assert len(applied) == 1 and len(noted) == 1
    assert not is_doubt("punctuation") and is_doubt("might be the wrong product name")
