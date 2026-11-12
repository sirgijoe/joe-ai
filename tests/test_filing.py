"""2.3 stage 1: how Joe files his work (filing.py), tidy my Output, projects (projects.py)."""
from __future__ import annotations

import json
import threading
import urllib.request
from datetime import date
from pathlib import Path

import pytest

from joeai import filing, projects, tools
from joeai.config import Settings
from joeai.engine import Engine, JobState
from joeai.mission import parse
from joeai.sandbox import Sandbox

from fake_ollama import FakeOllama

TODAY = f"{date.today():%Y-%m-%d}"


@pytest.fixture
def fake():
    f = FakeOllama()
    yield f
    f.close()


def _settings(tmp_path, fake=None, how="date") -> Settings:
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = fake.url if fake else "http://127.0.0.1:9"
    s.comfy.url = "http://127.0.0.1:9"
    s.engine.retry_backoff_s = 0
    s.engine.gpu_temp_pause_c = 0
    s.engine.keep_awake = False
    s.filing.how = how
    return s


def _engine(tmp_path, fake=None, how="date") -> Engine:
    s = _settings(tmp_path, fake, how)
    return Engine(s, Sandbox(s.workspace_path), log=lambda x: None)


def _rel(e: Engine, st) -> str:
    return st.output


# ------------------------------------------------------------------ text tasks
def test_one_task_mission_gets_one_dated_folder(tmp_path, fake):
    e = _engine(tmp_path, fake)
    m = parse("TASK: Showcase video script  CHUNKS: 1 x 2")
    st = e.run_mission(m)[0]
    assert st.status == "done"
    assert st.output == f"{TODAY} Showcase video script/showcase-video-script.md"
    assert (e.sb.output / st.output).is_file()


def test_several_tasks_share_the_mission_folder_each_writing_has_its_own(tmp_path, fake):
    e = _engine(tmp_path, fake)
    m = parse("TASK: Mugs  CHUNKS: 1 x 2\nTASK: Bowls  SAVE: shop/bowls.md  CHUNKS: 1 x 2")
    a, b = e.run_mission(m)
    assert a.output == f"{TODAY} Mugs +1/mugs/mugs.md"
    assert b.output == f"{TODAY} Mugs +1/bowls/bowls.md"          # SAVE's file name kept, its folder replaced


def test_run_again_is_a_numbered_version_inside_the_original(tmp_path, fake, monkeypatch):
    e = _engine(tmp_path, fake)
    text = "TASK: Mugs  CHUNKS: 1 x 2\nTASK: Bowls  CHUNKS: 1 x 2"
    first = e.run_mission(parse(text))
    monkeypatch.setattr(filing, "date", type("D", (), {"today": staticmethod(lambda: date(2031, 1, 2))}))
    e2 = Engine(e.s, e.sb, log=lambda x: None)
    second = e2.run_mission(parse(text))                           # another day: still the old folder
    assert second[0].output == f"{TODAY} Mugs +1/mugs/mugs v2.md"
    assert second[1].output == f"{TODAY} Mugs +1/bowls/bowls v2.md"
    third = Engine(e.s, e.sb, log=lambda x: None).run_mission(parse(text))
    assert third[0].output.endswith("mugs/mugs v3.md")
    assert (e.sb.output / first[0].output).is_file()               # never written over
    assert not any(p.name.startswith("2031") for p in e.sb.output.iterdir())


def test_resume_keeps_the_same_file(tmp_path, fake):
    e = _engine(tmp_path, fake)
    m = parse("TASK: Mugs  CHUNKS: 2 x 2")
    job = m.jobs[0]
    e._mission = m
    st = e._load_state(m, job)
    out = e._output_path(job, st)
    out.write_text("# Mugs\n\npart one\n", encoding="utf-8")
    st.parts_done = 1
    e._save_state(job, st)
    e2 = Engine(e.s, e.sb, log=lambda x: None)
    st2 = e2.run_mission(m)[0]
    assert st2.output == st.output and "part one" in (e.sb.output / st2.output).read_text(encoding="utf-8")


def test_project_filing_puts_missions_in_the_project_folder(tmp_path, fake):
    e = _engine(tmp_path, fake, how="project")
    st = e.run_mission(parse("PROJECT: My Shop\nTASK: Blurbs  CHUNKS: 1 x 2"))[0]
    assert st.output == f"My Shop/{TODAY} Blurbs/blurbs.md"
    assert projects.page(e.sb, "my shop")["missions"][0]["folder"] == f"My Shop/{TODAY} Blurbs"
    st2 = _engine(tmp_path / "b", fake, how="project").run_mission(parse("TASK: Loose  CHUNKS: 1 x 2"))[0]
    assert st2.output == f"{TODAY} Loose/loose.md"                 # no PROJECT: = like "by date"


def test_flat_filing_is_as_before(tmp_path, fake):
    e = _engine(tmp_path, fake, how="flat")
    a = e.run_mission(parse("TASK: Mugs  SAVE: q/mugs.md  CHUNKS: 1 x 2"))[0]
    b = Engine(e.s, e.sb, log=lambda x: None).run_mission(parse("TASK: Mugs  SAVE: q/mugs.md  CHUNKS: 1 x 2"))[0]
    assert (a.output, b.output) == ("q/mugs.md", "q/mugs_v2.md")


def test_a_bad_filing_value_means_by_date():
    s = Settings()
    s.filing.how = "sideways"
    assert filing.how(s) == "date"


def test_folder_names_are_safe_on_windows():
    assert filing.clean_name('a<b>:c"/d\\e|f?g*h') == "a b c d e f g h"
    assert filing.clean_name("CON") == "_CON"
    assert filing.clean_name("   ") == "Mission"
    assert len(filing.clean_name("x" * 200)) == 60


# ------------------------------------------------------------------ every save place
def _fresh_folder(e, job):
    st = JobState(job_id=job.job_id, name=job.name, spec_hash="x")
    return tools.tool_dir(e, job, st), st


@pytest.mark.parametrize("tid", sorted(tools.TOOLS))
def test_every_tool_saves_inside_its_mission_folder(tmp_path, tid):
    from joeai.mission import Job, Mission, default_save
    e = _engine(tmp_path)
    name = f"Try {tid}"
    m = Mission(project="", rules="", jobs=[Job(name=name, save=default_save(name, "", tid), parts=1,
                                                part_size=1, type=tid, inputs=["a.txt"])])
    e._mission = m
    folder, st = _fresh_folder(e, m.jobs[0])
    assert folder.is_dir()
    assert st.output == f"{TODAY} Try {tid}", st.output
    (folder / "made.txt").write_text("x", encoding="utf-8")
    e2 = Engine(e.s, e.sb, log=lambda x: None)
    e2._mission = m
    again, st2 = _fresh_folder(e2, m.jobs[0])                     # run again: v2 inside the original
    assert st2.output == f"{TODAY} Try {tid}/v2"


@pytest.mark.parametrize("typ", ["image", "video"])
def test_pictures_and_video_save_inside_the_mission_folder(tmp_path, typ):
    e = _engine(tmp_path)
    m = parse(f"TASK: Kiln art  TYPE: {typ}  CHUNKS: 1 x 1\nTASK: Notes  CHUNKS: 1 x 1")
    e._mission = m
    job = m.jobs[0]
    st = JobState(job_id=job.job_id, name=job.name, spec_hash="x")
    folder = e._media_dir(job, st)
    assert st.output == f"{TODAY} Kiln art +1/kiln-art" and folder.is_dir()


def test_spreadsheets_keep_csv(tmp_path):
    e = _engine(tmp_path)
    m = parse("TASK: Prices  SAVE: prices.csv  CHUNKS: 1 x 2\nHEADER: name,price")
    e._mission = m
    job = m.jobs[0]
    st = JobState(job_id=job.job_id, name=job.name, spec_hash="x")
    out = e._output_path(job, st)
    assert st.output == f"{TODAY} Prices/prices.csv" and out.suffix == ".csv"


def test_watch_folders_keep_their_standing_folder(tmp_path):
    e = _engine(tmp_path)
    m = parse("TASK: Clean (watch folder)  TYPE: clean-audio\nSAVE: watch-clean-audio\nINPUT: Watch/clean-audio/a.wav")
    e._mission = m
    _, st = _fresh_folder(e, m.jobs[0])
    assert st.output == "watch-clean-audio"


def test_input_from_an_earlier_task_follows_it_into_the_mission_folder(tmp_path, fake):
    e = _engine(tmp_path, fake)
    m = parse("TASK: Notes  SAVE: notes/a.md  CHUNKS: 1 x 2\nTASK: Summary  CHUNKS: 1 x 1\nINPUT: Output/notes/a.md")
    e.run_mission(m)
    assert filing.translate_input(e, "Output/notes/a.md") == f"Output/{TODAY} Notes +1/a/a.md"
    assert filing.translate_input(e, "Inbox/other.txt") == "Inbox/other.txt"


# ------------------------------------------------------------------ Files tab, phone, connector
def test_files_phone_and_connector_find_filed_work(tmp_path, fake):
    from joeai import mcp
    from joeai.phone import Phone
    from joeai.server import App
    e = _engine(tmp_path, fake)
    st = e.run_mission(parse("TASK: Mugs  CHUNKS: 1 x 2"))[0]
    app = App(settings=e.s)
    folder = st.output.rsplit("/", 1)[0]
    names = [x["name"] for x in app.list_dir("Output/" + folder)["entries"]]
    assert "mugs.md" in names
    assert any(f["path"] == st.output for f in Phone(app).results()["files"])
    j = mcp.Joe(e.s)
    j.sb = e.sb
    assert "mugs.md" in j.list_files(folder) and "Mugs" in j.read_file(st.output)


# ------------------------------------------------------------------ tidy my Output
def _messy(sb: Sandbox) -> None:
    out = sb.output
    out.mkdir(parents=True, exist_ok=True)
    (out / "notes.md").write_text("# notes\n", encoding="utf-8")
    (out / "notes.docx").write_bytes(b"PK")
    (out / "showcase").mkdir()
    (out / "showcase" / "a.png").write_bytes(b"png")
    (out / "showcase_v2").mkdir()
    (out / "showcase_v2" / "a.png").write_bytes(b"png2")
    (out / "showcase-redo").mkdir()
    (out / "showcase-redo" / "a.png").write_bytes(b"png3")
    (out / "_REPORT.md").write_text("| Notes | done | showcase/a.png |\n", encoding="utf-8")
    (out / "Backups").mkdir()
    (out / "watch-clean-audio").mkdir()
    (out / f"{TODAY} Already filed").mkdir()
    state = sb.meta / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "showcase-abc.json").write_text(json.dumps({"job_id": "showcase-abc", "name": "Showcase",
        "spec_hash": "x", "output": "showcase", "media_files": ["showcase/a.png"], "status": "done",
        "started": "2026-10-01T22:00:00"}), encoding="utf-8")


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".joe" not in p.parts and not p.name.startswith(("_TIDY_UNDO", "_REPORT"))}


def test_tidy_only_moves_and_undo_puts_it_all_back(tmp_path):
    sb = Sandbox(tmp_path / "ws").ensure()
    _messy(sb)
    before = _tree(sb.output)
    plan = filing.tidy_plan(sb)
    tos = {p["from"]: p["to"] for p in plan}
    assert tos["showcase"] == "2026-10-01 Showcase"                # the original becomes the dated folder
    assert tos["showcase_v2"] == "2026-10-01 Showcase/v2" and tos["showcase-redo"] == "2026-10-01 Showcase/v3"
    assert tos["notes.md"].endswith(" Notes/notes.md") and tos["notes.docx"].endswith(" Notes/notes.docx")
    assert not {"_REPORT.md", "Backups", "watch-clean-audio", f"{TODAY} Already filed"} & set(tos)
    assert _tree(sb.output) == before                              # looking moves nothing
    r = filing.tidy(sb)
    assert r["ok"] and r["moved"] == len(plan) and not r["skipped"]
    after = _tree(sb.output)
    assert sorted(after.values()) == sorted(before.values())       # every file still there, same bytes
    st = json.loads((sb.meta / "state" / "showcase-abc.json").read_text(encoding="utf-8"))
    assert st["output"] == tos["showcase"] and st["media_files"] == [tos["showcase"] + "/a.png"]
    assert tos["showcase"] + "/a.png" in (sb.output / "_REPORT.md").read_text(encoding="utf-8")
    assert list(sb.output.glob("_TIDY_UNDO_*.txt"))
    u = filing.undo(sb)
    assert u["ok"] and u["moved_back"] == r["moved"]
    assert _tree(sb.output) == before
    st = json.loads((sb.meta / "state" / "showcase-abc.json").read_text(encoding="utf-8"))
    assert st["output"] == "showcase"
    assert not filing.undo(sb)["ok"]                               # nothing left to undo


def test_tidy_never_writes_over_anything(tmp_path):
    sb = Sandbox(tmp_path / "ws").ensure()
    _messy(sb)
    plan = filing.tidy_plan(sb)
    step = next(p for p in plan if p["from"] == "notes.md")
    target = sb.output / step["to"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("mine", encoding="utf-8")
    r = filing.tidy(sb, plan)
    assert any(s["from"] == "notes.md" for s in r["skipped"])
    assert target.read_text(encoding="utf-8") == "mine" and (sb.output / "notes.md").exists()


def test_tidy_refuses_a_plan_that_leaves_output(tmp_path):
    sb = Sandbox(tmp_path / "ws").ensure()
    (sb.output / "a.md").write_text("x", encoding="utf-8")
    r = filing.tidy(sb, [{"from": "a.md", "to": "../../escaped.md"}, {"from": "../Inbox", "to": "x"}])
    assert r["moved"] == 0 and (sb.output / "a.md").exists() and not (tmp_path / "escaped.md").exists()


def test_rerun_names_are_recognised():
    assert filing._base_name("blurbs_v2") == ("blurbs", 2)
    assert filing._base_name("blurbs-redo") == ("blurbs", 2)
    assert filing._base_name("blurbs-retry2") == ("blurbs", 4)
    assert filing._base_name("blurbs2") == ("blurbs", 2)
    assert filing._base_name("v2") == ("v2", 1)
    assert filing._base_name("covid19") == ("covid19", 1)


# ------------------------------------------------------------------ projects
def test_project_page_notes_todo_about_and_folders(tmp_path):
    sb = Sandbox(tmp_path / "ws").ensure()
    name = projects.ensure(sb, "Garden  Plan")
    assert name == "Garden Plan" and projects.ensure(sb, "garden plan") == "Garden Plan"
    (sb.output / "2026-11-10 Seeds").mkdir()
    (sb.output / "2026-11-10 Seeds" / "list.md").write_text("x", encoding="utf-8")
    assert projects.add_folder(sb, name, "2026-11-10 Seeds")["ok"]
    assert not projects.add_folder(sb, name, "../Inbox")["ok"]
    assert not projects.add_folder(sb, name, ".joe")["ok"]
    projects.save(sb, name, notes="mine", todo=[{"text": " water  beds ", "done": False}, {"text": ""}],
                  about="A small garden.")
    p = projects.page(sb, name)
    assert p["notes"] == "mine" and p["todo"] == [{"text": "water beds", "done": False}]
    assert p["about"].startswith("A small garden.") and (sb.projects / "Garden Plan.md").is_file()
    assert p["missions"][0]["files"] == ["2026-11-10 Seeds/list.md"]
    assert projects.summary(sb) == [{"name": "Garden Plan", "missions": 1, "left": 1}]
    assert projects.delete(sb, name)["ok"] and (sb.output / "2026-11-10 Seeds" / "list.md").exists()
    with pytest.raises(ValueError):
        projects.ensure(sb, "  ")


def test_projects_and_tidy_need_joes_own_window(tmp_path, monkeypatch):
    from joeai.server import App, serve
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    app = App(settings=_settings(tmp_path))
    httpd = serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(path, body, token=True):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              **({"X-NR-Token": app.token} if token else {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return {"status": e.code}
    try:
        assert post("/api/project/new", {"name": "X"}, token=False) == {"status": 401}
        assert post("/api/tidy", {}, token=False) == {"status": 401}
        assert post("/api/project/new", {"name": "X"})["ok"]
        req = urllib.request.Request(base + "/api/projects", headers={"X-NR-Token": app.token})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert json.loads(r.read())["projects"][0]["name"] == "X"
        assert post("/api/tidy", {})["ok"]
    finally:
        httpd.shutdown()


def test_setup_has_the_filing_choice_with_reset_and_the_projects_page():
    ui = Path(__file__).parent.parent / "joeai" / "ui"
    html = (ui / "index.html").read_text(encoding="utf-8")
    assert 'data-path="filing.how"' in html and 'id="s-projects"' in html
    assert "TIDY MY OUTPUT" in html and "UNDO THE LAST TIDY" in html


def test_a_number_in_a_name_is_not_a_rerun_without_the_original(tmp_path):
    """Fable review: "chapter 3.md" is chapter three, not run number 3 of "chapter"."""
    sb = Sandbox(tmp_path / "ws").ensure()
    out = sb.output
    out.mkdir(parents=True, exist_ok=True)
    for n in (1, 2, 3):
        (out / f"chapter {n}.md").write_text(f"ch {n}", encoding="utf-8")
    (out / "blurbs.md").write_text("b", encoding="utf-8")
    (out / "blurbs2.md").write_text("b2", encoding="utf-8")
    tos = {p["from"]: p["to"] for p in filing.tidy_plan(sb)}
    for n in (1, 2, 3):
        assert tos[f"chapter {n}.md"].endswith(f"/chapter {n}.md")       # each keeps its own name
    assert tos["blurbs2.md"].endswith(" Blurbs/blurbs v2.md")            # a real rerun still goes inside


def test_a_bare_input_name_stays_an_inbox_file(tmp_path, fake):
    """Fable review: INPUT: notes/a.md means Inbox/notes/a.md even when a task SAVEs notes/a.md."""
    e = _engine(tmp_path, fake)
    e.run_mission(parse("TASK: Notes  SAVE: notes/a.md  CHUNKS: 1 x 2"))
    assert filing.translate_input(e, "notes/a.md") == "notes/a.md"
    assert filing.translate_input(e, "Output/notes/a.md").startswith("Output/") and \
        filing.translate_input(e, "Output/notes/a.md") != "Output/notes/a.md"


def test_a_rerun_without_its_original_is_not_a_lone_v2(tmp_path):
    """Fable review (Joseph's PC test): "neon-city-redo" with no "neon-city" ended up as Neon city/v2."""
    sb = Sandbox(tmp_path / "ws").ensure()
    out = sb.output
    out.mkdir(parents=True, exist_ok=True)
    (out / "neon-city-redo").mkdir()
    (out / "neon-city-redo" / "a.png").write_bytes(b"png")
    (out / "hidden-word-retry").mkdir()
    (out / "hidden-word-retry" / "a.png").write_bytes(b"png")
    (out / "hidden-word-retry2").mkdir()
    (out / "hidden-word-retry2" / "a.png").write_bytes(b"png")
    tos = {p["from"]: p["to"] for p in filing.tidy_plan(sb)}
    assert tos["neon-city-redo"].endswith(" Neon city") and "/" not in tos["neon-city-redo"]
    assert "/" not in tos["hidden-word-retry"] and tos["hidden-word-retry2"].endswith(" Hidden word/v4")
    before = _tree(out)
    r = filing.tidy(sb)
    assert r["moved"] == 3 and sorted(_tree(out).values()) == sorted(before.values())
