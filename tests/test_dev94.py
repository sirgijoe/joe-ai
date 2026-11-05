"""dev94: PDF export crashed the run (addons._edge imported a name app.py doesn't have)."""
from joeai import addons


def test_edge_finder_runs(monkeypatch):
    monkeypatch.setattr("joeai.system.app_browser", lambda: "/x/msedge")
    assert addons._edge() == "/x/msedge"
