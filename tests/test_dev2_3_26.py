"""2.3.0.dev26: fixes from the 2026-11-13 overnight test on Joseph's PC (privacy blur missed two children's
faces; restyle to watercolor gave the photo back; research with 0 sources still listed made-up sources; a
PART's instructions were copied under its heading)."""
import json

from joeai import avtools


def test_pixel_boxes_are_understood_when_the_picture_size_is_known():
    raw = json.dumps({"boxes": [{"bbox_2d": [300, 150, 450, 330], "label": "face"}]})
    got = avtools.parse_boxes(raw, {"faces"}, (1536, 878), "faces")
    assert len(got) == 1 and got[0]["kind"] == "faces"
    assert abs(got[0]["x"] - 300 / 1536) < 1e-6 and abs(got[0]["w"] - 150 / 1536) < 1e-6
    assert avtools.parse_boxes(raw, {"faces"}) == []                     # no size: pixels aren't trusted
    assert avtools.parse_boxes(json.dumps({"boxes": [{"bbox_2d": [10, 10, 5000, 90]}]}), set(),
                               (1536, 878), "faces") == []                # past the picture's edge
    bare = json.dumps([{"bbox_2d": [0, 0, 100, 100]}])                   # a bare list works too
    assert len(avtools.parse_boxes(bare, set(), (200, 200), "plates")) == 1


def test_model_label_does_not_drop_a_box():
    raw = json.dumps({"boxes": [{"kind": "face", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}]})
    assert avtools.parse_boxes(raw, {"faces"}, None, "faces")[0]["kind"] == "faces"


def test_blur_asks_one_kind_at_a_time_and_looks_twice_for_faces(monkeypatch, tmp_path):
    from joeai import tools
    asked = []

    def look(engine, job, st, part, kind, system, ask, img, model):
        asked.append(ask)
        return {"boxes": []}

    monkeypatch.setattr(tools, "_look", look)
    monkeypatch.setattr(tools, "picture_b64", lambda *a, **k: "x")
    monkeypatch.setattr(avtools, "picture_size", lambda ff, src: (2016, 1152))
    monkeypatch.setattr(avtools, "_ff", lambda cmd, t: "")

    class J:
        job_id, options = "j", []
    class S:
        flags: list = []
        titles: list = []
    class E:
        meta = tmp_path
    src = tmp_path / "porch.png"
    src.write_bytes(b"x")
    avtools._blur(E(), J(), S(), "ffmpeg", src, "porch", tmp_path)
    assert sum("human face" in a for a in asked) == 2                         # faces asked, then a second look
    assert any("license plate" in a for a in asked) and any("(1536 x 878 pixels)" in a for a in asked)
    assert all(a.count("Locate every") == 1 for a in asked)


def test_restyle_says_the_medium_replaces_the_photo():
    from joeai import tools
    assert "brush strokes" in tools.RESTYLES["watercolor"][1]
    src = open(tools.__file__.replace("tools.py", "picturetools.py"), encoding="utf-8").read()
    assert "not like a photograph" in src


def test_part_instructions_copied_under_the_heading_are_dropped():
    from joeai.engine import _fix_part_heading
    part = "## The cereal city. How Elmridge became known for breakfast cereal."
    got = _fix_part_heading("## The cereal city\nHow Elmridge became known for breakfast cereal.\n\nIt began.", part)
    assert got == "## The cereal city\n\nIt began."
    kept = _fix_part_heading("## The cereal city\nKellogg opened in 1906.", part)
    assert "Kellogg opened" in kept


def test_no_sources_found_means_no_made_up_sources():
    from joeai.engine import NO_SOURCES_NOTE, drop_made_up_sources
    text = "## Founding\nSettled in the 1830s.\n\nSources:\n- Michigan State Archives\n- Local records\n\n## Today\nA city."
    out = drop_made_up_sources(text)
    assert "Archives" not in out and "Settled in the 1830s." in out and "## Today" in out
    assert "[CHECK]" in NO_SOURCES_NOTE


def test_a_bare_json_list_from_the_vision_model_is_read():
    # On the PC (2.3.0.dev26 first try) qwen2.5vl answered a bare list, which was read as "no answer"
    from joeai.tools import parse_json_object
    o = parse_json_object('```json\n[{"bbox_2d": [300, 150, 450, 330], "label": "face"}]\n```')
    assert o == {"items": [{"bbox_2d": [300, 150, 450, 330], "label": "face"}]}
    assert len(avtools.parse_boxes(json.dumps(o), {"faces"}, (1536, 878), "faces")) == 1
    assert parse_json_object('{"boxes": []}') == {"boxes": []}


# --- kids' pictures: kept apart from adult content (Joseph, 2026-11-14) ---

def _job(**kw):
    from joeai.mission import Job
    return Job(name=kw.pop("name", "Pictures"), **kw)


def test_kids_found_from_the_book_mission_rules_template_and_more_words():
    from types import SimpleNamespace as NS
    from joeai import styles
    pics = NS(name="Rocky book pictures", format="A friendly farm dog", rules="", part_prompts=[], template="")
    book = NS(name="Rocky and the Big Red Barn", format="", rules="", part_prompts=[], template="kids")
    assert not styles.for_kids(pics)
    assert styles.for_kids(pics, None, book)                              # FROM a kids' book
    assert styles.for_kids(pics, NS(rules="Family-friendly."), None)      # the mission's RULES
    for words in ("a coloring book for my granddaughter", "for my 5-year-old", "bedtime story pictures",
                  "for my 2nd grade class", "for our niece"):
        assert styles.for_kids(NS(name="Book", format=words, rules="", part_prompts=[], template=""))
    adult = NS(name="Adult coloring book", format="intricate mandalas for relaxing", rules="", part_prompts=[],
               template="coloring")
    assert not styles.for_kids(adult)                                     # adults' books aren't touched


def test_held_back_page_keeps_later_pictures_on_their_own_pages():
    from joeai.addons import add_pictures
    text = "## One\nA\n## Two\nB\n## Three\nC"
    out = add_pictures(text, ["p1.png", None, "p3.png"])
    assert out.index("p1.png") < out.index("## Two") and "p3.png" in out.split("## Three")[1]
    assert out.split("## Two")[1].split("## Three")[0].count("![]") == 0


def test_kids_check_holds_back_unsafe_pictures(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    from joeai import engine as eng, tools
    (tmp_path / "001_page.png").write_bytes(b"x")
    (tmp_path / "001_page_example.png").write_bytes(b"x")
    (tmp_path / "002_page.png").write_bytes(b"x")
    answers = {"001": {"unsafe": True, "why": "topless mermaid"}, "002": {"unsafe": False}}
    monkeypatch.setattr(tools, "find_vision_model", lambda e: "qwen2.5vl:7b")
    monkeypatch.setattr(tools, "picture_b64", lambda ff, f, tmp, n: f.name[:3])
    monkeypatch.setattr(tools, "_look", lambda e, j, s, n, k, sy, a, img, m: answers[img])
    import joeai.doctor as doctor
    monkeypatch.setattr(doctor, "ffmpeg_exe", lambda c="": None)
    self = NS(services=NS(handoff=lambda k: True), meta=tmp_path, s=NS(comfy=NS(ffmpeg="")), log=lambda m: None)
    st = NS(flags=[], media_files=["b/001_page.png", "b/001_page_example.png", "b/002_page.png"])
    job = NS(name="Mermaid pages", job_id="j")
    eng.Engine._kids_check(self, job, st, tmp_path, ["001_page.png", "001_page_example.png", "002_page.png"])
    held = tmp_path / eng.KIDS_HELD
    assert (held / "001_page.png").exists() and (held / "001_page_example.png").exists()
    assert (tmp_path / "002_page.png").exists() and st.media_files == ["b/002_page.png"]
    assert any("held back" in f["flag"] and "topless mermaid" in f["flag"] for f in st.flags)


def test_no_vision_model_means_a_clear_warning_not_silence(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    from joeai import engine as eng, tools
    monkeypatch.setattr(tools, "find_vision_model", lambda e: "")
    self = NS(services=NS(handoff=lambda k: True), meta=tmp_path, s=NS(comfy=NS(ffmpeg="")), log=lambda m: None)
    st = NS(flags=[], media_files=[])
    eng.Engine._kids_check(self, NS(name="Book", job_id="j"), st, tmp_path, ["001.png"])
    assert st.flags and "weren't checked" in st.flags[0]["flag"]


# --- the face finder (YuNet via OpenCV), Joseph OK'd 2026-11-14 ---

def test_face_finder_boxes_become_fractions_and_skip_the_vision_model_for_faces(monkeypatch, tmp_path):
    from joeai import addons, tools
    monkeypatch.setattr(addons, "faces_ready", lambda: True)
    monkeypatch.setattr(addons, "detect_faces", lambda src, log=None: [[200.0, 100.0, 50.0, 60.0, 0.9],
                                                                      [1000.0, 300.0, 40.0, 40.0, 0.7]])
    got = avtools.face_boxes(tmp_path / "x.png", (2016, 1152))
    assert len(got) == 2 and got[0]["kind"] == "faces" and abs(got[0]["x"] - 200 / 2016) < 1e-9
    asked = []
    monkeypatch.setattr(tools, "_look", lambda e, j, s, n, k, sy, a, img, m: asked.append(a) or [])
    monkeypatch.setattr(tools, "picture_b64", lambda *a, **k: "x")
    monkeypatch.setattr(avtools, "picture_size", lambda ff, src: (2016, 1152))
    cmds = []
    monkeypatch.setattr(avtools, "_ff", lambda cmd, t: cmds.append(cmd) or "")

    class J:
        job_id, options = "j", ["blur faces"]
    class S:
        flags: list = []
        titles: list = []
    class E:
        meta = tmp_path
        log = staticmethod(lambda m: None)
    src = tmp_path / "porch.png"
    src.write_bytes(b"x")
    avtools._blur(E(), J(), S(), "ffmpeg", src, "porch", tmp_path)
    assert asked == []                                                  # faces: the finder only
    assert "boxblur" in " ".join(cmds[0]) and "-map_metadata" in cmds[0]  # blurred, GPS/date data dropped
    assert any("2 faces" in f["flag"] for f in S.flags)


def test_no_face_finder_falls_back_to_the_vision_model(monkeypatch, tmp_path):
    from joeai import addons
    monkeypatch.setattr(addons, "faces_ready", lambda: False)
    assert avtools.face_boxes(tmp_path / "x.png", (100, 100)) is None


def test_face_worker_keeps_one_box_per_face():
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location("fw", pathlib.Path(avtools.__file__).with_name("face_worker.py"))
    fw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fw)
    faces = fw.merge([[10, 10, 50, 50, 0.7], [12, 11, 49, 50, 0.95], [300, 40, 30, 30, 0.6]])
    assert len(faces) == 2 and faces[0][4] == 0.95
    assert fw.main(["face_worker.py"]) == 2


def test_face_worker_enlarged_pass_needs_a_surer_face(monkeypatch):
    # dev26 porch photo: the enlarged pass called the girl's clasped hands a face (0.67)
    import importlib.util
    import pathlib
    import sys
    import types
    spec = importlib.util.spec_from_file_location("fw", pathlib.Path(avtools.__file__).with_name("face_worker.py"))
    fw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fw)
    img = types.SimpleNamespace(shape=(1152, 2016, 3))
    monkeypatch.setitem(sys.modules, "cv2", types.SimpleNamespace(imdecode=lambda d, f: img, IMREAD_COLOR=1))
    monkeypatch.setitem(sys.modules, "numpy", types.SimpleNamespace(fromfile=lambda p, dtype=None: b"", uint8=0))

    def detect(cv2, model, pic, scale, flip=False):
        if scale > 1:                                   # the enlarged pass
            return [[640, 638, 130, 127, 0.67],         # hands: dropped
                    [1000, 382, 90, 114, 0.94],         # a real face: kept (merged with the first pass)
                    [1700, 100, 40, 44, 0.62]]          # a tiny far-away face: kept
        return [[1000, 386, 92, 112, 0.93]]
    monkeypatch.setattr(fw, "_detect", detect)
    _, _, faces = fw.find_faces("m.onnx", "p.png")
    assert sorted(round(f[4], 2) for f in faces) == [0.62, 0.94]


def test_tiny_and_edge_boxes_still_make_a_picture(tmp_path):
    # On the PC a tiny box gave boxblur a radius bigger than the box and FFmpeg wrote nothing
    import shutil
    import subprocess
    import pytest
    from joeai.doctor import ffmpeg_exe
    ff = ffmpeg_exe("") or shutil.which("ffmpeg")
    if not ff:
        pytest.skip("no FFmpeg here")
    src = tmp_path / "in.png"
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=640x360", "-frames:v", "1",
                    str(src)], check=True)
    for boxes in ([{"kind": "faces", "x": 0.4, "y": 0.3, "w": 0.0005, "h": 0.0005}],
                  [{"kind": "faces", "x": 0.98, "y": 0.98, "w": 0.1, "h": 0.1}],
                  [{"kind": "faces", "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}]):
        out = tmp_path / "out.png"
        out.unlink(missing_ok=True)
        r = subprocess.run(avtools.blur_command(ff, src, out, boxes, (640, 360)), capture_output=True, text=True)
        assert r.returncode == 0 and out.is_file(), r.stderr


def test_kids_words_and_check_are_a_little_stricter():
    from joeai import engine, styles
    assert "pin-up" in styles.KID_NEGATIVE and "seductive" in styles.KID_NEGATIVE
    assert "bikini" not in styles.KID_NEGATIVE and "curvy" not in styles.KID_NEGATIVE   # mermaids can still be grown-ups
    assert "modest" in styles.KID_WORDS
    assert "bikini-style top that shows cleavage" in engine.KIDS_CHECK_ASK
