"""Storage housekeeping: log caps, usage, ask-first cleanups, ComfyUI copy removal."""
import json
import os
import time

import pytest

from joeai import media as media_mod
from joeai import storage
from joeai.config import Settings
from joeai.sandbox import Sandbox


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "cfg" / "settings.json"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgcfg"))
    monkeypatch.setenv("JOE_ADDONS", str(tmp_path / "addons"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(storage, "trash", lambda p: _fake_trash(p, tmp_path / "trash"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.comfy.output_dir = str(tmp_path / "comfy_out")
    (tmp_path / "comfy_out").mkdir()
    return s, Sandbox(s.workspace_path).ensure(), tmp_path


def _fake_trash(p, d):
    import shutil
    d.mkdir(exist_ok=True)
    shutil.move(str(p), str(d / f"{time.monotonic_ns()}_{p.name}"))


def _age(p, days):
    t = time.time() - days * 86400
    os.utime(p, (t, t))


def test_cap_log_keeps_newest_lines(tmp_path):
    log = tmp_path / "_log.txt"
    log.write_text("".join(f"line {i}\n" for i in range(5000)), encoding="utf-8")
    assert not storage.cap_log(log, max_bytes=10**6)            # small enough: untouched
    assert storage.cap_log(log, max_bytes=20000, keep_bytes=5000)
    text = log.read_text(encoding="utf-8")
    assert len(text) < 5200 and text.endswith("line 4999\n")
    assert "older lines removed" in text.splitlines()[0]
    assert all(ln.startswith("line ") for ln in text.splitlines()[1:])   # whole lines only


def test_usage_reports_folders_and_cleanups(ws):
    s, sb, _ = ws
    (sb.output / "a.md").write_text("x" * 1000)
    (sb.inbox / "b.txt").write_text("y" * 50)
    u = storage.usage(s, sb)
    rows = {r["key"]: r for r in u["rows"]}
    assert rows["output"]["bytes"] == 1000 and rows["inbox"]["bytes"] == 50
    assert "comfy" in rows and "logs" in rows
    assert u["workspace_bytes"] >= 1050
    assert {c["kind"] for c in u["cleanups"]} == set(storage.CLEANUPS)


def test_clean_rejected_only_touches_x_marked(ws):
    s, sb, tmp = ws
    d = sb.output / "art" / "kiln"
    d.mkdir(parents=True)
    for n in ("a.png", "b.png", "c.png"):
        (d / n).write_bytes(b"png")
        media_mod.record(d, n, {"prompt": n})
    media_mod.set_review(d, "a.png", "reject")
    media_mod.set_review(d, "b.png", "star")
    assert [p.name for p in storage.candidates(s, sb, "rejected")] == ["a.png"]
    r = storage.clean(s, sb, "rejected")
    assert r["moved"] == 1 and r["freed"] == 3
    assert not (d / "a.png").exists() and (d / "b.png").exists() and (d / "c.png").exists()
    assert "a.png" not in media_mod.load(d)["items"]


def test_old_versions_keep_newest_and_starred_folders(ws):
    s, sb, _ = ws
    shop = sb.output / "shop"
    shop.mkdir()
    for i, n in enumerate(("mugs.md", "mugs_v2.md", "mugs_v3.md")):
        (shop / n).write_text(n)
        _age(shop / n, 10 - i)                      # mugs_v3 is newest
    (shop / "plates.md").write_text("only one")
    (shop / "level_v2.md").write_text("no base file: not a version group")
    old_dir, keep_dir, new_dir = shop / "kiln", shop / "kiln_v2", shop / "kiln_v3"
    for i, f in enumerate((old_dir, keep_dir, new_dir)):
        f.mkdir()
        (f / "1.png").write_bytes(b"p")
        media_mod.record(f, "1.png", {})
        _age(f, 10 - i)
    media_mod.set_review(keep_dir, "1.png", "star")
    _age(keep_dir, 9)
    names = sorted(p.name for p in storage.candidates(s, sb, "versions"))
    assert names == ["kiln", "mugs.md", "mugs_v2.md"]


def test_old_reports_after_30_days(ws):
    s, sb, _ = ws
    rd = sb.meta / "reports"
    rd.mkdir(parents=True)
    old, new = rd / "REPORT_20200101_000000.md", rd / "REPORT_20990101_000000.md"
    old.write_text("old"); new.write_text("new")
    _age(old, 45)
    assert storage.candidates(s, sb, "reports") == [old]


def test_comfy_copies_only_inside_joe_folder(ws):
    s, sb, tmp = ws
    out = tmp / "comfy_out"
    (out / "Joe" / "kiln").mkdir(parents=True)
    mine = out / "Joe" / "kiln" / "Joe_00001_.png"
    mine.write_bytes(b"p")
    yours = out / "ComfyUI_00001_.png"
    yours.write_bytes(b"p")
    files = [{"filename": "Joe_00001_.png", "subfolder": "Joe/kiln", "type": "output"},
             {"filename": "ComfyUI_00001_.png", "subfolder": "", "type": "output"},
             {"filename": "x.png", "subfolder": "Joe/../..", "type": "output"}]
    assert storage.delete_comfy_copies(s, files) == 1
    assert not mine.exists() and yours.exists()
    s.comfy.delete_copies = False
    mine.write_bytes(b"p")
    assert storage.delete_comfy_copies(s, files[:1]) == 0 and mine.exists()


def test_storage_api(ws):
    from joeai.server import App, serve
    from urllib.request import Request, urlopen
    s, sb, _ = ws
    app = App(s)
    srv = serve(app, 0)
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        h = {"X-NR-Token": app.token, "Content-Type": "application/json"}
        u = json.loads(urlopen(Request(base + "/api/storage", headers=h), timeout=10).read())
        assert u["rows"] and u["cleanups"]
        r = json.loads(urlopen(Request(base + "/api/storage/clean", data=b'{"kind":"reports"}',
                                       headers=h), timeout=10).read())
        assert r["ok"] and r["moved"] == 0
    finally:
        srv.shutdown()


def test_update_check_compares_versions(monkeypatch):
    from joeai import update
    from joeai.http import HttpError
    assert update.parse_version("v2.0.0") > update.parse_version("2.0.0.dev27")
    assert update.parse_version("2.0.1") > update.parse_version("2.0.0")
    assert update.parse_version("2.0.0.dev28") > update.parse_version("2.0.0.dev27")
    monkeypatch.setattr(update, "__version__", "2.0.0.dev27")
    r = update.check(force=True, fetch=lambda *a, **k: {"tag_name": "v2.0.0", "html_url": "https://x"})
    assert r["newer"] and r["latest"] == "2.0.0"
    def nope(*a, **k):
        raise HttpError("HTTP 404 from x")
    assert update.check(force=True, fetch=nope)["error"] == "No releases published yet."


def test_past_missions_delete_and_clean_up(ws):
    """Step by step > PAST MISSIONS: DEL one, CLEAN UP all (Recycle Bin); other Missions files stay."""
    from joeai.server import App, serve
    from urllib.request import Request, urlopen
    import threading
    s, sb, tmp = ws
    plan = "=== JOE MISSION ===\nTASK: a\nCHUNKS: 1 x 4\nFORMAT: x\n=== END ===\n"
    for n in ("mission_20261101_0101.txt", "mission_20261102_0101.txt", "mission_20261103_0101.txt"):
        (sb.missions / n).write_text(plan, encoding="utf-8")
    (sb.missions / "my-own-plan.txt").write_text(plan, encoding="utf-8")
    app = App(s)
    srv = serve(app, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        h = {"X-NR-Token": app.token, "Content-Type": "application/json"}
        post = lambda path, body: json.loads(urlopen(Request(base + path, data=json.dumps(body).encode(),
                                                             headers=h), timeout=10).read())
        assert len(app.history()["missions"]) == 3
        assert post("/api/history/delete", {"file": "Missions/mission_20261101_0101.txt"})["ok"]
        assert not (sb.missions / "mission_20261101_0101.txt").exists() and len(app.history()["missions"]) == 2
        assert not post("/api/history/delete", {"file": "Missions/my-own-plan.txt"})["ok"]      # not a past run
        assert not post("/api/history/delete", {"file": "../outside.txt"})["ok"]
        u = json.loads(urlopen(Request(base + "/api/storage", headers=h), timeout=10).read())
        assert next(c for c in u["cleanups"] if c["kind"] == "runs")["count"] == 2
        r = post("/api/storage/clean", {"kind": "runs"})
        assert r["ok"] and r["moved"] == 2 and app.history()["missions"] == []
        assert (sb.missions / "my-own-plan.txt").exists()
    finally:
        srv.shutdown()
