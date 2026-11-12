"""2.3.0.dev21: Joe never starts a second ComfyUI Desktop when one is already open (it crashed the first)."""
from joeai import services as services_mod


class FakeServices:
    ensure_comfy = services_mod.ServiceManager.ensure_comfy

    def __init__(self, running, up_after):
        self.attention, self.comfy_base, self.logs = "", "http://127.0.0.1:8188", []
        self._running, self._calls, self._up_after, self.started = running, 0, up_after, False

    def comfy_up(self):
        self._calls += 1
        return self._calls > self._up_after

    def _comfy_running(self):
        return self._running

    def start_comfy(self):
        self.started = True
        return True

    def _wait(self, check, *a, **k):
        return any(check() for _ in range(5))

    def ease(self, which):
        pass

    def log(self, m):
        self.logs.append(m)


def test_open_but_slow_comfy_is_waited_for_not_started_again():
    s = FakeServices(running=True, up_after=2)
    assert s.ensure_comfy() and not s.started
    assert any("instead of starting it again" in m for m in s.logs)


def test_closed_comfy_is_started():
    s = FakeServices(running=False, up_after=1)
    assert s.ensure_comfy() and s.started
