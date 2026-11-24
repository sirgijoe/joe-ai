"""Setup > Other AI apps > "Apps connected to Joe may read my Inbox and other folders"
(Settings.mcp_folders). Off: joe_shrink and joe_summarize read Output only, like joe_read_file.
On: also Inbox, Projects, Missions, Workflows and Themes. Only Joe's own window can change it."""
from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest

from joeai import mcp, server
from joeai.config import KEEP_ON_RESET, Settings, reset_paths
from joeai.sandbox import SandboxError

from fake_ollama import FakeOllama
from test_core import env  # noqa: F401

CLOSED = ('That folder is closed to connected apps. The person can open it in Joe: '
          'Setup > Other AI apps > "Apps connected to Joe may read my Inbox and other folders".')
LABEL = "Apps connected to Joe may read my Inbox and other folders"
TIP = ("Off: connected AI apps can read only what Joe made (his Output folder). On: they can also read "
       "short versions of text files in your Inbox, Projects, Missions, Workflows and Themes folders.")


@pytest.fixture
def joe(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    fake = FakeOllama()
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = fake.url
    s.ollama.text_model = "qwen3:14b"
    s.save()
    j = mcp.Joe(s)
    j.fake = fake
    for folder in ("Inbox", "Projects", "Missions", "Workflows", "Themes", "Output"):
        (j.sb.root / folder / "x.txt").write_text(f"hello from {folder}\n", encoding="utf-8")
    yield j
    fake.close()


# ------------------------------------------------------------------ off (the default)
@pytest.mark.parametrize("folder", ["Inbox", "Projects", "Missions", "Workflows", "Themes"])
def test_shrink_refuses_other_folders_by_default(joe, folder):
    with pytest.raises(SandboxError) as e:
        joe.call("joe_shrink", {"path": f"{folder}/x.txt"})
    assert str(e.value) == CLOSED


def test_shrink_still_reads_output_by_default(joe):
    assert "hello from Output" in joe.call("joe_shrink", {"path": "Output/x.txt"})
    assert "hello from Output" in joe.call("joe_shrink", {"path": "x.txt"})


def test_summarize_refuses_before_asking_the_model(joe):
    calls = joe.fake.calls
    with pytest.raises(SandboxError) as e:
        joe.call("joe_summarize", {"path": "Inbox/x.txt"})
    assert str(e.value) == CLOSED
    assert joe.fake.calls == calls


def test_summarize_still_reads_output_by_default(joe):
    out = joe.call("joe_summarize", {"path": "Output/x.txt"})
    assert "Output/x.txt" in out and joe.fake.calls >= 1


def test_closed_message_reaches_the_app_through_the_connector(joe):
    r = mcp.handle(joe, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": "joe_shrink", "arguments": {"path": "Inbox/x.txt"}}})
    assert r["result"]["isError"] and CLOSED in r["result"]["content"][0]["text"]


def test_a_link_in_output_to_the_inbox_is_still_closed(joe):
    link = joe.sb.output / "sneaky.txt"
    try:
        link.symlink_to(joe.sb.inbox / "x.txt")
    except (OSError, NotImplementedError):
        pytest.skip("no symlinks here")
    with pytest.raises(SandboxError):
        joe.call("joe_shrink", {"path": "Output/sneaky.txt"})


# ------------------------------------------------------------------ on
@pytest.mark.parametrize("folder", ["Inbox", "Projects", "Missions", "Workflows", "Themes"])
def test_ticked_opens_the_folders(joe, folder):
    joe.s.mcp_folders = True
    assert f"hello from {folder}" in joe.call("joe_shrink", {"path": f"{folder}/x.txt"})


def test_ticked_summarize_reads_the_inbox(joe):
    joe.s.mcp_folders = True
    out = joe.call("joe_summarize", {"path": "Inbox/x.txt"})
    assert "Inbox/x.txt" in out and joe.fake.calls >= 1


def test_ticked_private_folders_stay_closed(joe):
    joe.s.mcp_folders = True
    priv = joe.sb.output / ".joe"
    priv.mkdir(parents=True, exist_ok=True)
    (priv / "state.json").write_text('{"a": 1}', encoding="utf-8")
    for bad in ("Output/.joe/state.json", ".joe/state.json", "../settings.json"):
        with pytest.raises(SandboxError):
            joe.call("joe_shrink", {"path": bad})


# ------------------------------------------------------------------ the setting
def test_setting_is_off_saves_and_resets(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    assert Settings().mcp_folders is False
    s = Settings()
    s.mcp_folders = True
    s.save()
    assert Settings.load().mcp_folders is True
    assert "mcp_folders" not in KEEP_ON_RESET
    assert reset_paths(s) and s.mcp_folders is False
    s.mcp_folders = True
    assert reset_paths(s, ["mcp_folders"]) == ["mcp_folders"] and s.mcp_folders is False


def test_tool_descriptions_say_output_always_and_the_rest_when_allowed():
    for name in ("joe_shrink", "joe_summarize"):
        desc = next(t for t in mcp.TOOLS if t["name"] == name)["description"]
        assert "Output" in desc and "allowed it in Setup" in desc
        for folder in ("Inbox", "Missions", "Projects", "Workflows", "Themes"):
            assert folder in desc


def test_setup_page_has_the_tick_box():
    html = (Path(__file__).parent.parent / "joeai" / "ui" / "index.html").read_text(encoding="utf-8")
    page = html.split('class="setpage" data-page="otherai"', 1)[1].split('class="setpage"', 1)[0]
    assert f'<label title="{TIP}">{LABEL} <input type="checkbox" data-path="mcp_folders"></label>' in page
    es = json.loads((Path(__file__).parent.parent / "joeai" / "lang" / "es.json").read_text(encoding="utf-8"))
    assert es.get(LABEL) and es.get(TIP)


# ------------------------------------------------------------------ who may change it
@pytest.fixture
def live(env):  # noqa: F811
    s, sb, _ = env
    s.mcp_key = "right-key"
    s.save()
    for folder in ("Inbox", "Output"):
        (sb.root / folder / "x.txt").write_text(f"hello from {folder}\n", encoding="utf-8")
    app = server.App(s)
    httpd = server.serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield app, httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _post(port, path, body, headers):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        c.request("POST", path, json.dumps(body).encode(),
                  {"Host": "127.0.0.1", "Content-Type": "application/json", **headers})
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")
    finally:
        c.close()


def _mcp(port, name, args):
    return _post(port, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": name, "arguments": args}},
                 {"Authorization": "Bearer right-key"})


def test_settings_route_needs_the_window_token(live):
    app, port = live
    for headers in ({}, {"X-NR-Token": "wrong"}, {"Authorization": "Bearer right-key"}):
        st, _ = _post(port, "/api/settings", {"mcp_folders": True}, headers)
        assert st == 401
        assert app.settings.mcp_folders is False and Settings.load().mcp_folders is False
    st, r = _post(port, "/api/settings", {"mcp_folders": True}, {"X-NR-Token": app.token})
    assert st == 200 and r.get("ok") and app.settings.mcp_folders is True
    assert Settings.load().mcp_folders is True


def test_the_connector_cannot_change_it(live):
    app, port = live
    st, r = _mcp(port, "joe_shrink", {"path": "Inbox/x.txt", "mcp_folders": True})
    assert st == 200 and r["result"]["isError"] and CLOSED in r["result"]["content"][0]["text"]
    for name in ("joe_settings", "joe_set", "mcp_folders"):
        st, r = _mcp(port, name, {"mcp_folders": True})
        assert "error" in r
    for name in [t["name"] for t in mcp.TOOLS if t["name"] not in ("joe_queue_mission", "joe_make_pictures",
                                                                    "joe_run_tool", "joe_start_agent", "joe_stop")]:
        _mcp(port, name, {"mcp_folders": True, "path": "x.txt"})
    assert app.settings.mcp_folders is False and Settings.load().mcp_folders is False


def test_ticking_in_the_window_opens_the_http_connector_at_once(live):
    app, port = live
    _, r = _mcp(port, "joe_shrink", {"path": "Inbox/x.txt"})
    assert r["result"]["isError"]
    st, ok = _post(port, "/api/settings", {"mcp_folders": True}, {"X-NR-Token": app.token})
    assert ok.get("ok")
    _, r = _mcp(port, "joe_shrink", {"path": "Inbox/x.txt"})
    assert not r["result"]["isError"] and "hello from Inbox" in r["result"]["content"][0]["text"]


def test_the_connector_an_app_started_sees_the_tick_without_a_restart(tmp_path, monkeypatch):
    """Joe() with no settings (how an AI app starts the connector) read them once: the box is looked up
    in the settings file again on every read, so ticking and unticking both work at once."""
    import json
    from joeai import mcp
    from joeai.config import Settings
    cfg = tmp_path / "settings.json"
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.save(cfg)
    monkeypatch.setenv("JOE_CONFIG", str(cfg))
    joe = mcp.Joe()
    (joe.sb.inbox / "note.txt").write_text("hello from the inbox", encoding="utf-8")
    with pytest.raises(SandboxError, match="closed to connected apps"):
        joe.call("joe_shrink", {"path": "Inbox/note.txt"})
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["mcp_folders"] = True
    cfg.write_text(json.dumps(data), encoding="utf-8")
    assert "hello from the inbox" in joe.call("joe_shrink", {"path": "Inbox/note.txt"})
    data["mcp_folders"] = False
    cfg.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SandboxError, match="closed to connected apps"):
        joe.call("joe_shrink", {"path": "Inbox/note.txt"})
    cfg.write_text("not json", encoding="utf-8")                      # unreadable = closed
    with pytest.raises(SandboxError, match="closed to connected apps"):
        joe.call("joe_shrink", {"path": "Inbox/note.txt"})
