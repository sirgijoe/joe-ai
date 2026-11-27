"""Repo status and bundle sync: what state a project folder is in, and whether it matches a git bundle.

Why: a cloud AI chat works on the owner's project through git bundles that are carried back and forth by
hand. Before it builds on a bundle, or after the owner says "I pulled it in", it needs to see in a few
lines what the folder on this PC holds: which branch, the last commit, uncommitted changes, and whether
the folder has the same commits as a given bundle. When the owner asks for it in that request, Joe can
also bring a bundle in, but only as a fast-forward that can't lose any work.

Rules (every git call goes through _git, which enforces them):
  - status() changes nothing at all: read-only git commands with --no-optional-locks, so not even the
    index is refreshed. pull_bundle() is the only thing that changes anything, and only by fast-forward.
  - Never a push, never a URL, never the network: the only thing ever fetched is the bundle file, and
    GIT_ALLOW_PROTOCOL=file makes git refuse anything else even if a setting tries to rewrite the path.
  - Never reset, force, delete, or touch another branch. No remote-tracking refs change (--refmap=).
  - Nothing in the folder's own git settings can run a program: no hooks (core.hooksPath points at an
    empty folder of Joe's own), no fsmonitor, no pager, no credential helper, no signature checks, no
    automatic gc, no submodule recursion, and file filters set in the folder's own settings are switched
    off. (Filters from the owner's own global settings, like Git LFS, still work.)
  - git only looks in the folder itself, never in a folder above it (GIT_CEILING_DIRECTORIES), and the
    folder's settings can't point the work at a different folder (core.worktree is checked).
  - The bundle and the folder's contents are not trusted: branch names are checked before use, object
    names from the bundle must be plain hex, file names are shown with control characters escaped, and
    only paths are ever reported, never file contents or diffs.
Standard library only; works on Windows, Mac and Linux.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .system import WINDOWS, no_window_flags

READ_TIMEOUT = 30               # seconds for a read-only git call
WRITE_TIMEOUT = 300             # seconds for fetch / merge
MAX_PATHS = 20                  # uncommitted paths listed by name
MAX_SUBJECT = 80                # characters of a commit message's first line
MAX_HEADER = 1_000_000          # bytes of a bundle's text header read by Joe itself

_BUNDLE_SIGNATURES = (b"# v2 git bundle\n", b"# v3 git bundle\n")
_HEX = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_BAD_BRANCH = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]|\.\.|@\{|//|/$|\.lock$|^/|^@$|\.$")
_DROP_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
             "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
             "GIT_EXTERNAL_DIFF", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_ASKPASS", "SSH_ASKPASS", "GIT_PROXY_COMMAND",
             "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_QUARANTINE_PATH")
_IN_PROGRESS = {"MERGE_HEAD": "a merge", "rebase-merge": "a rebase", "rebase-apply": "a rebase or patch",
                "CHERRY_PICK_HEAD": "a cherry-pick", "REVERT_HEAD": "a revert", "BISECT_LOG": "a bisect"}
_STAGED = {"M": "staged change", "A": "staged new file", "D": "staged delete", "R": "staged rename",
           "C": "staged copy", "T": "staged type change"}
_CHANGED = {"M": "changed", "D": "deleted", "T": "type changed", "A": "new"}
_no_hooks_dir: str | None = None


class GitError(Exception):
    """A plain sentence for the person; raised inside this module, always caught before returning."""


@dataclass
class Result:
    code: int
    out: str
    err: str


# --------------------------------------------------------------------------- running git safely
def _empty_hooks_dir() -> str:
    """A private, empty folder of Joe's own for core.hooksPath, so no hook in the folder ever runs."""
    global _no_hooks_dir
    d = _no_hooks_dir
    if d is None or not os.path.isdir(d) or os.listdir(d):
        d = _no_hooks_dir = tempfile.mkdtemp(prefix="joe-no-hooks-")
    return d


def _env(folder: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _DROP_ENV and not k.startswith("GIT_CONFIG_KEY_")
           and not k.startswith("GIT_CONFIG_VALUE_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", LC_ALL="C", LANGUAGE="C", GIT_PAGER="cat", PAGER="cat",
               GIT_ALLOW_PROTOCOL="file", GIT_MERGE_AUTOEDIT="no", GCM_INTERACTIVE="never",
               GIT_CEILING_DIRECTORIES=str(folder.parent),
               GIT_LFS_SKIP_SMUDGE="1")      # Git LFS never downloads here (a bundle's .lfsconfig could name any address);
    #                                          big files come in as pointers until the person runs "git lfs pull" themselves
    return env


def _safe_config(extra: tuple[str, ...] = ()) -> list[str]:
    pairs = ("core.fsmonitor=false", "core.pager=cat", f"core.hooksPath={_empty_hooks_dir()}", "credential.helper=",
             "color.ui=false", "log.showSignature=false", "merge.verifySignatures=false", "gc.auto=0",
             "maintenance.auto=false", "submodule.recurse=false", "fetch.recurseSubmodules=false",
             "fetch.writeCommitGraph=false", "fetch.fsckObjects=true", "safe.bareRepository=explicit",
             "core.sshCommand=", "merge.autoStash=false", "advice.detachedHead=false") + extra
    out: list[str] = []
    for p in pairs:
        out += ["-c", p]
    return out


def _git(folder: Path, *args: str, write: bool = False, filters: tuple[str, ...] = ()) -> Result:
    """Run one git command in `folder` under the rules in the module docstring. Never raises for git's own
    errors (see .code); raises GitError when git is missing, won't start, or takes too long."""
    exe = shutil.which("git")
    if not exe:
        raise GitError("Git isn't installed on this computer, so Joe can't read this project's history.")
    cmd = [exe, "--no-pager"] + ([] if write else ["--no-optional-locks"]) + _safe_config(filters) + list(args)
    kw = {"creationflags": no_window_flags()} if WINDOWS else {}
    timeout = WRITE_TIMEOUT if write else READ_TIMEOUT
    try:
        p = subprocess.run(cmd, cwd=str(folder), env=_env(folder), capture_output=True, encoding="utf-8",
                           errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, **kw)
    except subprocess.TimeoutExpired:
        raise GitError(f"Git took longer than {timeout} seconds, so Joe stopped it.") from None
    except OSError as e:
        raise GitError(f"Git couldn't be started ({e.strerror or e}).") from None
    return Result(p.returncode, p.stdout or "", p.stderr or "")


def _local_filters(folder: Path) -> tuple[str, ...]:
    """Config pairs that switch off every file filter defined in the folder's own settings (a filter is a
    program git runs on file contents). Filters from the owner's global or system settings are left alone."""
    out: list[str] = []
    for scope in ("--local", "--worktree"):
        # --includes: a filter set in a file the folder's settings pull in (include.path) counts too (2026-11-27 review)
        r = _git(folder, "config", scope, "--includes", "--null", "--name-only", "--get-regexp", r"^filter\.")
        for name in r.out.split("\0") if r.code == 0 else []:
            parts = name.split(".")
            if len(parts) >= 3:
                driver = ".".join(parts[1:-1])
                out += [f"filter.{driver}.clean=", f"filter.{driver}.smudge=", f"filter.{driver}.process=",
                        f"filter.{driver}.required=false"]
    return tuple(dict.fromkeys(out))


# --------------------------------------------------------------------------- small helpers
def _show(path: str) -> str:
    """A file name safe to put on one line: control characters escaped, odd edges quoted."""
    s = "".join(c if c >= " " and c != "\x7f" else repr(c)[1:-1] for c in path)
    return f'"{s}"' if s != s.strip() or not s else s


def _short(oid: str) -> str:
    return oid[:8]


def _check_repo(folder: Path) -> str:
    """'' when `folder` is the top of a git repository Joe can work in, else a plain sentence why not."""
    if not folder.is_dir():
        return f"{folder} isn't a folder Joe can find."
    try:
        r = _git(folder, "rev-parse", "--show-toplevel")
    except GitError as e:
        return str(e)
    if r.code != 0:
        if "dubious ownership" in r.err:
            return ("Git won't read this folder because it belongs to a different user account on this computer "
                    "(git's 'safe.directory' rule).")
        return "This folder isn't a git repository (no project history here)."
    top = r.out.strip()
    try:
        same = Path(top).resolve() == folder.resolve()
    except OSError:
        same = False
    if not same:
        return "This folder's git settings point at a different folder for its files, so Joe won't use it."
    return ""


def _git_dir(folder: Path) -> Path:
    r = _git(folder, "rev-parse", "--absolute-git-dir")
    return Path(r.out.strip()) if r.code == 0 and r.out.strip() else Path("")


def _in_progress(folder: Path) -> str:
    """'a merge', 'a rebase', ... when one is half done in this folder, else ''."""
    gd = _git_dir(folder)
    if not gd.is_absolute():
        return ""
    for name, what in _IN_PROGRESS.items():
        if (gd / name).exists():
            return what
    return ""


# --------------------------------------------------------------------------- the working tree
@dataclass
class Tree:
    oid: str = ""                   # '' = no commits yet
    branch: str = ""                # '' = detached
    upstream: str = ""
    ab: tuple[int, int] | None = None
    changed: int = 0
    staged: int = 0
    untracked: int = 0
    conflicted: int = 0
    paths: list[tuple[str, str]] = field(default_factory=list)  # (path, state), every entry

    @property
    def tracked_dirty(self) -> bool:
        return bool(self.changed or self.staged or self.conflicted)

    @property
    def total(self) -> int:
        return len(self.paths)


def _state(xy: str) -> str:
    x, y = (xy + "..")[:2]
    words = [_STAGED[x]] if x in _STAGED else []
    if y in _CHANGED:
        words.append(_CHANGED[y])
    return ", ".join(words) or "changed"


def _read_tree(folder: Path, filters: tuple[str, ...]) -> Tree:
    r = _git(folder, "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=normal",
             "--ignore-submodules=none", "--no-renames", filters=filters)
    if r.code != 0:
        raise GitError("Git couldn't read this folder's status: " + (r.err.strip().splitlines() or ["unknown error"])[-1])
    t = Tree()
    records = r.out.split("\0")
    i = 0
    while i < len(records):
        rec = records[i]
        i += 1
        if not rec:
            continue
        kind = rec[0]
        if rec.startswith("# branch.oid "):
            v = rec[13:].strip()
            t.oid = v if _HEX.match(v) else ""
        elif rec.startswith("# branch.head "):
            v = rec[14:]
            t.branch = "" if v == "(detached)" else v
        elif rec.startswith("# branch.upstream "):
            t.upstream = rec[18:]
        elif rec.startswith("# branch.ab "):
            m = re.match(r"\+(\d+) -(\d+)", rec[12:])
            if m:
                t.ab = (int(m.group(1)), int(m.group(2)))
        elif kind == "1":
            parts = rec.split(" ", 8)
            if len(parts) == 9:
                _add(t, parts[1], parts[8])
        elif kind == "2":
            parts = rec.split(" ", 9)
            i += 1                                      # the original path is its own record
            if len(parts) == 10:
                _add(t, parts[1], parts[9])
        elif kind == "u":
            parts = rec.split(" ", 10)
            if len(parts) == 11:
                t.conflicted += 1
                t.paths.append((parts[10], "conflict"))
        elif kind == "?":
            t.untracked += 1
            t.paths.append((rec[2:], "untracked"))
    return t


def _add(t: Tree, xy: str, path: str) -> None:
    if xy[:1] not in ".":
        t.staged += 1
    if xy[1:2] not in ".":
        t.changed += 1
    t.paths.append((path, _state(xy)))


def _stash_count(folder: Path) -> int:
    if _git(folder, "rev-parse", "-q", "--verify", "refs/stash").code != 0:
        return 0
    r = _git(folder, "rev-list", "--walk-reflogs", "--count", "refs/stash", "--")
    return int(r.out.strip()) if r.code == 0 and r.out.strip().isdigit() else 1


def _last_commit(folder: Path) -> str:
    r = _git(folder, "log", "-1", "--no-show-signature", "--no-color", "--format=%H%x00%ci%x00%B", "HEAD", "--")
    parts = r.out.split("\0", 2) if r.code == 0 else []
    if len(parts) != 3:
        return "Last commit: none yet"
    subject = _show((parts[2].strip().splitlines() or [""])[0])
    if len(subject) > MAX_SUBJECT:
        subject = subject[:MAX_SUBJECT - 3] + "..."
    return f"Last commit: {_short(parts[0])}, {parts[1][:16]}, {subject}"


# --------------------------------------------------------------------------- bundles
@dataclass
class Bundle:
    ok: bool
    problem: str = ""
    heads: dict[str, str] = field(default_factory=dict)     # full ref name -> oid
    prereqs: list[str] = field(default_factory=list)


def _bundle_header_prereqs(bundle: Path) -> list[str]:
    """The commits a bundle says it builds on ('-<oid>' lines in its text header). Read by Joe, size-capped."""
    out: list[str] = []
    try:
        with open(bundle, "rb") as f:
            head = f.read(MAX_HEADER)
    except OSError:
        return out
    for raw in head.split(b"\n")[1:]:
        if not raw:
            break
        if raw.startswith(b"-"):
            oid = raw[1:].split(b" ", 1)[0].decode("ascii", "replace")
            if _HEX.match(oid):
                out.append(oid)
    return out


def _pack_intact(bundle: Path) -> bool:
    """True when the pack inside the bundle ends with the right checksum of everything before it.
    (git bundle verify only checks the text header, so a cut-off or damaged download would pass it.)"""
    try:
        with open(bundle, "rb") as f:
            first = f.readline(100)
            if first not in _BUNDLE_SIGNATURES:
                return False
            algo = "sha1"
            while True:
                line = f.readline(MAX_HEADER)
                if not line or not line.endswith(b"\n"):
                    return False
                if line == b"\n":
                    break
                if line.startswith(b"@object-format="):
                    algo = line.strip().split(b"=", 1)[1].decode("ascii", "replace")
            if algo not in ("sha1", "sha256"):
                return False
            h, size = hashlib.new(algo), hashlib.new(algo).digest_size
            tail = b""
            started = False
            while chunk := f.read(1 << 20):
                if not started:
                    if not (tail + chunk).startswith(b"PACK"):
                        return False
                    started = True
                data = tail + chunk
                h.update(data[:-size])
                tail = data[-size:]
            return started and len(tail) == size and h.digest() == tail
    except OSError:
        return False


def _read_bundle(folder: Path, bundle: Path) -> Bundle:
    path = str(bundle.resolve())
    if not os.path.isfile(path):
        return Bundle(False, "the bundle file isn't there")
    try:
        with open(path, "rb") as f:
            looks_right = f.readline(100) in _BUNDLE_SIGNATURES
    except OSError:
        return Bundle(False, "the bundle file can't be read")
    if not looks_right:
        return Bundle(False, "the file isn't a git bundle")
    r = _git(folder, "bundle", "verify", "--", path)
    if r.code != 0:
        missing = [p for p in _bundle_header_prereqs(bundle) if not _has_commit(folder, p)]
        if missing or "lacks these prerequisite" in r.err.lower():
            return Bundle(False, "it builds on commits this folder doesn't have")
        return Bundle(False, "the bundle is damaged (git bundle verify failed)")
    if not _pack_intact(bundle):
        return Bundle(False, "the bundle is damaged or cut short (its contents don't match their checksum)")
    lr = _git(folder, "bundle", "list-heads", "--", path)
    heads: dict[str, str] = {}
    for line in lr.out.splitlines() if lr.code == 0 else []:
        oid, _, ref = line.partition(" ")
        if _HEX.match(oid) and ref:
            heads[ref] = oid
    return Bundle(True, heads=heads, prereqs=_bundle_header_prereqs(bundle))


def _has_commit(folder: Path, oid: str) -> bool:
    return _git(folder, "cat-file", "-e", f"{oid}^{{commit}}").code == 0


def _is_ancestor(folder: Path, a: str, b: str) -> bool:
    return _git(folder, "merge-base", "--is-ancestor", a, b).code == 0


def _counts(folder: Path, local: str, other: str) -> tuple[int, int] | None:
    """(commits only local has, commits only `other` has), or None when git can't say."""
    r = _git(folder, "rev-list", "--left-right", "--count", f"{local}...{other}", "--")
    m = re.match(r"^(\d+)\s+(\d+)\s*$", r.out) if r.code == 0 else None
    return (int(m.group(1)), int(m.group(2))) if m else None


def _local_branches(folder: Path) -> dict[str, str]:
    r = _git(folder, "for-each-ref", "--format=%(objectname) %(refname)", "refs/heads/")
    out: dict[str, str] = {}
    for line in r.out.splitlines() if r.code == 0 else []:
        oid, _, ref = line.partition(" ")
        if _HEX.match(oid):
            out[ref] = oid
    return out


def _compare(folder: Path, b: Bundle, ref: str, oid: str, local: dict[str, str]) -> tuple[str, bool]:
    """(plain words, same?) for one bundle branch against the local branch of the same name."""
    mine = local.get(ref)
    if mine is None:
        return "local has no such branch", False
    if mine == oid:
        return "same", True
    if _has_commit(folder, oid):
        c = _counts(folder, mine, oid)
        if c is None:
            return "can't tell (git couldn't compare them)", False
        ours, theirs = c
        if ours == 0 and theirs == 0:
            return "same", True
        if ours == 0:
            return f"bundle is {theirs} commit{'s' * (theirs != 1)} ahead (pulling would fast-forward)", False
        if theirs == 0:
            return f"local is {ours} commit{'s' * (ours != 1)} ahead of the bundle", False
        return f"they have split (both have commits the other lacks: local {ours}, bundle {theirs})", False
    # The bundle's commit isn't here yet. Only claim a fast-forward when it can be proved: every head in the
    # bundle is this one commit (so everything it builds on is history of this commit) and the local tip
    # is one of those base commits or older than one of them.
    if len(set(b.heads.values())) == 1 and any(p == mine or _is_ancestor(folder, mine, p) for p in b.prereqs):
        return "bundle is ahead (pulling would likely fast-forward; the count shows after pulling)", False
    return "can't tell without pulling (the bundle's commit isn't in this repo yet)", False


def _branch_name(ref: str) -> str:
    return ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref


def _bundle_lines(folder: Path, bundle: Path, t: Tree) -> list[str]:
    b = _read_bundle(folder, bundle)
    lines = [f"Bundle: {_show(bundle.name)}"]
    if not b.ok:
        return lines + [f"  Not usable: {b.problem}.", f"This folder does NOT match the bundle: {b.problem}."]
    branches = {ref: oid for ref, oid in b.heads.items() if ref.startswith("refs/heads/")}
    others = len(b.heads) - len(branches)
    lines.append(f"  Valid bundle with {len(branches)} branch{'es' * (len(branches) != 1)}"
                 + (f" (and {others} other ref{'s' * (others != 1)})" if others else "") + ".")
    if not branches:
        return lines + ["This folder does NOT match the bundle: the bundle holds no branches."]
    local = _local_branches(folder)
    differ: list[str] = []
    for ref, oid in sorted(branches.items()):
        words, same = _compare(folder, b, ref, oid, local)
        name = _show(_branch_name(ref))
        lines.append(f"  {name} ({_short(oid)}): {words}")
        if not same:
            differ.append(f"{name} {words.split(' (')[0]}")
    if differ:
        lines.append("This folder does NOT match the bundle: " + "; ".join(differ) + ".")
    elif t.tracked_dirty or t.untracked:
        n = t.total
        lines.append(f"This folder does NOT match the bundle: same commits, but {n} uncommitted change{'s' * (n != 1)} in the folder.")
    else:
        lines.append("This folder matches the bundle.")
    return lines


# --------------------------------------------------------------------------- public
def status(folder: Path, bundle: Path | None = None) -> str:
    """A short plain-text report on a project folder (and how it compares to `bundle`). Changes nothing."""
    folder = Path(folder)
    problem = _check_repo(folder)
    if problem:
        return problem
    try:
        filters = _local_filters(folder)
        t = _read_tree(folder, filters)
        lines = [f"Folder: {folder}"]
        if t.branch:
            lines.append(f"Branch: {_show(t.branch)}")
        elif t.oid:
            lines.append(f"Branch: none (detached at {_short(t.oid)})")
        lines.append(_last_commit(folder) if t.oid else "Last commit: none yet (no commits in this repo)")
        if not t.paths:
            lines.append("Uncommitted changes: none (clean)")
        else:
            lines.append(f"Uncommitted changes: {t.changed} changed, {t.staged} staged, {t.untracked} untracked, "
                         f"{t.conflicted} conflicted")
            for path, state in t.paths[:MAX_PATHS]:
                lines.append(f"  {_show(path)}  ({state})")
            if t.total > MAX_PATHS:
                lines.append(f"  ... and {t.total - MAX_PATHS} more")
        if not t.branch:
            pass                                        # detached: no branch, so no upstream to compare
        elif not t.upstream:
            lines.append("Upstream: no upstream set")
        elif t.ab is None:
            lines.append(f"Upstream: {_show(t.upstream)} (not found; it may have been deleted)")
        else:
            ahead, behind = t.ab
            lines.append(f"Upstream: {_show(t.upstream)}, {ahead} ahead, {behind} behind (as of the last fetch)")
        stashes = _stash_count(folder)
        if stashes:
            lines.append(f"Stashes: {stashes}")
        busy = _in_progress(folder)
        if busy:
            lines.append(f"Note: {busy} is in progress in this folder.")
        if bundle is not None:
            lines += _bundle_lines(folder, Path(bundle), t)
        return "\n".join(lines)
    except GitError as e:
        return str(e)


def _bad_branch(branch: str) -> bool:
    return (not branch or branch.startswith("-") or bool(_BAD_BRANCH.search(branch))
            or any(not c.isprintable() or c.isspace() for c in branch))


def pull_bundle(folder: Path, bundle: Path, branch: str = "") -> str:
    """Bring the bundle's commits for `branch` (default: the current branch) into the folder, by fast-forward
    only. Refuses with a plain sentence, changing nothing, whenever that isn't safe."""
    folder = Path(folder)
    if branch.startswith("refs/heads/"):
        branch = branch[len("refs/heads/"):]
    if branch and _bad_branch(branch):
        return f"Joe won't use that branch name ({_show(branch)[:60]}): it isn't a plain branch name."
    problem = _check_repo(folder)
    if problem:
        return problem
    try:
        return _pull(folder, Path(bundle), branch)
    except GitError as e:
        return str(e)


def _pull(folder: Path, bundle: Path, branch: str) -> str:
    filters = _local_filters(folder)
    t = _read_tree(folder, filters)
    if not t.branch:
        return "Nothing was changed: this folder isn't on a branch (detached), so there's nothing to fast-forward."
    current = t.branch
    branch = branch or current
    if _bad_branch(branch):
        return f"Nothing was changed: the current branch name ({_show(branch)[:60]}) isn't one Joe will use."
    busy = _in_progress(folder)
    if busy:
        return f"Nothing was changed: {busy} is in progress in this folder. Finish or cancel it first."
    if t.tracked_dirty:
        n = t.changed + t.staged + t.conflicted
        return (f"Nothing was changed: this folder has uncommitted changes to tracked files ({t.changed} changed, "
                f"{t.staged} staged, {t.conflicted} conflicted; {n} in all). Commit or stash them first.")
    b = _read_bundle(folder, bundle)
    if not b.ok:
        return f"Nothing was changed: the bundle can't be used ({b.problem})."
    ref = f"refs/heads/{branch}"
    oid = b.heads.get(ref)
    if oid is None:
        names = ", ".join(_show(_branch_name(r)) for r in sorted(b.heads) if r.startswith("refs/heads/")) or "none"
        return f"Nothing was changed: the bundle has no branch {_show(branch)} (its branches: {names})."
    if branch != current:
        return (f"Nothing was changed: this folder is on {_show(current)}, not {_show(branch)}. "
                f"Joe only fast-forwards the branch the folder is on.")
    old = t.oid
    if old == oid or (old and _has_commit(folder, oid) and _is_ancestor(folder, oid, old)):
        extra = ""
        if old != oid:
            c = _counts(folder, old, oid)
            extra = f" (this folder is {c[0]} commit{'s' * (c[0] != 1)} ahead of the bundle)" if c else ""
        return f"Already up to date: {_show(branch)} at {_short(old)} already has everything in the bundle{extra}."
    if old and _has_commit(folder, oid) and not _is_ancestor(folder, old, oid):
        return ("Nothing was changed: it would not be a fast-forward (this folder and the bundle both have commits "
                "the other lacks). Combine them by hand.")
    path = str(bundle.resolve())
    f = _git(folder, "fetch", "--no-tags", "--no-recurse-submodules", "--no-auto-gc", "--refmap=", "--no-write-commit-graph",
             "--quiet", "--", path, ref, write=True, filters=filters)
    if f.code != 0:
        return "Nothing was changed: git couldn't read the bundle's commits: " + (f.err.strip().splitlines() or ["unknown error"])[-1][:200]
    fh = _git(folder, "rev-parse", "-q", "--verify", "FETCH_HEAD^{commit}").out.strip()
    if fh != oid:
        return "Nothing was changed: the commits read from the bundle weren't the ones it listed, so Joe stopped."
    if old and not _is_ancestor(folder, old, oid):
        return ("Nothing was changed in your files: it would not be a fast-forward (this folder and the bundle both have "
                "commits the other lacks). The bundle's commits are stored but no branch points at them.")
    m = _git(folder, "merge", "--ff-only", "--no-edit", "--no-stat", "--no-verify-signatures", "--no-autostash", "--quiet",
             oid, write=True, filters=filters)
    if m.code != 0:
        why = (m.err.strip().splitlines() or ["unknown error"])
        return "Nothing was changed: git refused the fast-forward: " + " ".join(why)[:300]
    new = _git(folder, "rev-parse", "-q", "--verify", "HEAD^{commit}").out.strip()
    if old:
        brought = _counts(folder, old, new)
        n = brought[1] if brought else 0
        d = _git(folder, "diff-tree", "-r", "-z", "--name-only", "--no-commit-id", "--no-renames", "--no-ext-diff",
                 "--no-textconv", old, new, "--")
    else:
        r = _git(folder, "rev-list", "--count", new, "--")
        n = int(r.out.strip()) if r.out.strip().isdigit() else 0
        d = _git(folder, "ls-tree", "-r", "-z", "--name-only", new, "--")
    files = len([p for p in d.out.split("\0") if p]) if d.code == 0 else 0
    return (f"Pulled the bundle into {_show(branch)}: {_short(old) if old else '(no commits)'} -> {_short(new)}, "
            f"{n} commit{'s' * (n != 1)} brought in, {files} file{'s' * (files != 1)} changed.")
