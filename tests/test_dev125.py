"""dev125: Workflows show Joe's own words (editable), DOWNLOAD ALL, folder pickers, writing templates."""
from joeai import comfy, engine, styles, workflowprefs as wfp
from joeai.config import Settings


def test_workflow_texts_shown_edited_and_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    orig_anime = styles.STYLES["anime"]
    try:
        assert wfp.builtin_text("style:anime")["words"] == "anime style, cel shaded, clean line art"
        assert wfp.text_of(s, "pictures")["leave"] == comfy.IMAGE_NEGATIVE
        assert "MOVE" in wfp.text_of(s, "video")["note"]
        # unchanged text isn't stored
        r = wfp.save(s, "style:anime", {"words": "anime style, cel shaded, clean line art", "add": ""})
        assert r["prefs"] == {}
        r = wfp.save(s, "style:anime", {"words": "anime style, soft pastel colors", "leave": "photo"})
        assert r["prefs"] == {"words": "anime style, soft pastel colors", "leave": "photo"}
        assert styles.STYLES["anime"].suffix == "anime style, soft pastel colors"
        assert styles.STYLES["anime"].negative == "photo"
        wfp.save(s, "video", {"leave": "blurry, static", "note": "- Move a lot.\n  Really."})
        assert comfy.WAN_NEGATIVE == "blurry, static" and comfy.WAN_VIDEO["negative"] == "blurry, static"
        assert engine.VIDEO_EXTRA == "- Move a lot.\n  Really."
        wfp.save(s, "pictures", {"leave": "ugly, blurry"})
        assert s.comfy.negative == "ugly, blurry" and wfp.text_of(s, "pictures")["leave"] == "ugly, blurry"
        rows = {r["id"]: r for r in wfp.entries(s, type("SB", (), {"workflows": tmp_path / "wf"})(), None)["rows"]}
        anime = {t["field"]: t for t in rows["style:anime"]["texts"]}
        assert anime["words"]["changed"] and not anime["note"]["changed"]
        for wid in ("style:anime", "video", "pictures"):
            wfp.save(s, wid, None)
        assert styles.STYLES["anime"] == orig_anime and s.comfy.negative == ""
        assert comfy.WAN_NEGATIVE == wfp._originals()["wan"]
    finally:
        s.workflows = {}
        wfp.apply(s)


def test_templates_edit_reset_and_css(tmp_path, monkeypatch):
    from joeai import doctemplates as dt
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    assert dt.get(s, "book")["page"] == "6x9" and dt.default_for(s, "epub") == "ebook"
    dt.save(s, "book", {"size": "13", "align": "left", "page": "nope", "chapter_break": False})
    t = dt.get(s, "book")
    assert t["size"] == 13 and t["align"] == "left" and t["page"] == "6x9" and not t["chapter_break"]
    rows = {r["id"]: r for r in dt.entries(s)["rows"]}
    assert any(f["changed"] for f in rows["book"]["fields"]) and not any(f["changed"] for f in rows["kids"]["fields"])
    dt.save(s, "book", None)
    assert dt.get(s, "book")["size"] == 11.5
    dt.save_defaults(s, {"docx": "manuscript", "xlsx": "book"})        # a doc template can't be the xlsx default
    assert dt.default_for(s, "docx") == "manuscript" and dt.default_for(s, "xlsx") == "sheet"
    c = dt.css(dt.get(s, "kids"))
    assert "@page { size: 8.5in 8.5in" in c and "font-size: 20pt" in c and "break-before: page" in c
    assert "@page" not in dt.css(dt.get(s, "ebook"), epub=True)
    assert dt.margins({"margins": "1 0.5"}) == (1.0, 0.5, 1.0, 0.5)


def test_docx_styles_and_page():
    from joeai import doctemplates as dt
    styles = ('<w:styles><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:asciiTheme="minorHAnsi"/></w:rPr>'
              '</w:rPrDefault></w:docDefaults><w:style w:type="paragraph" w:styleId="BodyText"><w:pPr>'
              '<w:spacing w:before="180" w:after="180"/></w:pPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading1"><w:rPr><w:color w:val="345A8A"/></w:rPr></w:style></w:styles>')
    out = dt.docx_styles(styles, dt.TEMPLATES["manuscript"])
    assert 'w:ascii="Times New Roman"' in out and 'w:sz w:val="24"' in out
    assert 'w:line="480"' in out and 'w:firstLine="720"' in out and 'w:before="180"' not in out
    assert "<w:pageBreakBefore/>" in out and "345A8A" not in out
    doc = dt.docx_page("<w:document><w:body><w:p/><w:sectPr /></w:body></w:document>", dt.TEMPLATES["book"])
    assert doc.count("<w:sectPr") == 1 and 'w:w="8640" w:h="12960"' in doc


def test_xlsx_writer_and_mission_keys(tmp_path):
    import zipfile
    from joeai import doctemplates as dt
    from joeai.mission import MissionError, parse
    src = tmp_path / "prices.csv"
    src.write_text("Item,Price,Code\nMug,12.50,007\nBowl & plate,30,10\n", encoding="utf-8")
    out = dt.csv_to_xlsx(src, dt.TEMPLATES["sheet"])
    z = zipfile.ZipFile(out)
    sheet = z.read("xl/worksheets/sheet1.xml").decode()
    assert '<v>12.50</v>' in sheet and "Bowl &amp; plate" in sheet and ">007<" in sheet     # 007 stays text
    assert 'state="frozen"' in sheet and "<autoFilter" in sheet and 'FFD9E1F2' in z.read("xl/styles.xml").decode()
    m = parse("TASK: Novel\nCHUNKS: 1 x 2\nEXPORT: docx, epub\nTEMPLATE: novel\n")
    assert m.jobs[0].template == "book"
    assert parse("TASK: P\nCHUNKS: 1 x 2\nSAVE: p.csv\nHEADER: A,B\nEXPORT: xlsx\n").jobs[0].export == ["xlsx"]
    import pytest
    with pytest.raises(MissionError):
        parse("TASK: Novel\nCHUNKS: 1 x 2\nTEMPLATE: comic\n")
    with pytest.raises(MissionError):
        parse("TASK: Novel\nCHUNKS: 1 x 2\nEXPORT: xlsx\n")


def test_pick_path_falls_through(monkeypatch):
    import subprocess
    from joeai import system
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd[0])
        if len(calls) == 1:
            return subprocess.CompletedProcess(cmd, 1, "", "ModuleNotFoundError: No module named 'tkinter'")
        return subprocess.CompletedProcess(cmd, 0, "/home/me/models\n", "")
    monkeypatch.setattr(system.subprocess, "run", fake)
    monkeypatch.setattr(system, "_pick_cmds", lambda k, t, s: [["python"], ["zenity"]])
    assert system.pick_path("folder", "x") == {"path": "/home/me/models"}
    monkeypatch.setattr(system, "_pick_cmds", lambda k, t, s: [])
    assert "error" in system.pick_path("file")


def test_restart_advice_sees_new_files(tmp_path, monkeypatch):
    from joeai import server
    a = type("A", (), {"restart_hint": "", "restart_advice": server.App.restart_advice})()
    a._disk_checked, a._disk_version = float("inf"), "9.9.9"
    assert "9.9.9" in a.restart_advice()
    a._disk_version = server.__version__
    a.restart_hint = "x"
    assert a.restart_advice() == "x"


def test_download_all_runs_each_model_once(tmp_path, monkeypatch):
    import time
    from joeai import doctor, server
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("JOE_ADDONS", str(tmp_path / "addons"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = s.comfy.url = "http://127.0.0.1:9"
    app = server.App(settings=s)
    offers = [{"id": "pull-model", "kind": "writing", "action": "pull", "model": "qwen3:8b", "what": "qwen3:8b (5.2 GB)"},
              {"id": "pack-bg", "kind": "pictures", "action": "download-pack", "pack": "bg", "what": "bg"},
              {"id": "install-voice", "action": "install-voice"},                 # a program: not in DOWNLOAD ALL
              {"id": "upd", "kind": "writing", "action": "pull", "model": "x", "group": "updates"}]
    got = []
    monkeypatch.setattr(doctor, "check", lambda settings, sm: {"issues": [o for o in offers
                                                                            if o["id"] not in got]})

    def fake_fix(b):
        got.append(b["id"])
        app.fix_result = {"ok": b["id"] != "pack-bg"}
        return {"ok": True}
    monkeypatch.setattr(app, "doctor_fix", fake_fix)
    assert [i["id"] for i in app.download_all_items()] == ["pull-model", "pack-bg"]
    assert not app.download_all({})["ok"]                        # needs the OK first
    assert app.download_all({"approved": True})["ok"]
    for _ in range(100):
        if app.dl_all.get("finished"):
            break
        time.sleep(0.1)
    assert got == ["pull-model", "pack-bg"]
    assert app.dl_all["done"] == 1 and len(app.dl_all["failed"]) == 1
    assert app.restart_advice() == ""                             # downloads never need a Joe restart


def test_claude_desktop_msix_found_on_windows(tmp_path, monkeypatch):
    from joeai import connect
    monkeypatch.setattr(connect, "WINDOWS", True)
    monkeypatch.setattr(connect, "MAC", False)
    monkeypatch.setenv("JOE_HOME_OVERRIDE", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    pkg = tmp_path / "Local" / "Packages" / "Claude_pzs8sxrjxfjjc"
    pkg.mkdir(parents=True)                               # app installed, never opened its settings
    st = {a["id"]: a for a in connect.status()}
    assert st["claude"]["installed"] and "Packages" in st["claude"]["file"]
    r = connect.connect("claude", {"command": "python", "args": ["Joe.pyw", "mcp"]})
    assert r["ok"]
    f = pkg / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
    assert "joe" in __import__("json").loads(f.read_text())["mcpServers"]
    assert connect.status()[0]["connected"]
    assert connect.disconnect("claude")["ok"] and not connect.status()[0]["connected"]


def test_screen_savers_validate_save_list(tmp_path):
    from joeai import savers
    s = savers.validate({"name": "Night <b>sky</b>", "kind": "STARS", "colors": ["#000", "#010101", "bad"],
                         "speed": 9, "density": "2", "text": "GOOD NIGHT {x} and more words here!!", "status": False})
    assert s["kind"] == "stars" and s["colors"][0] == "#000000" and s["colors"][1] == "#ffffff"   # unreadable fixed
    assert s["colors"][2] == "#7fb2ff" and s["speed"] == 5 and s["density"] == 2 and len(s["text"]) <= 24
    assert "<" not in s["name"] and "{" not in s["text"]
    import pytest
    with pytest.raises(ValueError):
        savers.validate({"kind": "flash-code"})
    sid = savers.save(tmp_path, s)
    ids = [x["id"] for x in savers.list_savers(tmp_path)]
    assert ids[0] == "joe" and sid in ids and len(ids) == len(savers.BUILTIN) + 1
    assert savers.delete(tmp_path, sid) and not savers.delete(tmp_path, "joe")

    class C:
        def chat(self, msgs, model=None, think=None):
            from joeai.ollama import ChatResult
            return ChatResult('Sure! {"name": "Ocean", "kind": "waves", "colors": ["#001020", "#55ddff", "#ffcc66"], '
                              '"speed": 2, "density": 3, "text": "", "status": true}', 1, 1, 0.1)
    assert savers.generate(C(), "m", "calm ocean")["kind"] == "waves"


def test_dev127_new_templates_and_settings():
    from joeai import doctemplates as dt
    for tid in ("largeprint", "poetry", "screenplay", "letter", "resume", "cookbook", "recipecard", "coloring",
                "school", "pricelist"):
        assert tid in dt.TEMPLATES
        for k in dt.fields_of(tid):
            assert k in dt.TEMPLATES[tid], (tid, k)
    c = dt.css(dt.get(None, "manuscript"), title="Skeeter")
    assert '@top-right { content: "Skeeter " counter(page)' in c and "@page :first" in c
    c = dt.css(dt.get(None, "school"))
    assert '"Lastname " counter(page)' in c and "@page :first" not in c          # MLA: number on page 1 too
    c = dt.css(dt.get(None, "book"))
    assert "@page :left" in c and "@bottom-left" in c and "::first-letter" in c and "1.0in 0.6in" not in c
    assert "h1, h2 { break-before: page" in dt.css(dt.get(None, "poetry"))
    assert "#title-block-header { display: none; }" in dt.css(dt.get(None, "letter"))
    assert "border-bottom" in dt.css(dt.get(None, "resume")) and "max-height" in dt.css(dt.get(None, "coloring"))
    parts = dt.docx_parts(dt.get(None, "manuscript"), "Skeeter")
    assert "Skeeter" in parts["header"] and "PAGE" in parts["header"] and "footer" not in parts
    doc = dt.docx_page("<w:document x><w:body><w:sectPr/></w:body></w:document>", dt.get(None, "book"), "", "rIdF")
    assert 'w:gutter="216"' in doc and "footerReference" in doc and "<w:titlePg/>" in doc and "xmlns:r=" in doc
    st = dt.docx_styles("<w:styles><w:docDefaults><w:rPrDefault/></w:docDefaults></w:styles>", dt.get(None, "screenplay"))
    assert 'w:styleId="Character"' in st and 'w:styleId="Transition"' in st
    assert dt.word_font(dt.TEMPLATES["screenplay"]["font"]) == "Courier New"


def test_screenplay_markup():
    from joeai import doctemplates as dt
    out = dt.screenplay_md("INT. KITCHEN - NIGHT\n\nRain falls.\n\nJOE\n(quietly)\nHello there.\n\nCUT TO:\n")
    assert '{.scene custom-style="Scene Heading"}\nINT. KITCHEN - NIGHT' in out
    assert '{.character custom-style="Character"}\nJOE' in out and '{.parenthetical' in out
    assert '{.dialogue custom-style="Dialogue"}\nHello there.' in out and '{.transition' in out
    assert '{.action custom-style="Action"}\nRain falls.' in out


def test_pricelist_money_and_totals(tmp_path):
    import zipfile
    from joeai import doctemplates as dt
    src = tmp_path / "p.csv"
    src.write_text('Item,Price,Stock\nMug,12.50,40\nBowl,$30.00,12\nVase,"1,250",2\n', encoding="utf-8")
    z = zipfile.ZipFile(dt.csv_to_xlsx(src, dt.TEMPLATES["pricelist"]))
    sheet, styles = z.read("xl/worksheets/sheet1.xml").decode(), z.read("xl/styles.xml").decode()
    assert "<v>1250</v>" in sheet and "<v>30.00</v>" in sheet and "<f>SUM(B2:B4)</f>" in sheet
    assert "<v>40</v>" in sheet and '<autoFilter ref="A1:C4"/>' in sheet and "Total" in sheet
    assert styles.index("<numFmts") < styles.index("<fonts") and "#,##0.00" in styles
    assert dt.money_columns(["Item", "Retail price", "Qty"], "auto") == {1}
    assert dt.money_columns(["Item", "Retail price", "Qty"], "qty") == {2}
    assert dt.money_value("abc") is None and dt.money_value("$1,234.5") == "1234.5"


def test_custom_templates(tmp_path, monkeypatch):
    """Your own writing templates (Setup > Writing > Templates > ADD YOUR OWN TEMPLATE)."""
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    from joeai import doctemplates as dt
    from joeai.config import Settings
    from joeai.mission import MissionError, parse
    s = Settings()
    assert not dt.add_custom(s, "", "book")["ok"]
    assert not dt.add_custom(s, "Bulletin", "nope")["ok"]
    r = dt.add_custom(s, "Church bulletin", "report", "weekly 2 pages")
    assert r["ok"] and r["id"] == "my-church-bulletin"
    assert not dt.add_custom(s, "church bulletin", "book")["ok"]          # same name twice
    assert not dt.add_custom(s, "Book", "standard")["ok"]                 # clashes with Joe's
    t = dt.get(s, "my-church-bulletin")
    assert t["custom"] and t["for"] == "doc" and t["page"] == dt.TEMPLATES["report"]["page"]
    assert dt.save(s, "my-church-bulletin", {"page": "a5", "size": 14, "label": "Bulletin"})["ok"]
    t = dt.get(s, "my-church-bulletin")
    assert t["page"] == "a5" and t["size"] == 14 and t["label"] == "Bulletin"
    assert dt.get(s, "report")["page"] == dt.TEMPLATES["report"]["page"]  # Joe's own never changes
    rows = {r["id"]: r for r in dt.entries(s)["rows"]}
    assert rows["my-church-bulletin"]["custom"] and rows["my-church-bulletin"]["base"] == "report"
    assert dt.save_defaults(s, {"pdf": "my-church-bulletin", "xlsx": "my-church-bulletin"})["ok"]
    assert dt.default_for(s, "pdf") == "my-church-bulletin" and dt.default_for(s, "xlsx") == "sheet"
    assert dt.resolve(s, "Church bulletin") == "my-church-bulletin"          # by its id...
    assert dt.resolve(s, "bulletin") == "my-church-bulletin"                 # ...or its (new) name
    assert dt.resolve(s, "newsletter") == ""
    assert dt.resolve(s, "my-church-bulletin") == "my-church-bulletin"
    assert dt.save(s, "my-church-bulletin", None)["ok"]                   # back to where it started
    assert dt.get(s, "my-church-bulletin")["page"] == dt.TEMPLATES["report"]["page"]
    s.save()
    m = parse("TASK: News\nCHUNKS: 1 x 2\nEXPORT: pdf\nTEMPLATE: my-church-bulletin\n")
    assert m.jobs[0].template == "my-church-bulletin"
    import pytest
    with pytest.raises(MissionError):
        parse("TASK: X\nCHUNKS: 1 x 2\nTEMPLATE: nothing-like-this\n")
    assert dt.delete_custom(s, "my-church-bulletin")["ok"]
    assert dt.default_for(s, "pdf") == "standard"
    assert not dt.delete_custom(s, "book")["ok"]


def test_restart_bar_really_hides():
    """.readybar sets display:flex, which beats [hidden] unless a [hidden] rule says otherwise
    (the RESTART JOE bar showed up empty)."""
    from pathlib import Path
    css = (Path(__file__).parents[1] / "joeai" / "ui" / "app.css").read_text(encoding="utf-8")
    assert ".readybar[hidden] { display: none; }" in css


def test_claude_desktop_data_outside_package(tmp_path, monkeypatch):
    """Claude Desktop that keeps its data outside the package reads Local/Claude-Data/claude_<id>/."""
    import json
    from joeai import connect
    monkeypatch.setattr(connect, "WINDOWS", True)
    monkeypatch.setattr(connect, "MAC", False)
    monkeypatch.setenv("JOE_HOME_OVERRIDE", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    pkg = tmp_path / "Local" / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
    pkg.mkdir(parents=True)
    real = tmp_path / "Local" / "Claude-Data" / "claude_pzs8sxrjxfjjc" / "claude_desktop_config.json"
    real.parent.mkdir(parents=True)
    real.write_text(json.dumps({"preferences": {"sidebarMode": "chat"}}), encoding="utf-8")
    st = {a["id"]: a for a in connect.status()}
    assert "Claude-Data" in st["claude"]["file"] and not st["claude"]["connected"]
    assert connect.connect("claude", {"command": "python", "args": ["Joe.pyw", "mcp"]})["ok"]
    d = json.loads(real.read_text(encoding="utf-8"))
    assert "joe" in d["mcpServers"] and d["preferences"]["sidebarMode"] == "chat"      # their settings kept
    assert connect.status()[0]["connected"]


def test_connect_waits_until_the_app_is_closed(tmp_path, monkeypatch):
    from joeai import connect
    monkeypatch.setattr(connect, "WINDOWS", True)
    monkeypatch.setattr(connect, "MAC", False)
    monkeypatch.setenv("JOE_HOME_OVERRIDE", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    (tmp_path / "Roaming" / "Claude").mkdir(parents=True)

    class R:
        def __init__(self, out):
            self.stdout, self.returncode = out, 0
    running = '"claude.exe","1234","Console","1","200,000 K"\n"Joe.exe","9","Console","1","1 K"\n'
    assert connect.app_running("claude", run=lambda *a, **k: R(running))
    assert not connect.app_running("claude", run=lambda *a, **k: R('"explorer.exe","1"\n'))
    assert not connect.app_running("gemini")
    monkeypatch.setattr(connect, "app_running", lambda app_id, run=None: app_id == "claude")
    r = connect.connect("claude", {"command": "python", "args": ["Joe.pyw", "mcp"]})
    assert not r["ok"] and r["running"] and "Task Manager" in r["error"]
    assert not (tmp_path / "Roaming" / "Claude" / "claude_desktop_config.json").exists()   # nothing touched
    assert connect.disconnect("claude")["running"]
    monkeypatch.setattr(connect, "app_running", lambda app_id, run=None: False)
    assert connect.connect("claude", {"command": "python", "args": ["Joe.pyw", "mcp"]})["ok"]


def test_one_click_links_extension_and_checks(tmp_path, monkeypatch):
    import base64
    import json
    import zipfile
    from urllib.parse import unquote
    from joeai import connect
    e = {"command": "C:/Py/python.exe", "args": ["C:/joe/Joe.pyw", "mcp"], "env": {"PYTHONIOENCODING": "utf-8"}}
    c = connect.deeplink("cursor", e)
    assert c.startswith("cursor://anysphere.cursor-deeplink/mcp/install?name=joe&config=")
    assert json.loads(base64.b64decode(unquote(c.split("config=")[1]))) == e
    assert connect.deeplink("lmstudio", e).startswith("lmstudio://add_mcp?name=joe&config=")
    v = json.loads(unquote(connect.deeplink("vscode", e).split("?", 1)[1]))
    assert v["name"] == "joe" and v["type"] == "stdio" and v["args"] == e["args"]
    assert connect.deeplink("claude", e) == ""
    f = connect.mcpb_bundle(e, tmp_path / "Joe.mcpb", "2.1.0.dev24")
    with zipfile.ZipFile(f) as z:
        m = json.loads(z.read("manifest.json"))
        starter = z.read("server/joe_connector.py").decode()
    assert m["manifest_version"] == "0.3" and m["version"] == "2.1.0" and m["server"]["type"] == "python"
    assert m["server"]["mcp_config"]["command"] == "C:/Py/python.exe" and "C:/joe/Joe.pyw" in starter
    assert connect.entry_matches("c:\\py\\python.exe C:\\joe\\Joe.pyw mcp", e)
    assert not connect.entry_matches("C:/old/python.exe C:/joe/Joe.pyw mcp", e)
    calls = []

    class R:
        returncode, stdout, stderr = 0, "", ""
    monkeypatch.setattr(connect.shutil, "which", lambda n: "/bin/gemini" if n == "gemini" else None)
    assert connect.gemini_add(e, run=lambda cmd, **k: calls.append(cmd) or R()) == ""
    assert calls[-1] == ["/bin/gemini", "mcp", "add", "-s", "user", "joe", "C:/Py/python.exe", "C:/joe/Joe.pyw", "mcp"]


def test_system_check_watches_connected_apps(tmp_path, monkeypatch):
    import json
    from joeai import connect
    monkeypatch.setattr(connect, "WINDOWS", False)
    monkeypatch.setattr(connect, "MAC", False)
    monkeypatch.setenv("JOE_HOME_OVERRIDE", str(tmp_path))
    monkeypatch.setattr(connect, "app_running", lambda app_id, run=None: False)
    cfg = tmp_path / ".config" / "Claude" / "claude_desktop_config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("{}", encoding="utf-8")
    e = {"command": "/usr/bin/python3", "args": ["/home/me/joe/Joe.pyw", "mcp"]}
    assert connect.check(e, ["claude"]) == [{"app": "claude", "name": "Claude Desktop", "why": "missing"}]
    connect.connect("claude", {"command": "/usr/bin/python3", "args": ["/old/Joe.pyw", "mcp"]})
    got = connect.check(e, ["claude"])
    assert got[0]["why"] == "old" and "/old/Joe.pyw" in got[0]["points_to"]
    connect.connect("claude", e)
    assert connect.check(e, ["claude"]) == [] and connect.check(e, []) == []
    assert connect.disconnect_all() == 1 and "joe" not in json.loads(cfg.read_text())["mcpServers"]


from test_tools import app  # noqa: E402,F401


def test_app_connect_uses_the_apps_own_way(app, monkeypatch):  # noqa: F811
    from joeai import connect
    opened = []
    monkeypatch.setattr(connect, "open_link", lambda url: opened.append(url) or True)
    r = app.connect_app("cursor", True)
    assert r["ok"] and "asking you to add Joe" in r["say"] and opened[-1].startswith("cursor://")
    assert "cursor" in app.settings.mcp_apps
    r = app.connect_app("claude", True, "extension")
    assert r["ok"] and opened[-1].endswith("Joe.mcpb")
