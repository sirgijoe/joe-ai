"""Setting up your own SearXNG with Joe's help (2.3). Joe writes the settings file SearXNG needs (JSON
answers on) and shows the one command that starts it; the person installs Docker Desktop and runs the
command themselves. CHECK MY SEARXNG says what is wrong in plain words. Fake servers only."""
from pathlib import Path

import pytest

from joeai import searxng

from fake_search import FakeWeb

ROOT = Path(__file__).resolve().parents[1]


def test_joe_makes_the_folder_and_a_settings_file_with_json_on(tmp_path):
    r = searxng.make_folder(tmp_path)
    folder = tmp_path / "SearXNG"
    assert r["ok"] and r["made"] and Path(r["folder"]) == folder and r["address"] == "http://localhost:8888"
    assert (folder / "data").is_dir()
    text = (folder / "config" / "settings.yml").read_text(encoding="utf-8")
    assert "use_default_settings: true" in text and "limiter: false" in text
    assert "formats:\n    - html\n    - json\n" in text
    key = text.split('secret_key: "')[1].split('"')[0]
    assert len(key) == 64 and key != "ultrasecretkey" and "\t" not in text


def test_every_folder_gets_its_own_secret_and_an_old_file_is_never_overwritten(tmp_path):
    a = searxng.make_folder(tmp_path / "a")
    b = searxng.make_folder(tmp_path / "b")
    one = (tmp_path / "a" / "SearXNG" / "config" / "settings.yml").read_text(encoding="utf-8")
    assert one != (tmp_path / "b" / "SearXNG" / "config" / "settings.yml").read_text(encoding="utf-8")
    again = searxng.make_folder(tmp_path / "a")
    assert again["ok"] and not again["made"] and "already" in again["text"]
    assert (tmp_path / "a" / "SearXNG" / "config" / "settings.yml").read_text(encoding="utf-8") == one
    assert a["command"] == again["command"] != b["command"]


def test_the_command_starts_it_for_this_pc_only(tmp_path):
    cmd = searxng.make_folder(tmp_path / "My Joe")["command"]
    folder = tmp_path / "My Joe" / "SearXNG"
    assert cmd.startswith("docker run -d --name searxng --restart unless-stopped -p 127.0.0.1:8888:8080 ")
    assert f'-v "{folder / "config"}:/etc/searxng"' in cmd and f'-v "{folder / "data"}:/var/cache/searxng"' in cmd
    assert cmd.endswith(" docker.io/searxng/searxng:latest") and "\n" not in cmd


def test_a_folder_joe_cannot_write_is_said_plainly(tmp_path):
    (tmp_path / "SearXNG").write_text("a file is in the way")
    r = searxng.make_folder(tmp_path)
    assert not r["ok"] and "couldn't make" in r["text"]


@pytest.fixture
def web():
    with FakeWeb() as w:
        yield w


def test_check_says_it_works(web):
    web.route("/search", {"results": [{"title": "a", "url": "https://example.org", "content": "b"}] * 4})
    r = searxng.check(web.url("/search"))
    assert r == {"ok": True, "text": "Your SearXNG works (4 results). Tick 'Your own SearXNG' in the list and SAVE."}
    assert web.hits[0][1].startswith("/search?q=") and "format=json" in web.hits[0][1]


@pytest.mark.parametrize("address,part", [
    ("", "Type its address first"),
    ("localhost:8888", "Type its address first"),
    ("javascript:alert(1)", "Type its address first")])
def test_check_wants_a_web_address(address, part):
    r = searxng.check(address)
    assert not r["ok"] and part in r["text"] and "http://localhost:8888" in r["text"]


def test_check_names_what_is_wrong(web):
    web.route("/search", "<html>no json here</html>", status=403)
    r = searxng.check(web.url())
    assert not r["ok"] and "JSON answers are switched off" in r["text"] and "- json" in r["text"]
    web.route("/search", {"error": "limit"}, status=429)
    assert "limiter: false" in searxng.check(web.url())["text"]
    web.route("/search", "<html>a web page</html>")
    assert "isn't SearXNG" in searxng.check(web.url())["text"]
    web.route("/search", {"results": [], "unresponsive_engines": [["google", "CAPTCHA"], ["brave", "too many requests"]]})
    r = searxng.check(web.url())
    assert not r["ok"] and "found nothing" in r["text"] and "google (CAPTCHA)" in r["text"]
    web.route("/search", {"error": "x"}, status=500)
    assert "answered with an error (500)" in searxng.check(web.url())["text"]


def test_check_says_when_nothing_is_there():
    r = searxng.check("http://127.0.0.1:9")
    assert not r["ok"] and "Nothing answers at that address" in r["text"] and "docker start searxng" in r["text"]


def test_setup_and_the_guide_walk_through_it():
    html = (ROOT / "joeai" / "ui" / "index.html").read_text(encoding="utf-8")
    assert 'data-act="searxng-make"' in html and 'data-act="searxng-check"' in html and "Docker Desktop" in html
    js = (ROOT / "joeai" / "ui" / "app.js").read_text(encoding="utf-8")
    assert "/api/web/searxng-make" in js and "/api/web/searxng-check" in js
    server = (ROOT / "joeai" / "server.py").read_text(encoding="utf-8")
    assert '"/api/web/searxng-make"' in server and '"/api/web/searxng-check"' in server
    guide = (ROOT / "docs" / "GUIDE.md").read_text(encoding="utf-8")
    assert "MAKE THE SEARXNG FOLDER" in guide and "CHECK MY SEARXNG" in guide and "Docker Desktop" in guide
