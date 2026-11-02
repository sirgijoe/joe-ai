"""Keep the PC awake during a run, and optional sleep/shutdown afterwards."""
from __future__ import annotations

import contextlib
import subprocess
import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


@contextlib.contextmanager
def keep_awake(enabled: bool = True):
    if not enabled or sys.platform != "win32":
        yield
        return
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    try:
        yield
    finally:
        k32.SetThreadExecutionState(ES_CONTINUOUS)


def when_finished(action: str, log=print) -> None:
    if sys.platform != "win32" or action not in ("sleep", "shutdown"):
        return
    if action == "shutdown":
        log("Shutting down in 120 s (run 'shutdown /a' to cancel).")
        subprocess.run(["shutdown", "/s", "/t", "120", "/c", "Joe finished."], check=False)
    else:
        log("Putting PC to sleep.")
        subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=False)
