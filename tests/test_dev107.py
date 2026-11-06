"""dev107: big-test fixes."""
from types import SimpleNamespace as NS

from joeai import styles
from joeai.items import split_title_line


def M(n):
    return NS(name=n)


def test_realistic_pony_not_used_for_art():
    ms = [M("juggernautXL_ragnarok.safetensors"), M("cyberrealisticPony_v110.safetensors"),
          M("SDXL/sd_xl_base_1.0_0.9vae.safetensors")]
    for s in ("anime", "manga", "character", "coloring", "illustration"):
        got = styles.choose_model(ms, s)
        assert all("cyberrealistic" not in m.name for m in got), s
    assert styles.choose_model(ms, "photo")[0].name.startswith("juggernaut")


def test_one_line_heading_items():
    it = split_title_line("Bolt - quick and strong")
    assert (it.title, it.body) == ("Bolt", "quick and strong")
    assert split_title_line("Pip").body == "Pip"



def test_parse_changes_tolerant():
    from joeai.tools import parse_changes
    raw = '[{"find": "C:\\Users\\you", "replace": "C:\\Users\\you", "why": "path"}, {"find": "teh", "replace": "the", "why": "spelling"}]'
    got = parse_changes(raw.replace("\\\\", "\\"))     # single backslashes: invalid JSON
    assert got and got[-1]["replace"] == "the"
    broken = '[{"find": "a", "replace": "b"}, {"find": "c" "replace": "d"}]'
    assert parse_changes(broken) == [{"find": "a", "replace": "b", "why": ""}]
