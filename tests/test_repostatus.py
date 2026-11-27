"""repostatus.py: a project folder's state and how it compares to a git bundle, for connected AI apps.

Every test makes real throwaway repositories in tmp_path with the real git. The tests' own git calls use
no global or system settings (each repo gets its own user.name/email), so they behave the same on every PC.
Refusals are checked by taking a snapshot of HEAD, every ref, the index and every working file before and
after: a refusal must leave all of it exactly as it was."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from joeai import repostatus

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git isn't installed")


# --------------------------------------------------------------------------- helpers
def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(k, None)
    return env


def g(repo: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, encoding="utf-8", errors="replace",
                       env=_env(), stdin=subprocess.DEVNULL)
    if check and p.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {p.stderr}")
    return p.stdout.strip()


def make_repo(path: Path, files: dict[str, str] | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    g(path, "init", "-q", "-b", "main")
    g(path, "config", "user.name", "Tester")
    g(path, "config", "user.email", "tester@example.invalid")
    g(path, "config", "commit.gpgsign", "false")
    commit(path, files or {"readme.txt": "hello\n"}, "first commit")
    return path


def commit(repo: Path, files: dict[str, str], msg: str) -> str:
    for name, text in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        g(repo, "add", "--", name)
    g(repo, "commit", "-q", "-m", msg)
    return g(repo, "rev-parse", "HEAD")


def clone(src: Path, dst: Path) -> Path:
    subprocess.run(["git", "clone", "-q", str(src), str(dst)], check=True, env=_env(), capture_output=True)
    g(dst, "config", "user.name", "Tester")
    g(dst, "config", "user.email", "tester@example.invalid")
    return dst


def bundle(repo: Path, out: Path, *revs: str) -> Path:
    g(repo, "bundle", "create", str(out), *revs)
    return out


def snapshot(repo: Path) -> dict:
    """HEAD, every ref, the index's bytes and every working file's bytes."""
    files = {}
    for p in sorted(repo.rglob("*")):
        if ".git" in p.relative_to(repo).parts or not p.is_file():
            continue
        files[str(p.relative_to(repo))] = p.read_bytes()
    index = repo / ".git" / "index"
    return {"head": (repo / ".git" / "HEAD").read_text(), "head_oid": g(repo, "rev-parse", "-q", "--verify", "HEAD", check=False),
            "refs": g(repo, "for-each-ref", "--format=%(objectname) %(refname)"),
            "index": index.read_bytes() if index.exists() else b"", "files": files}


def git_dir_fingerprint(repo: Path) -> dict:
    """A hash of every file under .git, plus the index's modification time."""
    out = {}
    for p in sorted((repo / ".git").rglob("*")):
        if p.is_file():
            out[str(p.relative_to(repo))] = hashlib.sha256(p.read_bytes()).hexdigest()
    out["index mtime"] = (repo / ".git" / "index").stat().st_mtime_ns
    return out


def short(oid: str) -> str:
    return oid[:8]


# --------------------------------------------------------------------------- not a repo / no git
def test_not_a_repo(tmp_path):
    (tmp_path / "plain").mkdir()
    assert repostatus.status(tmp_path / "plain") == "This folder isn't a git repository (no project history here)."
    assert "isn't a git repository" in repostatus.pull_bundle(tmp_path / "plain", tmp_path / "x.bundle")
    assert "isn't a folder" in repostatus.status(tmp_path / "missing")


def test_subfolder_of_a_repo_is_not_treated_as_the_repo(tmp_path):
    """git never looks above the folder it was given (the repo above may hold things the app wasn't given)."""
    repo = make_repo(tmp_path / "r")
    (repo / "sub").mkdir()
    assert "isn't a git repository" in repostatus.status(repo / "sub")


def test_git_not_installed(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "r")
    monkeypatch.setattr(repostatus.shutil, "which", lambda name: None)
    assert repostatus.status(repo).startswith("Git isn't installed on this computer")
    assert repostatus.pull_bundle(repo, tmp_path / "b").startswith("Git isn't installed on this computer")


# --------------------------------------------------------------------------- status
def test_clean_repo(tmp_path):
    repo = make_repo(tmp_path / "r")
    head = g(repo, "rev-parse", "HEAD")
    out = repostatus.status(repo)
    assert "Branch: main" in out
    assert f"Last commit: {short(head)}, " in out and out.splitlines()[2].endswith(", first commit")
    assert "Uncommitted changes: none (clean)" in out
    assert "Upstream: no upstream set" in out
    assert "Stashes" not in out


def test_long_commit_message_is_cut(tmp_path):
    repo = make_repo(tmp_path / "r")
    commit(repo, {"a.txt": "a"}, "x" * 200 + "\n\nbody text that never shows")
    line = [ln for ln in repostatus.status(repo).splitlines() if ln.startswith("Last commit:")][0]
    assert line.endswith("...") and "body" not in line and line.count("x") == repostatus.MAX_SUBJECT - 3


def test_counts_of_changed_staged_untracked(tmp_path):
    repo = make_repo(tmp_path / "r", {"a.txt": "a\n", "b.txt": "b\n", "c.txt": "c\n"})
    (repo / "a.txt").write_text("changed\n")                        # changed, not staged
    (repo / "b.txt").write_text("staged\n")
    g(repo, "add", "b.txt")                                         # staged
    (repo / "c.txt").write_text("staged\n")
    g(repo, "add", "c.txt")
    (repo / "c.txt").write_text("and changed again\n")              # staged and changed
    (repo / "new.txt").write_text("new\n")                          # untracked
    g(repo, "rm", "-q", "--cached", "--", "a.txt", check=False)
    g(repo, "reset", "-q", "--", "a.txt")
    out = repostatus.status(repo)
    assert "Uncommitted changes: 2 changed, 2 staged, 1 untracked, 0 conflicted" in out
    assert "  a.txt  (changed)" in out
    assert "  b.txt  (staged change)" in out
    assert "  c.txt  (staged change, changed)" in out
    assert "  new.txt  (untracked)" in out
    assert "hello" not in out and "staged\n" not in out              # never file contents


def test_twenty_path_cap(tmp_path):
    repo = make_repo(tmp_path / "r")
    for i in range(27):
        (repo / f"f{i:02}.txt").write_text("x")
    out = repostatus.status(repo)
    assert "27 untracked" in out
    assert sum(1 for ln in out.splitlines() if ln.endswith("(untracked)")) == 20
    assert "  ... and 7 more" in out
    assert len(out.splitlines()) < 40


def test_conflict_and_merge_in_progress(tmp_path):
    repo = make_repo(tmp_path / "r", {"a.txt": "base\n"})
    g(repo, "checkout", "-q", "-b", "other")
    commit(repo, {"a.txt": "other\n"}, "other side")
    g(repo, "checkout", "-q", "main")
    commit(repo, {"a.txt": "main\n"}, "main side")
    g(repo, "merge", "other", check=False)
    out = repostatus.status(repo)
    assert "0 changed, 0 staged, 0 untracked, 1 conflicted" in out
    assert "  a.txt  (conflict)" in out
    assert "Note: a merge is in progress in this folder." in out


def test_detached_head(tmp_path):
    repo = make_repo(tmp_path / "r")
    first = g(repo, "rev-parse", "HEAD")
    commit(repo, {"b.txt": "b"}, "second")
    g(repo, "checkout", "-q", "--detach", first)
    out = repostatus.status(repo)
    assert f"Branch: none (detached at {short(first)})" in out
    assert "Upstream" not in out


def test_empty_repo(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    g(repo, "init", "-q", "-b", "main")
    out = repostatus.status(repo)
    assert "Branch: main" in out and "Last commit: none yet" in out and "clean" in out


def test_ahead_behind_upstream_as_of_last_fetch(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True, env=_env())
    repo = make_repo(tmp_path / "r")
    g(repo, "remote", "add", "origin", str(bare))
    g(repo, "push", "-q", "-u", "origin", "main")
    commit(repo, {"local.txt": "1"}, "local only")
    other = clone(bare, tmp_path / "other")
    commit(other, {"theirs.txt": "1"}, "theirs")
    g(other, "push", "-q", "origin", "main")
    out = repostatus.status(repo)
    assert "Upstream: origin/main, 1 ahead, 0 behind (as of the last fetch)" in out     # status() never fetches
    g(repo, "fetch", "-q", "origin")
    assert "Upstream: origin/main, 1 ahead, 1 behind (as of the last fetch)" in repostatus.status(repo)


def test_stash_count(tmp_path):
    repo = make_repo(tmp_path / "r")
    for i in range(2):
        (repo / "readme.txt").write_text(f"change {i}\n")
        g(repo, "stash", "-q")
    assert "Stashes: 2" in repostatus.status(repo)


def test_odd_file_names(tmp_path):
    repo = make_repo(tmp_path / "my project ünï")
    names = ["my file.txt", "ünïcødé ñame.txt", "it's 'quoted'.txt"]
    if not sys.platform.startswith("win"):                    # Windows allows neither " nor a line break in a file name
        names += ['we"ird.txt', "new\nline.txt"]
    for n in names:
        (repo / n).write_text("x", encoding="utf-8")
    commit(repo, {"space dir/inner file.txt": "1"}, "a commit with a\nsecond line")
    (repo / "space dir" / "inner file.txt").write_text("2")
    out = repostatus.status(repo)
    assert f"1 changed, 0 staged, {len(names)} untracked, 0 conflicted" in out
    assert "  space dir/inner file.txt  (changed)" in out
    assert "  my file.txt  (untracked)" in out
    assert "  ünïcødé ñame.txt  (untracked)" in out
    assert "  it's 'quoted'.txt  (untracked)" in out
    if 'we"ird.txt' in names:
        assert '  we"ird.txt  (untracked)' in out
    if "new\nline.txt" in names:
        assert "  new\\nline.txt  (untracked)" in out
    assert out.splitlines()[2].endswith("a commit with a")


# --------------------------------------------------------------------------- status with a bundle
def test_bundle_same(tmp_path):
    repo = make_repo(tmp_path / "r")
    b = bundle(repo, tmp_path / "same.bundle", "main")
    out = repostatus.status(repo, b)
    assert "Valid bundle with 1 branch." in out
    assert f"  main ({short(g(repo, 'rev-parse', 'HEAD'))}): same" in out
    assert out.endswith("This folder matches the bundle.")


def test_bundle_same_commits_but_uncommitted_changes(tmp_path):
    repo = make_repo(tmp_path / "r")
    b = bundle(repo, tmp_path / "same.bundle", "main")
    (repo / "readme.txt").write_text("edited\n")
    assert repostatus.status(repo, b).endswith("This folder does NOT match the bundle: same commits, but 1 uncommitted change in the folder.")


def test_bundle_ahead_counted(tmp_path):
    repo = make_repo(tmp_path / "r")
    commit(repo, {"a.txt": "1"}, "two")
    commit(repo, {"a.txt": "2"}, "three")
    b = bundle(repo, tmp_path / "ahead.bundle", "main")
    g(repo, "reset", "-q", "--hard", "HEAD~2")                      # the commits stay in the repo's objects
    out = repostatus.status(repo, b)
    assert "bundle is 2 commits ahead (pulling would fast-forward)" in out
    assert out.endswith("This folder does NOT match the bundle: main bundle is 2 commits ahead.")


def test_local_ahead_of_bundle(tmp_path):
    repo = make_repo(tmp_path / "r")
    b = bundle(repo, tmp_path / "old.bundle", "main")
    commit(repo, {"a.txt": "1"}, "two")
    out = repostatus.status(repo, b)
    assert "local is 1 commit ahead of the bundle" in out and "does NOT match" in out


def test_split(tmp_path):
    repo = make_repo(tmp_path / "r")
    commit(repo, {"a.txt": "bundle side"}, "bundle side")
    b = bundle(repo, tmp_path / "split.bundle", "main")
    g(repo, "reset", "-q", "--hard", "HEAD~1")
    commit(repo, {"b.txt": "local side"}, "local side")
    out = repostatus.status(repo, b)
    assert "they have split (both have commits the other lacks: local 1, bundle 1)" in out
    assert "does NOT match the bundle: main they have split" in out


def test_bundle_branch_missing_locally(tmp_path):
    repo = make_repo(tmp_path / "r")
    g(repo, "branch", "feature")
    b = bundle(repo, tmp_path / "feat.bundle", "feature", "main")
    g(repo, "branch", "-D", "feature")
    out = repostatus.status(repo, b)
    assert "Valid bundle with 2 branches." in out
    assert "  feature (" in out and "local has no such branch" in out
    assert "): same" in out                                       # main is still the same


def test_corrupt_bundle(tmp_path):
    repo = make_repo(tmp_path / "r")
    bad = tmp_path / "bad.bundle"
    bad.write_bytes(b"this is not a bundle\n\x00\x01junk")
    out = repostatus.status(repo, bad)
    assert "Not usable: the file isn't a git bundle." in out
    assert out.endswith("This folder does NOT match the bundle: the file isn't a git bundle.")
    real = bundle(repo, tmp_path / "real.bundle", "main")
    cut = tmp_path / "cut.bundle"
    cut.write_bytes(real.read_bytes()[:-30])                       # a damaged pack
    assert "Not usable: the bundle is damaged or cut short" in repostatus.status(repo, cut)
    flipped = bytearray(real.read_bytes())
    flipped[-40] ^= 0xFF                                           # one damaged byte in the middle of the pack
    (tmp_path / "flipped.bundle").write_bytes(bytes(flipped))
    assert "Not usable: the bundle is damaged" in repostatus.status(repo, tmp_path / "flipped.bundle")
    assert "Valid bundle" in repostatus.status(repo, real)
    assert "Not usable: the bundle file isn't there" in repostatus.status(repo, tmp_path / "nope.bundle")


def test_bundle_commits_not_in_repo_yet(tmp_path):
    repo = make_repo(tmp_path / "r")
    other = clone(repo, tmp_path / "other")
    base = g(repo, "rev-parse", "HEAD")
    commit(other, {"x.txt": "1"}, "new work")
    full = bundle(other, tmp_path / "full.bundle", "main")
    incremental = bundle(other, tmp_path / "inc.bundle", "main", f"^{base}")
    assert "can't tell without pulling (the bundle's commit isn't in this repo yet)" in repostatus.status(repo, full)
    assert "bundle is ahead (pulling would likely fast-forward" in repostatus.status(repo, incremental)
    # A bundle that builds on commits this repo doesn't have at all doesn't verify.
    stranger = make_repo(tmp_path / "stranger", {"s.txt": "s"})
    s0 = g(stranger, "rev-parse", "HEAD")
    commit(stranger, {"s.txt": "t"}, "more")
    needs = bundle(stranger, tmp_path / "needs.bundle", "main", f"^{s0}")
    assert "it builds on commits this folder doesn't have" in repostatus.status(repo, needs)


def test_incremental_bundle_on_a_split_is_not_called_a_fast_forward(tmp_path):
    repo = make_repo(tmp_path / "r")
    other = clone(repo, tmp_path / "other")
    base = g(repo, "rev-parse", "HEAD")
    commit(other, {"x.txt": "1"}, "theirs")
    inc = bundle(other, tmp_path / "inc.bundle", "main", f"^{base}")
    commit(repo, {"y.txt": "1"}, "ours")
    assert "can't tell without pulling" in repostatus.status(repo, inc)


def test_status_with_bundle_has_short_output(tmp_path):
    repo = make_repo(tmp_path / "r")
    for i in range(30):
        (repo / f"u{i}.txt").write_text("x")
    b = bundle(repo, tmp_path / "b.bundle", "main")
    assert len(repostatus.status(repo, b).splitlines()) < 40


# --------------------------------------------------------------------------- status() writes nothing
def test_status_writes_nothing(tmp_path):
    repo = make_repo(tmp_path / "r", {"a.txt": "a\n", "b.txt": "b\n"})
    other = clone(repo, tmp_path / "other")
    commit(other, {"c.txt": "c"}, "theirs")
    inc = bundle(other, tmp_path / "inc.bundle", "main", f"^{g(repo, 'rev-parse', 'HEAD')}")
    (repo / "a.txt").write_text("changed\n")
    (repo / "new.txt").write_text("untracked\n")
    old = (repo / "b.txt").stat().st_mtime_ns
    os.utime(repo / "b.txt", ns=(old + 5_000_000_000, old + 5_000_000_000))   # same content, new time: a refresh would write
    g(repo, "stash", "-q")
    (repo / "a.txt").write_text("changed again\n")
    before = git_dir_fingerprint(repo)
    before_files = snapshot(repo)["files"]
    for b in (None, inc, bundle(repo, tmp_path / "same.bundle", "main"), tmp_path / "missing.bundle"):
        repostatus.status(repo, b)
    assert git_dir_fingerprint(repo) == before
    assert snapshot(repo)["files"] == before_files


# --------------------------------------------------------------------------- pull_bundle
def test_pull_fast_forwards_and_reports(tmp_path):
    repo = make_repo(tmp_path / "r", {"a.txt": "a\n"})
    other = clone(repo, tmp_path / "other")
    old = g(repo, "rev-parse", "HEAD")
    commit(other, {"a.txt": "a2\n", "b.txt": "b\n"}, "two")
    commit(other, {"dir/c.txt": "c\n"}, "three")
    new = g(other, "rev-parse", "HEAD")
    b = bundle(other, tmp_path / "work.bundle", "main", f"^{old}")
    refs_before = g(repo, "for-each-ref", "--format=%(refname)")
    (repo / "notes.txt").write_text("untracked work stays\n")
    out = repostatus.pull_bundle(repo, b)
    assert out == f"Pulled the bundle into main: {short(old)} -> {short(new)}, 2 commits brought in, 3 files changed."
    assert g(repo, "rev-parse", "HEAD") == new
    assert (repo / "dir" / "c.txt").read_text() == "c\n"
    assert (repo / "notes.txt").read_text() == "untracked work stays\n"
    assert g(repo, "for-each-ref", "--format=%(refname)") == refs_before     # no new refs, no remote-tracking refs
    assert g(repo, "tag") == ""
    after = repostatus.status(repo, b)
    assert f"  main ({short(new)}): same" in after
    assert after.endswith("same commits, but 1 uncommitted change in the folder.")            # notes.txt
    assert "Already up to date" in repostatus.pull_bundle(repo, b)


def test_pull_named_branch_and_full_bundle(tmp_path):
    repo = make_repo(tmp_path / "r")
    other = clone(repo, tmp_path / "other")
    commit(other, {"x.txt": "1"}, "x")
    b = bundle(other, tmp_path / "full.bundle", "main")
    assert "1 commit brought in, 1 file changed" in repostatus.pull_bundle(repo, b, "main")
    assert "Already up to date" in repostatus.pull_bundle(repo, b, "refs/heads/main")


def test_pull_when_local_is_ahead_is_up_to_date(tmp_path):
    repo = make_repo(tmp_path / "r")
    b = bundle(repo, tmp_path / "old.bundle", "main")
    commit(repo, {"a.txt": "1"}, "two")
    before = snapshot(repo)
    out = repostatus.pull_bundle(repo, b)
    assert out.startswith("Already up to date") and "1 commit ahead of the bundle" in out
    assert snapshot(repo) == before


def _refusal(repo: Path, bundle_path: Path, branch: str = "") -> str:
    before = snapshot(repo)
    out = repostatus.pull_bundle(repo, bundle_path, branch)
    assert snapshot(repo) == before, out
    return out


def _ahead_bundle(tmp_path, repo: Path) -> Path:
    other = clone(repo, tmp_path / "other")
    commit(other, {"readme.txt": "from the bundle\n"}, "bundle work")
    return bundle(other, tmp_path / "ahead.bundle", "main", f"^{g(repo, 'rev-parse', 'HEAD')}")


def test_refuses_with_uncommitted_changes(tmp_path):
    repo = make_repo(tmp_path / "r")
    b = _ahead_bundle(tmp_path, repo)
    (repo / "readme.txt").write_text("my unsaved work\n")
    assert "uncommitted changes to tracked files" in _refusal(repo, b)
    g(repo, "add", "readme.txt")
    assert "uncommitted changes to tracked files (0 changed, 1 staged" in _refusal(repo, b)


def test_refuses_during_a_merge(tmp_path):
    repo = make_repo(tmp_path / "r", {"a.txt": "base\n"})
    b = _ahead_bundle(tmp_path, repo)
    g(repo, "checkout", "-q", "-b", "other")
    commit(repo, {"a.txt": "other\n"}, "other side")
    g(repo, "checkout", "-q", "main")
    commit(repo, {"a.txt": "main\n"}, "main side")
    g(repo, "merge", "other", check=False)
    assert "a merge is in progress" in _refusal(repo, b)


def test_refuses_a_bad_bundle(tmp_path):
    repo = make_repo(tmp_path / "r")
    bad = tmp_path / "bad.bundle"
    bad.write_bytes(b"# v2 git bundle\nnonsense\n\nPACKjunk")
    assert "the bundle can't be used" in _refusal(repo, bad)
    assert "the bundle can't be used" in _refusal(repo, tmp_path / "missing.bundle")


def test_refuses_branch_not_in_bundle_and_other_branch(tmp_path):
    repo = make_repo(tmp_path / "r")
    b = _ahead_bundle(tmp_path, repo)
    assert "the bundle has no branch feature (its branches: main)" in _refusal(repo, b, "feature")
    g(repo, "checkout", "-q", "-b", "feature")
    assert "the bundle has no branch feature" in _refusal(repo, b)          # default: the current branch
    assert "this folder is on feature, not main" in _refusal(repo, b, "main")
    g(repo, "checkout", "-q", "--detach")
    assert "isn't on a branch (detached)" in _refusal(repo, b)


def test_refuses_a_split_when_commits_are_known(tmp_path):
    repo = make_repo(tmp_path / "r")
    commit(repo, {"a.txt": "bundle side"}, "bundle side")
    b = bundle(repo, tmp_path / "split.bundle", "main")
    g(repo, "reset", "-q", "--hard", "HEAD~1")
    commit(repo, {"b.txt": "local side"}, "local side")
    assert "would not be a fast-forward" in _refusal(repo, b)


def test_refuses_a_split_found_after_reading_the_bundle(tmp_path):
    repo = make_repo(tmp_path / "r")
    other = clone(repo, tmp_path / "other")
    commit(other, {"x.txt": "theirs"}, "theirs")
    b = bundle(other, tmp_path / "full.bundle", "main")
    commit(repo, {"y.txt": "ours"}, "ours")
    out = _refusal(repo, b)
    assert "would not be a fast-forward" in out


@pytest.mark.parametrize("name", ["-x", "--upload-pack=touch pwned", "main --force", "a b", "a..b", "a\nb", "a\x01b", "a\tb",
                                  "x:y", "a~1", "HEAD^", "@{-1}", "/abs", "end/", "x.lock"])
def test_refuses_injection_branch_names(tmp_path, name):
    repo = make_repo(tmp_path / "r")
    b = _ahead_bundle(tmp_path, repo)
    out = _refusal(repo, b, name)
    assert out.startswith("Joe won't use that branch name")
    assert not (repo / "pwned").exists()


# --------------------------------------------------------------------------- nothing in the repo runs a program
def _marker_script(path: Path, marker: Path, tail: str = "") -> str:
    path.write_text(f"#!/bin/sh\necho ran > '{marker.as_posix()}'\n{tail}", newline="\n")
    path.chmod(0o755)
    return path.as_posix()


def test_hooks_fsmonitor_and_filters_never_run(tmp_path):
    repo = make_repo(tmp_path / "r")
    other = clone(repo, tmp_path / "other")
    commit(other, {".gitattributes": "*.txt filter=evil\n", "new.txt": "brought in\n"}, "with attributes")
    b = bundle(other, tmp_path / "ahead.bundle", "main", f"^{g(repo, 'rev-parse', 'HEAD')}")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    marks = {n: tmp_path / f"ran-{n}" for n in ("fsmonitor", "post-merge", "reference-transaction", "post-checkout",
                                               "smudge", "clean", "pager")}
    hooks = repo / ".git" / "hooks"
    for hook in ("post-merge", "reference-transaction", "post-checkout"):
        _marker_script(hooks / hook, marks[hook])
    g(repo, "config", "core.fsmonitor", _marker_script(scripts / "fsmon.sh", marks["fsmonitor"]))
    g(repo, "config", "filter.evil.smudge", _marker_script(scripts / "smudge.sh", marks["smudge"], "cat\n"))
    g(repo, "config", "filter.evil.clean", _marker_script(scripts / "clean.sh", marks["clean"], "cat\n"))
    g(repo, "config", "core.pager", _marker_script(scripts / "pager.sh", marks["pager"], "cat\n"))
    g(repo, "config", "log.showSignature", "true")
    # Control: plain git does run the fsmonitor program and the reference-transaction hook in this repo.
    subprocess.run(["git", "-C", str(repo), "status"], env=_env(), capture_output=True)
    subprocess.run(["git", "-C", str(repo), "branch", "probe"], env=_env(), capture_output=True)
    subprocess.run(["git", "-C", str(repo), "branch", "-D", "probe"], env=_env(), capture_output=True)
    if not sys.platform.startswith("win"):
        assert marks["fsmonitor"].exists() and marks["reference-transaction"].exists()
    for m in marks.values():
        m.unlink(missing_ok=True)

    (repo / "readme.txt").touch()
    assert "Branch: main" in repostatus.status(repo, b)
    out = repostatus.pull_bundle(repo, b)
    assert out.startswith("Pulled the bundle into main"), out
    assert (repo / "new.txt").read_text() == "brought in\n"
    repostatus.status(repo, b)
    ran = [n for n, m in marks.items() if m.exists()]
    assert ran == []


def test_a_global_hooks_setting_does_not_bring_hooks_back(tmp_path, monkeypatch):
    """Even a hooks folder named in the global settings stays unused: the command line wins."""
    repo = make_repo(tmp_path / "r")
    b = _ahead_bundle(tmp_path, repo)
    hooks = tmp_path / "global-hooks"
    hooks.mkdir()
    mark = tmp_path / "ran-global-hook"
    _marker_script(hooks / "post-merge", mark)
    cfg = tmp_path / "global.gitconfig"
    cfg.write_text(f"[core]\n\thooksPath = {hooks.as_posix()}\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    assert repostatus.pull_bundle(repo, b).startswith("Pulled the bundle")
    assert not mark.exists()


def test_environment_cannot_redirect_git(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "r")
    elsewhere = make_repo(tmp_path / "elsewhere", {"secret.txt": "s"})
    monkeypatch.setenv("GIT_DIR", str(elsewhere / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(elsewhere))
    out = repostatus.status(repo)
    assert "clean" in out and str(repo) in out and "secret" not in out
