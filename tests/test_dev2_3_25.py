"""2.3.0.dev25: a copy started with its own settings file (JOE_CONFIG, like a test copy) gives connected
apps a connector that starts THAT Joe, not one on the everyday settings (the connector used to read the
everyday Joe's settings and folder even when a test copy set it up)."""
from joeai import config, connect, mcp


def _entry():
    return mcp.client_config()["mcpServers"]["joe"]


def test_everyday_joe_connector_has_no_settings_line(monkeypatch):
    monkeypatch.delenv("JOE_CONFIG", raising=False)
    assert "JOE_CONFIG" not in _entry()["env"]


def test_usual_settings_file_counts_as_everyday(monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(config.config_dir() / "settings.json"))
    assert "JOE_CONFIG" not in _entry()["env"]


def test_test_copy_connector_carries_its_settings_file(tmp_path, monkeypatch):
    own = tmp_path / "Joe TEST" / "settings.json"
    monkeypatch.setenv("JOE_CONFIG", str(own))
    e = _entry()
    assert e["env"]["JOE_CONFIG"] == str(own.resolve()) or e["env"]["JOE_CONFIG"] == str(own)
    assert e["env"]["PYTHONIOENCODING"] == "utf-8"          # the usual lines stay


def test_settings_file_makes_a_different_joe_for_system_check(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    test_copy = _entry()
    monkeypatch.delenv("JOE_CONFIG")
    everyday = _entry()
    # same Python and Joe.pyw, different settings: System check must not call them the same Joe
    assert not connect.entry_matches(connect.points_to(test_copy), everyday)
    assert connect.entry_matches(connect.points_to(everyday), everyday)
    assert connect.entry_matches(connect.points_to(test_copy), test_copy)
    assert "(settings: " in connect.points_to(test_copy)


# --- the fixes from the first dev25 run on Joseph's PC (slides, [CHECK] flag, compare lists) ---

def _job(export):
    from joeai.mission import parse
    exp = f"EXPORT: {export}\n" if export else ""
    return parse("=== JOE MISSION ===\nTASK: Deck\nPART: ## What Joe is. A free helper.\n"
                 "PART: ## How to start. Type in the box.\n" + exp + "=== END ===").jobs[0]


def test_pptx_parts_are_written_as_slides_not_essays(tmp_path):
    from joeai.engine import SLIDE_RULE, SLIDE_THIN, Engine, JobState, is_slides
    from joeai.config import Settings
    from joeai.sandbox import Sandbox
    deck, doc = _job("pptx"), _job("pdf")
    assert is_slides(deck) and not is_slides(doc)
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    eng = Engine(s, Sandbox(s.workspace_path).ensure(), log=lambda m: None)
    st = JobState(job_id="x", name="Deck", spec_hash="h")
    assert SLIDE_RULE in eng._guided_prompt(deck, 0, "", st)
    assert SLIDE_RULE not in eng._guided_prompt(doc, 0, "", st)
    assert SLIDE_THIN < 13            # the 13-word slides from the PC test are fine, not "too short"


def test_the_mission_format_tells_bigger_ais_about_pptx():
    from joeai import bigger, describe
    assert "| pptx (" in open(bigger.__file__, encoding="utf-8").read()
    assert "pptx for slides" in open(describe.__file__, encoding="utf-8").read()


def test_joes_own_disclaimer_is_not_a_check_flag():
    from joeai.items import find_flags
    from joeai.writetools import _without_note, note
    body = note("Rewritten", "gemma4:12b") + "# What changed\n\n- Shorter sentences.\n"
    assert find_flags(body) and not find_flags(_without_note(body))
    real = note("Rewritten", "m") + "Open on [CHECK] days.\n"
    assert find_flags(_without_note(real))                 # a real [CHECK] still counts
    assert _without_note("Plain text [CHECK]\nmore") == "Plain text [CHECK]\nmore"


def test_compare_splits_a_list_into_lines():
    from joeai import compare
    old = "# Saturday\n\nMow the lawn.\nClean the stalls.\nFix the gate latch.\nFeed before noon.\n"
    new = "# Saturday\n\nMow the lawn and field.\nClean the stalls.\nFeed before 11.\nCall about solar.\n"
    kinds = sorted(c["kind"] for c in compare.compare(old, new)["changes"])
    assert kinds == ["added", "changed", "changed", "removed"]
    # prose wrapped over several lines stays one paragraph
    assert len(compare.paragraphs("# T\n\nThis is prose that keeps\nwrapping over several lines\nwithout ending")) == 2
    assert compare.paragraphs("# L\n\nMilk\nEggs\nBread") == ["# L", "Milk", "Eggs", "Bread"]
