"""Setup > Other AI apps > DEV TOOLS: the "Dev tools" tick box (Settings.dev_tools, off when Joe comes), the
plain warning under it, and the editor for the project list (Settings.dev_projects), which is saved with the
rest of Setup through /api/settings (the window's token) and comes back cleaned by devprojects.clean_settings.
RESET THIS PAGE turns Dev tools off and keeps the list. The Tools tab has a short "Dev tools" note."""
from __future__ import annotations

import http.client
import json
import re
import threading
from pathlib import Path

import pytest

from joeai import i18n, server
from joeai.config import KEEP_ON_RESET, Settings

from test_core import env  # noqa: F401

UI = Path(__file__).resolve().parent.parent / "joeai" / "ui"
LABEL = "Dev tools: connected AI apps may run the commands I list below and see this PC's status"
WARNINGS = (
    "This is for people who write software with an AI app. Leave it off if that isn't you.",
    "It can't add anything to it, type its own command, or change this list.",
    "Names and numbers only: no window titles, no file paths, no command lines.",
    "A command does whatever its program does: a test suite that deletes files will delete them.",
    "An AI app can run a listed command as often as it likes.",
    "The names of the programs you have open are shown to that app.",
    "Every run is written down in Output/dev/_runs.txt, and its whole output is kept in Output/dev.",
    "It can bring in a git bundle, by fast-forward only, only for a project where you ticked the box for that below. "
    "It never pushes.",
    "Bringing in a bundle changes the project's files. A command you listed then runs whatever is in the folder, so only "
    "bring in bundles you trust, and only tick that box for projects where you want it.",
    "The app is shown the folders and the commands on this list as you typed them, and each command's output. "
    "Don't put a password or key in a command.",
    "put those in a script and list the script. A project folder can't be Joe's own folder or inside it.",
)
PULL = "A connected AI app may bring a git bundle into this project (fast-forward only)"
PULL_TIP = ("Off: connected AI apps can only look at this project's git state. On: an app can also bring in a bundle file "
            "you saved in the project folder or in Joe's Inbox. That changes the project's files, and a command you listed "
            "then runs whatever those files say.")


def _html() -> str:
    return (UI / "index.html").read_text(encoding="utf-8")


def _js() -> str:
    return (UI / "app.js").read_text(encoding="utf-8")


def _page() -> str:
    html = _html()
    return html.split('class="setpage" data-page="otherai"', 1)[1].split('class="setpage"', 1)[0]


def _box() -> str:
    page = _page()
    box = page[page.index('<fieldset id="dev-box">'):]
    return box[:box.index("</fieldset>") + len("</fieldset>")]


def _js_part() -> str:
    js = _js()
    a = js[js.index("/* Setup > Other AI apps > DEV TOOLS"):js.index("// --- Setup > Add-ons ----")]
    t = js[js.index("const toolDevHtml = "):js.index("function renderToolGrid(lit)")]
    return a + t


# ------------------------------------------------------------------ the page
def test_the_tick_box_is_on_the_other_ai_apps_page_after_the_folders_box():
    page = _page()
    m = re.search(r'<label title="([^"]+)">' + re.escape(LABEL) + r' <input type="checkbox" data-path="dev_tools"></label>', page)
    assert m and "Off:" in m.group(1) and "On:" in m.group(1)
    assert page.index('data-path="mcp_folders"') < page.index('data-path="dev_tools"')
    assert Settings().dev_tools is False                    # off when Joe comes


def test_the_warning_is_on_the_page_not_in_a_tooltip():
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _box()).replace("&gt;", ">").replace("&amp;", "&"))
    for line in WARNINGS:
        assert line in text, line
    assert "| > &&" in text and "put those in a script and list the script" in text


def test_nothing_not_built_yet_is_promised():
    for text in (_box(), _js_part()):
        assert "Unsloth" not in text and "training run" not in text


def test_the_editor_inputs_have_no_data_path_and_are_labelled():
    """The generic Setup collector reads [data-path]: the editor's boxes stay out of it and go as dev_projects."""
    box, js = _box(), _js_part()
    assert box.count("data-path=") == 1 and 'id="dev-list" role="list"' in box
    assert "data-path" not in js
    for f in ("name", "folder", "cname", "run", "minutes"):
        assert re.search(r'<label title="[^"]+">[^<]+<input data-devf="' + f + '"', js), f    # each box sits in its label
    assert 'data-pick="folder"' in js and "addPickButtons();" in js                            # the [ + ] folder chooser
    assert 'type="number" min="1" max="240"' in js and 'placeholder="15"' in js
    for f, n in (("name", 32), ("cname", 32), ("folder", 400), ("run", 500)):          # nothing is cut without showing
        assert re.search(r'data-devf="' + f + r'" maxlength="' + str(n) + '"', js), f

    for b in ("[ ADD A PROJECT ]", "[ ADD A COMMAND ]", "[ REMOVE PROJECT ]", "[ REMOVE COMMAND ]"):
        assert b in box + js, b
    assert all('<button type="button"' in tag for tag in re.findall(r"<button[^>]*>", box + js))


def test_each_project_has_the_bundle_tick_box_saved_as_true_or_false():
    js = _js_part()
    assert (f'<label for="dev-pull-${{i}}" title="{PULL_TIP}">` +' in js
            and f'`{PULL} <input type="checkbox" id="dev-pull-${{i}}" data-devf="pull"' in js)
    assert '${p.pull === true ? " checked" : ""}' in js                       # missing = off
    assert f'aria-label="${{esc(who)}}: {PULL[0].lower() + PULL[1:]}"' in js     # the name says which project
    assert """pull: p.querySelector('[data-devf="pull"]').checked === true,""" in js
    assert '$("#dev-list").addEventListener("change", () => { $("#set-dirty").hidden = false; });' in js


def test_save_sends_the_list_and_removing_a_project_asks_first():
    js = _js()
    assert "if (devProj) out.dev_projects = devProjRead();" in js
    assert "devProjRender(s.dev_projects);" in js and "devProjSaved(out.dev_projects);" in js
    part = _js_part()
    remove = part[part.index("b.dataset.devdel != null"):]
    assert "confirmBox(" in remove and "Are you sure?" in remove
    one = part[part.index("b.dataset.devcmddel)"):part.index("b.dataset.devdel != null")]
    assert "confirmBox(" in one and "Are you sure?" in one          # one command asks first too
    assert one.index("confirmBox(") < one.index("splice(")
    assert 'title="Take this command off the list. Asks first.">[ REMOVE COMMAND ]' in part


def test_the_tools_tab_points_to_setup():
    part, js = _js_part(), _js()
    assert 'data-goto-page="otherai"' in part and "count tokens" in part
    assert "html + toolDevHtml()" in js
    assert 'show("setup", b.dataset.gotoPage)' in js        # from the Tools tab it opens Setup on that page


def test_every_new_line_has_spanish():
    p = i18n._HTML()
    p.feed(_box())
    lines = p.out + i18n._js_text(_js_part())
    assert LABEL in lines and len(lines) > 40
    es = i18n.load("es")
    missing = [t for t in lines if t not in es]
    assert not missing, missing


# ------------------------------------------------------------------ saving through Joe's window
@pytest.fixture
def live(env):  # noqa: F811
    s, _, _ = env
    s.save()
    app = server.App(s)
    httpd = server.serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield app, httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _call(port, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        c.request("POST" if body is not None else "GET", path, json.dumps(body).encode() if body is not None else None,
                  {"Host": "127.0.0.1", "Content-Type": "application/json", **(headers or {})})
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")
    finally:
        c.close()


TYPED = [{"name": "My App", "folder": '"C:\\code\\my app"', "pull": True,
          "commands": [{"name": "Tests", "run": "python -m pytest -q", "minutes": ""},
                       {"name": "slow", "run": "hua check", "minutes": 999},
                       {"name": "", "run": "left out", "minutes": 5}]},
         {"name": "", "folder": "C:\\nameless", "commands": []}]
CLEAN = [{"name": "my-app", "folder": "C:\\code\\my app", "pull": True,
          "commands": [{"name": "tests", "run": "python -m pytest -q", "minutes": 15},
                       {"name": "slow", "run": "hua check", "minutes": 240}]}]


def test_the_list_saves_with_the_window_token_and_comes_back_cleaned(live):
    app, port = live
    for headers in ({}, {"X-NR-Token": "wrong"}):
        st, _ = _call(port, "/api/settings", {"dev_tools": True, "dev_projects": TYPED}, headers)
        assert st == 401
    assert app.settings.dev_projects == [] and app.settings.dev_tools is False
    st, r = _call(port, "/api/settings", {"dev_tools": True, "dev_projects": TYPED}, {"X-NR-Token": app.token})
    assert st == 200 and r.get("ok")
    st, s = _call(port, "/api/settings", None, {"X-NR-Token": app.token})          # what the page draws again
    assert s["dev_tools"] is True and s["dev_projects"] == CLEAN          # pull comes back True (a real boolean)
    assert s["dev_projects"][0]["pull"] is True and Settings.load().dev_projects == CLEAN


def _same_list(got):
    """The list apart from the bundle tick box (its own test above checks that it is kept)."""
    return [{k: v for k, v in p.items() if k != "pull"} for p in got] == [{k: v for k, v in p.items() if k != "pull"} for p in CLEAN]


def test_an_empty_list_saves_as_empty(live):
    app, port = live
    tok = {"X-NR-Token": app.token}
    assert _call(port, "/api/settings", {"dev_projects": TYPED}, tok)[1].get("ok")
    assert _same_list(app.settings.dev_projects)
    assert _call(port, "/api/settings", {"dev_projects": []}, tok)[1].get("ok")
    assert app.settings.dev_projects == [] and Settings.load().dev_projects == []


def test_reset_this_page_turns_dev_tools_off_and_keeps_the_list(live):
    app, port = live
    tok = {"X-NR-Token": app.token}
    assert _call(port, "/api/settings", {"dev_tools": True, "mcp_folders": True, "dev_projects": TYPED}, tok)[1].get("ok")
    paths = sorted(set(re.findall(r'data-path="([^"]+)"', _page())))                # what RESET THIS PAGE sends
    assert paths == ["dev_tools", "mcp_folders"]
    assert "dev_projects" in KEEP_ON_RESET and "dev_tools" not in KEEP_ON_RESET
    st, r = _call(port, "/api/settings/reset", {"paths": paths}, tok)
    assert st == 200 and r.get("ok")
    assert app.settings.dev_tools is False and app.settings.mcp_folders is False
    assert _same_list(app.settings.dev_projects)
    assert _call(port, "/api/settings/reset", {"all": True}, tok)[1].get("ok")          # RESET ALL keeps it too
    assert app.settings.dev_tools is False and _same_list(app.settings.dev_projects)
