"""The whole computer at a glance, for an AI app connected to Joe (read-only).

The person's words: "more than just gpu, the entire picture of the computer's stats" and "at least
allow you to read the task manager's processes". A cloud AI chat reads this instead of asking the
person for screenshots of Task Manager.

report() gives a short plain-text report: processor, memory, graphics card, disk space, which of
Joe's engines are running (and the writing models loaded right now), and the running programs as
Task Manager shows them. Each part is looked up on its own; a part the system can't give says
"not known on this computer" and never stops the others. Joe's own queue is in joe_status.

Where the numbers come from (standard library only, nothing installed):
  Windows   tasklist /FO CSV /NH (names), one PowerShell call to the process counters
            (Win32_PerfFormattedData_PerfProc_Process: processor share and private memory, as
            Task Manager shows them), GlobalMemoryStatusEx, the drive letters
  Mac       ps -axo pid=,pcpu=,rss=,comm=, sysctl and vm_stat, df -kP
  Linux     /proc/<pid>/stat (sampled twice, so the processor share is "right now"), /proc/meminfo,
            /proc/mounts; ps as a fallback
  Windows   a second PowerShell call (run alongside) to the graphics card's own counters: load and
            memory for every program, browsers and games included, as Task Manager's GPU column
  Linux     nvidia-smi pmon -c 1 for graphics card load per program (NVIDIA only)
  all       nvidia-smi for graphics memory per program, where it's there

Privacy for programs: names and numbers ONLY. No window titles, no command lines or arguments, no
file paths, no user names, no environment. Nothing here ever ends, pauses, re-prioritises or
changes a program: it only reads.
"""
from __future__ import annotations

import csv
import io
import os
import platform
import re
import shutil
import subprocess
import threading
import time

from . import hardware, system

DEFAULT_ROWS = 25
MAX_ROWS = 100
RUN_TIMEOUT_S = 6              # one quick system command
PS_TIMEOUT_S = 20              # PowerShell can be slow to start on a busy PC
PART_TIMEOUT_S = 40            # the longest any one part may take before it's "not known"
SAMPLE_S = 0.5                 # gap between two readings for "busy right now"
NOT_KNOWN = "not known on this computer"
FOOTER = "Joe's own queue and what he is working on: joe_status."

_PS_PERF = ("Get-CimInstance Win32_PerfFormattedData_PerfProc_Process | "
            "Select-Object Name,IDProcess,PercentProcessorTime,WorkingSetPrivate | "
            "ConvertTo-Csv -NoTypeInformation")
_NVIDIA_APPS = ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"]
_NVIDIA_PMON = ["nvidia-smi", "pmon", "-c", "1", "-s", "u"]
# The graphics card's counters on Windows 10 1709 and newer (any card maker). Both lists come back
# from one PowerShell start, as two CSV blocks with a marker line between them. A missing class only
# writes an error (SilentlyContinue keeps it quiet), so the block is just empty.
GPU_MARK = "#JOE-GPU-MEMORY#"
_PS_GPU = ("$ErrorActionPreference = 'SilentlyContinue'; "
           "Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine | "
           "Select-Object Name,UtilizationPercentage | ConvertTo-Csv -NoTypeInformation; "
           f"'{GPU_MARK}'; "
           "Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory | "
           "Select-Object Name,DedicatedUsage,SharedUsage | ConvertTo-Csv -NoTypeInformation")

# Linux file systems that are real places to keep files (the rest are the system's own: proc, tmpfs, ...)
REAL_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "vfat", "exfat", "ntfs", "ntfs3",
           "fuseblk", "hfsplus", "apfs", "jfs", "reiserfs", "bcachefs", "nfs", "nfs4", "cifs", "smb3"}
_SKIP_MOUNTS = ("/boot", "/efi", "/snap/", "/System/Volumes/", "/private/var/vm",
                "/Library/Developer/CoreSimulator")


# --------------------------------------------------------------------------- small helpers
def _os() -> str:
    """'windows', 'mac' or 'linux' (tests change this to try the other systems' paths)."""
    return system.name()


def _cores() -> int:
    return os.cpu_count() or 1


def _decode(b: bytes) -> str:
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        enc = "oem" if system.WINDOWS else "latin-1"          # Windows commands answer in the console's code page
        try:
            return b.decode(enc, errors="replace")
        except LookupError:
            return b.decode("latin-1", errors="replace")


def _run(argv: list[str], timeout: float = RUN_TIMEOUT_S) -> str | None:
    """Output of one system command, or None when it's missing, fails or takes too long."""
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout, creationflags=system.no_window_flags())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    out = _decode(p.stdout or b"")
    if p.returncode != 0 and not out.strip():
        return None
    return out


def _read_file(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _digits(s: str) -> int | None:
    """'1.234 K', '1,234 K', '1 234 Ko' (any language's thousands mark) -> 1234."""
    d = re.sub(r"\D", "", s or "")
    return int(d) if d else None


def _float(s: str) -> float | None:
    try:
        return float(str(s).strip().replace(",", "."))
    except ValueError:
        return None


def clean_name(name: str) -> str:
    """A program's name only: the last part of a path, no control characters, not too long. If
    anything that looks like an argument ever comes along (' --key', ' -x', ' /path', ' C:\\'),
    it and all after it are cut off first, so a command line can't slip through."""
    n = re.split(r"\s+(?:-{1,2}\w|[/\\]|[A-Za-z]:\\)", (name or "").strip())[0]
    n = re.split(r"[\\/]", n)[-1]
    n = re.sub(r"[\x00-\x1f\x7f]", "", n).strip()
    return n[:60]


def size(n_bytes: float | None) -> str:
    """'8.1 GB', '812 MB', '-' when not known."""
    if n_bytes is None:
        return "-"
    if n_bytes >= 2**30:
        return f"{n_bytes / 2**30:.1f} GB"
    return f"{max(n_bytes, 0) / 2**20:.0f} MB"


def _gb(n_bytes: float) -> str:
    g = n_bytes / 2**30
    return f"{g:,.0f}" if g >= 10 else f"{g:.1f}"


def _pct(v: float | None) -> str:
    if v is None:
        return "-"
    return f"{v:.0f}%" if v >= 10 or v == 0 else f"{v:.1f}%"


# --------------------------------------------------------------------------- parsers (pure: raw text in)
def parse_tasklist(text: str | None) -> list[dict]:
    """tasklist /FO CSV /NH -> [{pid, name, mem}]. Only the name, id and memory columns are kept
    (if a /V listing ever comes in, its user and window-title columns are dropped here)."""
    rows = []
    for cells in csv.reader(io.StringIO(text or "")):
        if len(cells) < 5 or not cells[1].strip().isdigit():
            continue
        kb = _digits(cells[4])
        rows.append({"pid": int(cells[1]), "name": clean_name(cells[0]),
                     "mem": kb * 1024 if kb is not None else None})
    return rows


def parse_win_perf(text: str | None) -> list[dict]:
    """PowerShell's CSV of Win32_PerfFormattedData_PerfProc_Process -> [{pid, name, cpu_raw, mem}].
    'chrome#12' becomes 'chrome'; '_Total' and 'Idle' are left out (they aren't programs)."""
    rows = []
    reader = csv.DictReader(io.StringIO((text or "").lstrip("﻿")))
    for r in reader:
        name = re.sub(r"#\d+$", "", (r.get("Name") or "").strip())
        pid = _digits(r.get("IDProcess") or "")
        if not name or name in ("_Total", "Idle") or pid in (None, 0):
            continue
        rows.append({"pid": pid, "name": clean_name(name), "cpu_raw": _float(r.get("PercentProcessorTime") or ""),
                     "mem": _digits(r.get("WorkingSetPrivate") or "")})
    return rows


def parse_ps(text: str | None) -> list[dict]:
    """ps -axo pid=,pcpu=,rss=,comm= -> [{pid, name, cpu, mem}]. cpu is ps's own (a share of one
    core); comm can be a whole path on a Mac, so only its last part is kept."""
    rows = []
    for line in (text or "").splitlines():
        m = re.match(r"^\s*(\d+)\s+([\d.,]+)\s+(\d+)\s+(.+?)\s*$", line)
        if not m:
            continue
        rows.append({"pid": int(m.group(1)), "cpu": _float(m.group(2)), "mem": int(m.group(3)) * 1024,
                     "name": clean_name(m.group(4))})
    return rows


def parse_proc_stat(text: str | None) -> dict | None:
    """One /proc/<pid>/stat line -> {pid, name, ticks, rss_pages}. The name sits in brackets and
    may hold spaces or brackets itself, so the last ')' ends it."""
    if not text:
        return None
    a, b = text.find("("), text.rfind(")")
    if a < 0 or b < a:
        return None
    try:
        rest = text[b + 1:].split()
        return {"pid": int(text[:a].strip()), "name": clean_name(text[a + 1:b]),
                "ticks": int(rest[11]) + int(rest[12]), "rss_pages": int(rest[21])}
    except (ValueError, IndexError):
        return None


def parse_nvidia_apps(text: str | None) -> dict[int, int]:
    """nvidia-smi --query-compute-apps=pid,used_memory (no units: MiB) -> {pid: bytes}. Only the
    process id and the number are read; '[N/A]' (common on Windows) is left out."""
    out: dict[int, int] = {}
    for line in (text or "").splitlines():
        cells = [c.strip() for c in line.split(",")]
        if len(cells) < 2 or not cells[0].isdigit():
            continue
        mib = _float(cells[-1])
        if mib is not None:
            out[int(cells[0])] = out.get(int(cells[0]), 0) + int(mib * 2**20)
    return out


def _num_text(s: str) -> float | None:
    """'12', '1,5' (comma decimal), '1\u202f234' (thin-space thousands) -> a number, or None."""
    t = re.sub(r"[\s\u00a0\u202f']", "", str(s or "")).replace(",", ".")
    if t.count(".") > 1:
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def _gpu_pid(instance: str) -> int | None:
    m = re.match(r"^pid_(\d+)_", (instance or "").strip())
    return int(m.group(1)) if m else None


def _csv_rows(text: str | None) -> list[dict]:
    try:
        return list(csv.DictReader(io.StringIO((text or "").lstrip("\ufeff").strip() + "\n")))
    except csv.Error:
        return []


def split_win_gpu(text: str | None) -> tuple[str, str]:
    """The combined PowerShell answer -> (engine CSV, memory CSV)."""
    a, _, b = (text or "").partition(GPU_MARK)
    return a, b


def parse_win_gpu_engine(text: str | None) -> dict[int, float]:
    """Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine CSV -> {pid: load percent}.

    Instance names look like pid_1234_luid_0x00000000_0x0000C3A1_phys_0_eng_0_engtype_3D. Per
    process, the engines of one kind on one card (3D, Copy, VideoDecode, ...) are added up, and the
    busiest kind is the answer, capped at 100. That is what Task Manager's GPU column shows (the
    busiest engine, not the sum over all kinds), so the numbers can be compared with it directly;
    adding 3D + Copy + VideoDecode would overstate a program that uses several at once."""
    by: dict[int, dict[str, float]] = {}
    for r in _csv_rows(text):
        name = r.get("Name") or ""
        pid = _gpu_pid(name)
        val = _num_text(r.get("UtilizationPercentage") or "")
        if pid is None or pid == 0 or val is None:
            continue
        m = re.search(r"_luid_(\w+?)_phys_(\d+)_eng_\d+_engtype_(.*)$", name)
        kind = f"{m.group(1)}|{m.group(2)}|{m.group(3).strip().lower()}" if m else "?"
        kinds = by.setdefault(pid, {})
        kinds[kind] = kinds.get(kind, 0.0) + max(val, 0.0)
    return {pid: min(100.0, max(kinds.values())) for pid, kinds in by.items() if kinds}


def parse_win_gpu_memory(text: str | None) -> dict[int, int]:
    """Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory CSV -> {pid: bytes} of the
    card's own (dedicated) memory, added over cards. Shared memory is main memory, so it's left out."""
    out: dict[int, int] = {}
    for r in _csv_rows(text):
        pid = _gpu_pid(r.get("Name") or "")
        val = _num_text(r.get("DedicatedUsage") or "")
        if pid is None or pid == 0 or val is None:
            continue
        out[pid] = out.get(pid, 0) + int(val)
    return out


def parse_nvidia_pmon(text: str | None) -> dict[int, float]:
    """nvidia-smi pmon -c 1 -> {pid: load percent (the sm column)}. Columns are found from the
    header line, because newer drivers add some; the command-name column is never read. '-' (idle)
    is left out; a process on two cards is added up, capped at 100."""
    out: dict[int, float] = {}
    cols: list[str] = []
    for line in (text or "").splitlines():
        cells = line.split()
        if not cells:
            continue
        if cells[0] == "#":
            if not cols and "pid" in cells and "sm" in cells:
                cols = cells[1:]
            continue
        if not cols or len(cells) < len(cols) - 1:
            continue
        try:
            pid = int(cells[cols.index("pid")])
        except (ValueError, IndexError):
            continue
        val = _num_text(cells[cols.index("sm")])
        if val is not None:
            out[pid] = min(100.0, out.get(pid, 0.0) + val)
    return out


def parse_meminfo(text: str | None) -> tuple[int, int] | None:
    """/proc/meminfo -> (total, available) in bytes."""
    vals = {}
    for line in (text or "").splitlines():
        m = re.match(r"^(\w+):\s+(\d+)", line)
        if m:
            vals[m.group(1)] = int(m.group(2)) * 1024
    if "MemTotal" not in vals:
        return None
    avail = vals.get("MemAvailable", vals.get("MemFree", 0) + vals.get("Cached", 0) + vals.get("Buffers", 0))
    return vals["MemTotal"], avail


def parse_vm_stat(text: str | None, total: int) -> tuple[int, int] | None:
    """Mac vm_stat -> (total, free) in bytes. Used is worked out as Activity Monitor does:
    app memory (anonymous - purgeable) + wired + compressed."""
    if not text or total <= 0:
        return None
    m = re.search(r"page size of (\d+) bytes", text)
    page = int(m.group(1)) if m else 4096
    pages = {k.strip().lower(): int(v) for k, v in re.findall(r"^\s*\"?([^:\"]+)\"?:\s+(\d+)\.?\s*$", text, re.M)}
    wired = pages.get("pages wired down", 0)
    comp = pages.get("pages occupied by compressor", 0)
    if "anonymous pages" in pages:
        used_pages = pages["anonymous pages"] - pages.get("pages purgeable", 0) + wired + comp
    elif "pages active" in pages:
        used_pages = pages["pages active"] + wired + comp
    else:
        return None
    used = max(0, min(total, used_pages * page))
    return total, total - used


def parse_cpuinfo(text: str | None) -> str:
    """The processor's name from /proc/cpuinfo ('' when it doesn't say)."""
    for key in ("model name", "Model", "Hardware", "cpu model"):
        m = re.search(rf"^{key}\s*:\s*(.+)$", text or "", re.M)
        if m and m.group(1).strip():
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


def _unescape_mount(s: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)


def parse_mounts(text: str | None) -> list[dict]:
    """/proc/mounts -> real, writable volumes [{device, mount}] (no proc, tmpfs, snaps, /boot)."""
    out, seen = [], set()
    for line in (text or "").splitlines():
        p = line.split()
        if len(p) < 4:
            continue
        dev, mount, fs, opts = p[0], _unescape_mount(p[1]), p[2], p[3].split(",")
        if fs not in REAL_FS or "ro" in opts or _skip_mount(mount) or dev in seen:
            continue
        seen.add(dev)
        out.append({"device": dev, "mount": mount})
    return out


def parse_df(text: str | None) -> list[dict]:
    """df -kP (Mac) -> [{device, mount, total, free}] for real disks (/dev/...)."""
    out = []
    for line in (text or "").splitlines():
        m = re.match(r"^(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+\d+%\s+(.+?)\s*$", line)
        if not m or not m.group(1).startswith("/dev/") or _skip_mount(m.group(5)):
            continue
        out.append({"device": m.group(1), "mount": m.group(5),
                    "total": int(m.group(2)) * 1024, "free": int(m.group(4)) * 1024})
    return out


def _skip_mount(mount: str) -> bool:
    return any(mount == s.rstrip("/") or mount.startswith(s if s.endswith("/") else s + "/") for s in _SKIP_MOUNTS)


def plain_mount(mount: str) -> str:
    """A volume's place without anybody's user name: /home/joe/x -> ~/x, /media/joe/USB -> /media/USB."""
    m = re.match(r"^/(?:run/)?media/[^/]+/(.+)$", mount)
    if m:
        return "/media/" + m.group(1)
    m = re.match(r"^/(?:home|Users)/[^/]+(/.*)?$", mount)
    if m:
        return "~" + (m.group(1) or "")
    return mount


# --------------------------------------------------------------------------- processes
def _linux_snapshot() -> dict[int, dict]:
    """Every process's /proc/<pid>/stat (name and numbers only; never cmdline or environ)."""
    snap = {}
    try:
        pids = [d for d in os.listdir("/proc") if d.isdigit()]
    except OSError:
        return snap
    for d in pids:
        st = parse_proc_stat(_read_file(f"/proc/{d}/stat"))
        if st:
            snap[st["pid"]] = st
    return snap


def _linux_processes() -> list[dict] | None:
    a = _linux_snapshot()
    if not a:
        return None
    t0 = time.monotonic()
    time.sleep(SAMPLE_S)
    b = _linux_snapshot()
    gap = max(time.monotonic() - t0, 0.001)
    try:
        hz, page = os.sysconf("SC_CLK_TCK"), os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        hz, page = 100, 4096
    return linux_rows(a, b, gap, hz, page, _cores())


def linux_rows(a: dict, b: dict, gap_s: float, hz: int, page: int, cores: int) -> list[dict]:
    """Two /proc snapshots -> rows with the processor share over the gap (of the whole computer,
    as Task Manager shows it). Kernel threads (no memory of their own) are left out."""
    rows = []
    for pid, st in b.items():
        if st["rss_pages"] <= 0:
            continue
        before = a.get(pid)
        cpu = None
        if before and before["name"] == st["name"]:
            cpu = max(0.0, 100 * (st["ticks"] - before["ticks"]) / hz / gap_s / max(cores, 1))
        rows.append({"pid": pid, "name": st["name"], "cpu": cpu if cpu is not None else 0.0, "mem": st["rss_pages"] * page})
    return rows


def _ps_processes() -> list[dict] | None:
    rows = parse_ps(_run(["ps", "-axo", "pid=,pcpu=,rss=,comm="]))
    if not rows:
        return None
    n = _cores()
    for r in rows:
        r["cpu"] = r["cpu"] / n if r["cpu"] is not None else None
    return [r for r in rows if r["mem"] > 0 or (r["cpu"] or 0) > 0]


def windows_rows(perf: list[dict], tasks: list[dict], cores: int) -> list[dict]:
    """Join the process counters (processor, private memory) with tasklist (names with .exe) by
    process id. Without counters: tasklist alone, processor share not known."""
    names = {t["pid"]: t["name"] for t in tasks}
    if perf:
        cpu_known = sum(p["cpu_raw"] or 0 for p in perf) > 0     # a first reading can come back all zero
        return [{"pid": p["pid"], "name": names.get(p["pid"], p["name"]),
                 "cpu": (p["cpu_raw"] or 0) / max(cores, 1) if cpu_known else None,
                 "mem": p["mem"] or 0} for p in perf]
    return [{"pid": t["pid"], "name": t["name"], "cpu": None, "mem": t["mem"] or 0} for t in tasks if t["pid"] != 0]


def _windows_processes() -> list[dict] | None:
    tasks = parse_tasklist(_run(["tasklist", "/FO", "CSV", "/NH"], timeout=15))
    perf = parse_win_perf(_run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_PERF], timeout=PS_TIMEOUT_S))
    rows = windows_rows(perf, tasks, _cores())
    return rows or None


def gpu_memory_by_pid() -> dict[int, int] | None:
    """Graphics memory per process id from nvidia-smi, or None when it isn't there."""
    text = _run(_NVIDIA_APPS)
    return None if text is None else parse_nvidia_apps(text)


def windows_gpu_by_pid() -> tuple[dict[int, float] | None, dict[int, int] | None]:
    """(load percent, card memory bytes) per process id from Windows' graphics card counters.
    None for a list that didn't come back (old Windows, no PowerShell, too slow)."""
    text = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_GPU], timeout=PS_TIMEOUT_S)
    if text is None:
        return None, None
    eng, mem = split_win_gpu(text)
    load, used = parse_win_gpu_engine(eng), parse_win_gpu_memory(mem)
    return (load or None), (used or None)


def gpu_load_by_pid() -> dict[int, float] | None:
    """Graphics card load per process id from nvidia-smi pmon (Linux), or None."""
    text = _run(_NVIDIA_PMON, timeout=RUN_TIMEOUT_S)
    if text is None:
        return None
    out = parse_nvidia_pmon(text)
    return out if out or "pid" in text else None       # a header with no rows: known, nothing busy


def _graphics_per_program() -> tuple[dict | None, dict | None]:
    """(load by pid, memory by pid) from whatever this system gives; each None when not known.
    Windows: its own counters first, nvidia-smi memory when those are missing. Linux: nvidia-smi.
    Mac: nothing (the system has no per-program graphics numbers without extra software)."""
    o = _os()
    load = mem = None
    if o == "windows":
        try:
            load, mem = windows_gpu_by_pid()
        except Exception:                             # noqa: BLE001
            load, mem = None, None
    elif o == "linux":
        try:
            load = gpu_load_by_pid()
        except Exception:                             # noqa: BLE001
            load = None
    if mem is None:
        try:
            mem = gpu_memory_by_pid()
        except Exception:                             # noqa: BLE001
            mem = None
    return load, mem


def running_processes() -> dict | None:
    """{'rows': [{pid, name, cpu, mem, gpu, gpu_pct}], 'gpu_known': bool, 'gpu_load_known': bool},
    or None when not known. gpu = graphics card memory, gpu_pct = graphics card load. The graphics
    numbers are asked for at the same time as the program list, so the report isn't slower."""
    box: dict = {}

    def graphics():
        try:
            box["v"] = _graphics_per_program()
        except Exception:                             # noqa: BLE001 (the rest still counts)
            pass
    t = threading.Thread(target=graphics, daemon=True)
    t.start()
    o = _os()
    if o == "windows":
        rows = _windows_processes()
    elif o == "linux" and os.path.isdir("/proc"):
        rows = _linux_processes() or _ps_processes()
    else:
        rows = _ps_processes()
    t.join(PS_TIMEOUT_S + 2)
    if not rows:
        return None
    load, mem = box.get("v", (None, None))
    for r in rows:                                    # a process that ended in between is simply not matched
        r["gpu"] = mem.get(r["pid"]) if mem else None
        r["gpu_pct"] = load.get(r["pid"], 0.0) if load is not None else None
    return {"rows": rows, "gpu_known": mem is not None, "gpu_load_known": load is not None}


def group(rows: list[dict]) -> list[dict]:
    """Same name (any case) added together: {name, count, cpu, mem, gpu, gpu_pct}, largest memory
    first, then processor share. Graphics card load is added up too, capped at 100."""
    groups: dict[str, dict] = {}
    for r in rows:
        name = r.get("name") or "?"
        g = groups.setdefault(name.lower(), {"name": name, "count": 0, "cpu": None, "mem": 0, "gpu": None,
                                                     "gpu_pct": None})
        g["count"] += 1
        g["mem"] += r.get("mem") or 0
        if r.get("cpu") is not None:
            g["cpu"] = (g["cpu"] or 0) + r["cpu"]
        if r.get("gpu") is not None:
            g["gpu"] = (g["gpu"] or 0) + r["gpu"]
        if r.get("gpu_pct") is not None:
            g["gpu_pct"] = min(100.0, (g["gpu_pct"] or 0) + r["gpu_pct"])
    return sorted(groups.values(), key=lambda g: (-g["mem"], -(g["cpu"] or 0), g["name"].lower()))


def clamp_rows(n) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return DEFAULT_ROWS
    return max(1, min(MAX_ROWS, n))


def process_lines(info: dict | None, rows: int = DEFAULT_ROWS) -> list[str]:
    if not info or not info.get("rows"):
        return [f"Processes: {NOT_KNOWN}"]
    groups = group(info["rows"])
    top = groups[:clamp_rows(rows)]
    show_gpu, show_load = info.get("gpu_known"), info.get("gpu_load_known")
    note = ("" if show_gpu and show_load else
            "; graphics card use per program not reported here" if not show_gpu and not show_load else
            "; graphics card load per program not reported here" if show_gpu else
            "; graphics card memory per program not reported here")
    cpu_note = "" if any(g["cpu"] is not None for g in groups) else "; processor share not known"
    out = []
    busy = busiest_on_graphics(groups)
    if busy:
        out.append("Using the graphics card now: " + busy)
    out.append(f"Processes (top {len(top)} of {len(groups)} by memory, then processor; "
               f"{len(info['rows'])} running; names and numbers only{note}{cpu_note}):")
    out.append("  memory    processor" + ("  graphics mem" if show_gpu else "") + ("  graphics %" if show_load else "") + "  name")
    for g in top:
        line = f"  {size(g['mem']):>8}  {_pct(g['cpu']):>9}"
        if show_gpu:
            line += f"  {size(g['gpu']):>12}"
        if show_load:
            line += f"  {_pct(g['gpu_pct']):>10}"
        out.append(f"{line}  {_label(g)}")
    return out


def _label(g: dict) -> str:
    return g["name"] + (f" x{g['count']}" if g["count"] > 1 else "")


def busiest_on_graphics(groups: list[dict], top: int = 3, above: float = 1.0) -> str:
    """'chrome.exe x18 21%, ollama.exe 3%': up to three programs using the graphics card most right
    now (more than 1%), or '' when none is."""
    busy = sorted((g for g in groups if (g.get("gpu_pct") or 0) > above), key=lambda g: -g["gpu_pct"])[:top]
    return ", ".join(f"{_label(g)} {_pct(g['gpu_pct'])}" for g in busy)


# --------------------------------------------------------------------------- processor, memory, graphics, disks
def _cpu_name() -> str:
    o = _os()
    if o == "windows":
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return re.sub(r"\s+", " ", str(winreg.QueryValueEx(k, "ProcessorNameString")[0])).strip()
        except (ImportError, OSError):
            return ""
    if o == "mac":
        return (_run(["sysctl", "-n", "machdep.cpu.brand_string"]) or "").strip()
    return parse_cpuinfo(_read_file("/proc/cpuinfo"))


def _cpu_busy() -> int | None:
    """Whole-computer processor load over a short gap, right now."""
    a = hardware._cpu_counters()
    if a:
        time.sleep(SAMPLE_S)
        b = hardware._cpu_counters()
        if b and b[1] > a[1]:
            return max(0, min(100, round(100 * (b[0] - a[0]) / (b[1] - a[1]))))
    return hardware.cpu_pct()


def processor_lines() -> list[str]:
    parts = []
    try:
        name = _cpu_name()
    except Exception:                                 # noqa: BLE001
        name = ""
    if name:
        parts.append(name)
    parts.append(f"{_cores()} cores (logical)")
    busy = _cpu_busy()
    parts.append(f"{busy}% busy" if busy is not None else "load not known")
    return ["Processor: " + ", ".join(parts)]


def _windows_memory() -> tuple[int, int] | None:
    import ctypes

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MS()
    m.dwLength = ctypes.sizeof(MS)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):  # type: ignore[attr-defined]
        return int(m.ullTotalPhys), int(m.ullAvailPhys)
    return None


def _memory() -> tuple[int, int] | None:
    """(total, free) in bytes."""
    o = _os()
    if o == "windows":
        return _windows_memory()
    if o == "mac":
        total = _digits(_run(["sysctl", "-n", "hw.memsize"]) or "") or 0
        return parse_vm_stat(_run(["vm_stat"]), total)
    return parse_meminfo(_read_file("/proc/meminfo"))


def memory_lines() -> list[str]:
    m = _memory()
    if not m or m[0] <= 0:
        return [f"Memory: {NOT_KNOWN}"]
    total, free = m
    return [f"Memory: {total / 2**30:.1f} GB, {(total - free) / 2**30:.1f} used, {free / 2**30:.1f} free"]


def graphics_lines() -> list[str]:
    g = hardware.gpu()
    if not g:
        return ["Graphics card: none found that reports itself"]
    parts = [g.get("name") or "graphics card"]
    total, used = g.get("vram_total_mb"), g.get("vram_used_mb")
    if g.get("unified"):
        parts.append("shares the main memory" + (f" (about {total / 1024:.1f} GB usable)" if total else ""))
    elif total:
        parts.append(f"{total / 1024:.1f} GB")
        if used is not None:
            parts.append(f"{used / 1024:.1f} used, {max(total - used, 0) / 1024:.1f} free")
    if g.get("temp_c") is not None:
        parts.append(f"{g['temp_c']} C")
    if g.get("util_pct") is not None:
        parts.append(f"{g['util_pct']}% busy")
    if g.get("power_w") is not None:
        parts.append(f"{g['power_w']:.0f} W" if isinstance(g["power_w"], float) else f"{g['power_w']} W")
    if g.get("vendor") == "nvidia-no-smi":
        parts.append("live numbers not known (nvidia-smi missing)")
    return ["Graphics card: " + ", ".join(str(p) for p in parts)]


def _usage(path: str) -> tuple[int, int] | None:
    """(total, free) for one volume, or None. A dead network drive can hang, so this gives up after a while."""
    box: dict = {}

    def go():
        try:
            u = shutil.disk_usage(path)
            box["v"] = (u.total, u.free)
        except OSError:
            pass
    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(3)
    return box.get("v")


def _windows_drives() -> list[str]:
    if hasattr(os, "listdrives"):
        try:
            return [d.rstrip("\\") for d in os.listdrives()]       # type: ignore[attr-defined]
        except OSError:
            pass
    return [f"{c}:" for c in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")]


def disks() -> list[dict]:
    """[{name, total, free}] for each real drive or volume."""
    o = _os()
    out = []
    if o == "windows":
        for d in _windows_drives():
            u = _usage(d + "\\")
            if u and u[0] > 0:
                out.append({"name": d, "total": u[0], "free": u[1]})
        return out
    if o == "mac":
        vols = parse_df(_run(["df", "-kP"]))
    else:
        vols = []
        for v in parse_mounts(_read_file("/proc/mounts")):
            u = _usage(v["mount"])
            if u and u[0] > 0:
                vols.append({**v, "total": u[0], "free": u[1]})
    seen = set()
    for v in vols:
        key = (v["total"], v["free"])                 # one Mac disk shows up as "/" and as its Data volume
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": plain_mount(v["mount"]), "total": v["total"], "free": v["free"]})
    return out


def disk_lines() -> list[str]:
    d = disks()
    if not d:
        return [f"Disks: {NOT_KNOWN}"]
    return ["Disks: " + " | ".join(f"{x['name']} {_gb(x['total'])} GB, {_gb(x['free'])} free" for x in d)]


# --------------------------------------------------------------------------- engines
def _services(settings):
    from .services import ServiceManager
    return ServiceManager(settings, log=lambda *_: None)


def model_text(m: dict) -> str:
    """'gemma4:12b, 8.1 GB, all on the graphics card'."""
    name = re.sub(r"[\x00-\x1f\x7f]", "", str(m.get("name") or m.get("model") or "?"))[:60]
    sz, vram = m.get("size") or 0, m.get("size_vram") or 0
    if sz <= 2**20:                                   # a writing program that doesn't give sizes
        return name
    share = round(100 * vram / sz)
    where = ("all on the graphics card" if share >= 99 else "all on the processor" if share <= 0
             else f"{share}% on the graphics card")
    return f"{name}, {size(sz)}, {where}"


def engine_parts(settings) -> list[str]:
    """['Ollama yes (...)', 'ComfyUI no']."""
    from .textengines import engine_label
    label = engine_label(settings.ollama)
    sm = _services(settings)
    parts = []
    try:
        up = sm.ollama_up()
    except Exception:                                 # noqa: BLE001
        up = None
    if up:
        try:
            models = sm.ollama.loaded_models()
        except Exception:                             # noqa: BLE001
            models = None
        if models:
            parts.append(f"{label} yes (" + "; ".join(model_text(m) for m in models) + ")")
        elif models is not None and label == "Ollama":
            parts.append(f"{label} yes (no model loaded)")
        else:
            parts.append(f"{label} yes")
    else:
        parts.append(f"{label} " + ("no" if up is False else NOT_KNOWN))
    try:
        parts.append("ComfyUI " + ("yes" if sm.comfy_up() else "no"))
    except Exception:                                 # noqa: BLE001
        parts.append(f"ComfyUI {NOT_KNOWN}")
    return parts


def unsloth_text(info: dict | None) -> str:
    """Unsloth Studio by program name only (no ports or files are opened for it)."""
    if not info or not info.get("rows"):
        return f"Unsloth Studio {NOT_KNOWN}"
    seen = any("unsloth" in (r.get("name") or "").lower() for r in info["rows"])
    return "Unsloth Studio " + ("running" if seen else "not seen")


# --------------------------------------------------------------------------- the report
def _os_text() -> str:
    o = _os()
    try:
        if o == "windows":
            rel = platform.release()
            try:
                if rel == "10" and int(platform.version().split(".")[-1]) >= 22000:
                    rel = "11"                        # older Pythons call Windows 11 "10"
            except ValueError:
                pass
            return f"Windows {rel}"
        if o == "mac":
            return f"macOS {platform.mac_ver()[0]}".strip()
        try:
            return platform.freedesktop_os_release().get("PRETTY_NAME") or "Linux"
        except OSError:
            return "Linux"
    except Exception:                                 # noqa: BLE001
        return system.pretty_name()


def _in_parallel(jobs: dict, timeout: float | None = None) -> dict:
    """Run each job at once on its own; {key: ('ok', value) | ('error', None)}. A job that raises
    or takes too long is an error, and the others carry on."""
    results: dict = {}

    def runner(key, fn, args):
        try:
            results[key] = ("ok", fn(*args))
        except Exception:                             # noqa: BLE001 (one part never loses the others)
            results[key] = ("error", None)
    threads = []
    for key, (fn, args) in jobs.items():
        t = threading.Thread(target=runner, args=(key, fn, args), daemon=True)
        t.start()
        threads.append(t)
    end = time.monotonic() + (PART_TIMEOUT_S if timeout is None else timeout)
    for t in threads:
        t.join(max(0.0, end - time.monotonic()))
    return {k: results.get(k, ("error", None)) for k in jobs}


def report(settings, processes: int = DEFAULT_ROWS) -> str:
    """The whole computer in a short plain-text report (read-only). processes = how many rows of
    running programs (1..100, default 25)."""
    rows = clamp_rows(processes)
    r = _in_parallel({
        "cpu": (processor_lines, ()),
        "mem": (memory_lines, ()),
        "gpu": (graphics_lines, ()),
        "disk": (disk_lines, ()),
        "eng": (engine_parts, (settings,)),
        "procs": (running_processes, ()),
    })

    def part(key, label):
        ok, v = r[key]
        return v if ok == "ok" and v else [f"{label}: {NOT_KNOWN}"]
    procs = r["procs"][1] if r["procs"][0] == "ok" else None
    eng = r["eng"][1] if r["eng"][0] == "ok" and r["eng"][1] else [f"writing program {NOT_KNOWN}", f"ComfyUI {NOT_KNOWN}"]
    lines = [f"[this computer | {_os_text()} | {time.strftime('%H:%M')}]"]
    lines += part("cpu", "Processor") + part("mem", "Memory") + part("gpu", "Graphics card") + part("disk", "Disks")
    lines.append("Running: " + " | ".join(eng + [unsloth_text(procs)]))
    try:
        lines += process_lines(procs, rows)
    except Exception:                                 # noqa: BLE001
        lines.append(f"Processes: {NOT_KNOWN}")
    lines.append(FOOTER)
    return "\n".join(lines)
