import os

import pytest

os.environ.setdefault("JOE_OFFLINE", "1")      # no update checks or model-list fetches in tests


@pytest.fixture(autouse=True)
def _no_real_graphics_card(request, monkeypatch):
    """Tests behave the same on every machine: the test PC's own graphics card (an Apple chip on
    the Mac runner, an NVIDIA card on a developer's PC) is never seen. Tests that need a card
    set one themselves; test_hardware checks the detection code itself."""
    if request.module.__name__.endswith("test_hardware"):
        yield
        return
    from joeai import hardware
    hardware.reset_cache()
    monkeypatch.setattr(hardware, "_nvidia", lambda: None)
    monkeypatch.setattr(hardware, "_static", lambda: None)
    yield
    hardware.reset_cache()
