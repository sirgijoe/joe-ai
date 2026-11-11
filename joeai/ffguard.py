"""Every FFmpeg run may only read local files and pipes (2.3).

People hand Joe pictures, videos and sound made by anyone. A media file can point FFmpeg at other
places to read from (a playlist naming web addresses, a "concat" list, a link to another file over
the network...). -protocol_whitelist file,pipe,fd in front of each input stops that: FFmpeg reads
the file it was given and Joe's own temporary files, and nothing over the network.

It's put in at one place for every FFmpeg call Joe makes, so a new tool can't forget it: install()
(run when the joeai package is imported) makes subprocess.Popen add it to any command whose program
is ffmpeg. Nothing else about any command changes.
"""
from __future__ import annotations

import os
import subprocess

WHITELIST = "file,pipe,fd"
_FLAG = "-protocol_whitelist"


def is_ffmpeg(prog) -> bool:
    name = os.path.basename(str(prog).replace("\\", "/")).lower()
    return name.split(".")[0] == "ffmpeg"


def guard(args):
    """The same command with -protocol_whitelist before every -i (only for ffmpeg)."""
    if isinstance(args, (str, bytes)) or not isinstance(args, (list, tuple)) or not args:
        return args
    if not is_ffmpeg(args[0]):
        return args
    out = [args[0]]
    rest = list(args[1:])
    for i, a in enumerate(rest):
        if str(a) == "-i" and not (len(out) >= 2 and str(out[-2]) == _FLAG):
            out += [_FLAG, WHITELIST]
        out.append(a)
    return out


class _GuardedPopen(subprocess.Popen):
    def __init__(self, args, *a, **k):
        super().__init__(guard(args), *a, **k)


def install() -> None:
    if not getattr(subprocess.Popen, "_joe_guard", False):
        _GuardedPopen._joe_guard = True
        subprocess.Popen = _GuardedPopen
