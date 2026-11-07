"""dev128: fixes from the pre-release review."""
import io
import urllib.request

import pytest

from joeai import items, packs, support
from joeai.mission import slug


def test_names_in_every_language():
    assert slug("陶器のマグ") != slug("花瓶") and slug("陶器のマグ") != "job"
    assert slug("Фото") == "фото" and slug("Hand-thrown Mug!") == "hand-thrown-mug"
    assert slug("!!!") == "job"
    assert items.norm_title("Синяя кружка") == "синяя кружка"
    assert not items.is_duplicate("Синяя кружка", ["Красная ваза"])
    assert items.count_words("Привет, как дела у тебя") == 5
    assert items.count_words("今日は良い天気です") >= 4


def test_cut_short_download_is_not_kept(tmp_path, monkeypatch):
    from joeai import doctor

    class R(io.BytesIO):
        headers = {"Content-Length": "1000"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: R(b"x" * 400))
    dest = tmp_path / "model.safetensors"
    assert not doctor._download("https://example.invalid/m", dest, lambda m: None)
    assert not dest.exists() and not dest.with_suffix(".safetensors.part").exists()


def test_connector_cant_read_private_folders(tmp_path):
    from joeai.mcp import Joe
    from joeai.sandbox import Sandbox, SandboxError
    j = Joe.__new__(Joe)
    j.sb = Sandbox(tmp_path / "ws").ensure()
    (j.sb.output / ".joe" / "chats").mkdir(parents=True)
    (j.sb.output / ".joe" / "chats" / "a.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SandboxError):
        j._inside_output(".joe/chats/a.json")
    with pytest.raises(SandboxError):
        j._inside_output("../x")
    assert j._inside_output("report.md").name == "report.md"


def test_user_pack_drops_task_with_keys_on_its_line():
    text = "=== JOE MISSION ===\nTASK: Song  SAVE: song.mp3\nTYPE: music\nTASK: Notes\nCHUNKS: 1 x 2\n=== END ===\n"
    out = packs.drop_task(text, "Song")
    assert "Song" not in out and "TASK: Notes" in out


def test_help_file_scrub():
    t = support._scrub_text("ping https://me:secret@ntfy.example.com/x and Joe said hi")
    assert "secret" not in t and "https://ntfy.example.com/x" in t
    s = support._scrub_settings({"ollama": {"engine_start": "llama-server --api-key abc"},
                                 "comfort": {"ntfy_server": "https://u:p@n.example"}})
    assert s["ollama"]["engine_start"] == "(hidden)" and s["comfort"]["ntfy_server"] == "https://n.example"


def test_rerun_keeps_from_links():
    from joeai import describe
    blocks = ["TASK: Candles  SAVE: candles.md\nCHUNKS: 2 x 5", "TASK: Prices  SAVE: prices.csv\nFROM: Candles"]
    again = describe._again_block(blocks[1])
    assert "FROM: Candles (again)" in again and "TASK: Prices (again)" in again
    assert describe._from_name(blocks[1]) == "Candles"
