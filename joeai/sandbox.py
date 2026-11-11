"""The sandbox: Joe reads and writes ONLY inside its workspace folder.

Layout:
    <workspace>/Inbox      files you drop in for jobs to read
    <workspace>/Output     everything Joe writes
    <workspace>/Projects   project profiles (brand rules, facts)
    <workspace>/Missions   saved mission blocks
    <workspace>/Workflows  ComfyUI workflows (API format) for image/video tasks
    <workspace>/Themes     custom color themes (JSON, made in F10 or by hand)
"""
from __future__ import annotations

import os
import re
from pathlib import Path

SUBFOLDERS = ("Inbox", "Output", "Projects", "Missions", "Workflows", "Themes")
_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


class SandboxError(ValueError):
    """Raised when a path would escape the workspace or is not allowed."""


class Sandbox:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

    def ensure(self) -> "Sandbox":
        for name in SUBFOLDERS:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        return self

    @property
    def inbox(self) -> Path: return self.root / "Inbox"
    @property
    def output(self) -> Path: return self.root / "Output"
    @property
    def projects(self) -> Path: return self.root / "Projects"
    @property
    def missions(self) -> Path: return self.root / "Missions"
    @property
    def meta(self) -> Path:
        """Joe's bookkeeping (state, run log, old reports)."""
        return self.output / ".joe"
    @property
    def workflows(self) -> Path: return self.root / "Workflows"
    @property
    def themes(self) -> Path: return self.root / "Themes"

    def resolve(self, rel: str | os.PathLike, base: str = "Output") -> Path:
        """Turn a user/mission-supplied relative path into a safe absolute path.

        Rejects absolute paths, drive letters, '..', reserved device names,
        illegal characters, and anything (incl. symlinks) that lands outside.
        """
        raw = str(rel).strip().replace("\\", "/")
        if not raw:
            raise SandboxError("empty path")
        if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw) or raw.startswith("//"):
            raise SandboxError(f"absolute paths are not allowed: {rel}")
        parts = [p for p in raw.split("/") if p not in ("", ".")]
        for p in parts:
            if p == "..":
                raise SandboxError(f"'..' is not allowed: {rel}")
            if _BAD_CHARS.search(p):
                raise SandboxError(f"illegal character in: {p}")
            if p.split(".")[0].upper() in _RESERVED:
                raise SandboxError(f"reserved name: {p}")
            if p.endswith((" ", ".")):
                raise SandboxError(f"name can't end with space or dot: {p}")
        # Allow a leading 'Output/' etc. so missions can say either form.
        if parts and parts[0] in SUBFOLDERS:
            base_dir = self.root / parts[0]
            parts = parts[1:]
        else:
            base_dir = self.root / base
        target = base_dir.joinpath(*parts) if parts else base_dir
        self.check(target)
        return target

    def resolve_input(self, rel: str | os.PathLike) -> Path:
        """An INPUT / FROM-file path from a mission: like resolve() from Inbox, but never one of
        Joe's private folders (names starting with a dot, like Output/.joe = chats and run state),
        whoever wrote the mission."""
        target = self.resolve(rel, base="Inbox")
        self.check_not_private(target)
        return target

    def check_not_private(self, path: Path) -> Path:
        for p in (Path(path), Path(os.path.realpath(path))):
            try:
                parts = p.relative_to(self.root).parts
            except ValueError:
                continue
            if any(part.startswith(".") for part in parts):
                raise SandboxError(f"that's one of Joe's private folders: {path.name}")
        return path

    def check(self, path: Path) -> Path:
        """Verify an absolute path (after following symlinks) is inside root."""
        real = Path(os.path.realpath(path))
        try:
            real.relative_to(self.root)
        except ValueError:
            raise SandboxError(f"outside the workspace: {path}") from None
        return path
