"""pcstatus: the whole computer at a glance for a connected AI app (read-only).

Nothing here reads this machine's real hardware: every system command goes through pcstatus._run,
and every file through pcstatus._read_file, and the tests put canned answers in both (real-looking
output from Windows, a Mac and Linux). The privacy tests put a command line, a path, a user name
and a window title into that output and check none of them ever reaches the report."""
from __future__ import annotations

import subprocess
import sys
import time

import pytest

from joeai import hardware, pcstatus
from joeai.config import Settings

GB = 2**30
MB = 2**20

# --------------------------------------------------------------------------- canned output
TASKLIST = '''"System Idle Process","0","Services","0","8 K"
"System","4","Services","0","2,412 K"
"chrome.exe","1200","Console","1","312,000 K"
"chrome.exe","1201","Console","1","100,000 K"
"ollama.exe","3300","Console","1","1,048,576 K"
"My App, Deluxe.exe","4400","Console","1","20,480 K"
'''
# German and French Windows: "1.234 K", "1 234 Ko" (a no-break space as the thousands mark)
TASKLIST_DE = '"chrome.exe","1200","Console","1","312.000 K"\n"explorer.exe","50","Console","1","98.765 K"\n'
TASKLIST_FR = '"chrome.exe","1200","Console","1","312\u00a0000 Ko"\n'
# a /V listing (user name and window title in its last columns) must never leak through
TASKLIST_V = ('"notepad.exe","777","Console","1","9,000 K","Running","PC\\joseph","0:00:01",'
              '"secret-plans.txt - Notepad"\n')

WIN_PERF = '''"Name","IDProcess","PercentProcessorTime","WorkingSetPrivate"
"Idle","0","1500","8192"
"System","4","0","24576"
"chrome","1200","16","200000000"
"chrome#1","1201","8","50000000"
"ollama","3300","32","900000000"
"My App, Deluxe","4400","0","10000000"
"_Total","0","1600","2000000000"
'''
WIN_PERF_ZERO = '''"Name","IDProcess","PercentProcessorTime","WorkingSetPrivate"
"chrome","1200","0","200000000"
"ollama","3300","0","900000000"
'''

PS_MAC = """    1   0.0  12345 /sbin/launchd
  400  25.5 800000 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
  401   3.0 200000 /Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Helper (Renderer)
  402   1,5 100000 /Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Helper (Renderer)
  900   0.0  50000 /Users/joseph/Secret Project/bin/thing
"""
PS_LINUX = """    1  0.0  11000 systemd
    2  0.0      0 kthreadd
  500 12.0 300000 firefox
  501  0.5  80000 Web Content
"""

NVIDIA_APPS = """3300, 7900
1200, 300
4400, [N/A]
"""

MEMINFO = """MemTotal:       32768000 kB
MemFree:         1000000 kB
MemAvailable:   12000000 kB
Buffers:          100000 kB
Cached:          5000000 kB
"""
VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               20000.
Pages active:                            300000.
Pages inactive:                          290000.
Pages speculative:                        10000.
Pages throttled:                              0.
Pages wired down:                        100000.
Pages purgeable:                          20000.
"Translation faults":                 123456789.
Pages copy-on-write:                    5000000.
Anonymous pages:                         320000.
Pages occupied by compressor:             50000.
"""
CPUINFO = "processor\t: 0\nvendor_id\t: AuthenticAMD\nmodel name\t: AMD Ryzen 7 5800X 8-Core Processor\n"
MOUNTS = r"""sysfs /sys sysfs rw,nosuid 0 0
proc /proc proc rw 0 0
/dev/nvme0n1p2 / ext4 rw,relatime 0 0
/dev/nvme0n1p1 /boot/efi vfat rw 0 0
tmpfs /run tmpfs rw 0 0
/dev/loop3 /snap/core22/1380 squashfs ro 0 0
/dev/sda1 /media/joseph/Big\040Disk ntfs3 rw 0 0
/dev/nvme0n1p3 /home/joseph/games ext4 rw 0 0
/dev/nvme0n1p2 /var/lib/docker ext4 rw 0 0
/dev/sr0 /media/cdrom iso9660 ro 0 0
overlay /var/lib/docker/overlay2/abc/merged overlay rw 0 0
"""
DF_MAC = """Filesystem     1024-blocks      Used Available Capacity  Mounted on
/dev/disk3s1s1   971350180  10000000 500000000     3%    /
devfs                  200       200         0   100%    /dev
/dev/disk3s6     971350180   4000000 500000000     1%    /System/Volumes/VM
/dev/disk3s5     971350180 400000000 500000000    45%    /System/Volumes/Data
map auto_home            0         0         0   100%    /System/Volumes/Data/home
/dev/disk5s1     1953514584 953514584 1000000000   49%    /Volumes/Photo Backup
"""


class FakeRun:
    """Stands in for pcstatus._run: answers by the command's first word; records every command."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, argv, timeout=pcstatus.RUN_TIMEOUT_S):
        self.calls.append(list(argv))
        a = self.answers.get(argv[0])
        if isinstance(a, BaseException):
            raise a
        return a


@pytest.fixture
def fake(monkeypatch):
    """Use as fake(system, commands={...}, files={...})."""
    def setup(os_name: str, commands: dict | None = None, files: dict | None = None):
        run = FakeRun(commands or {})
        files = files or {}
        monkeypatch.setattr(pcstatus, "_os", lambda: os_name)
        monkeypatch.setattr(pcstatus, "_run", run)
        monkeypatch.setattr(pcstatus, "_read_file", lambda p: files.get(p))
        monkeypatch.setattr(pcstatus, "_cores", lambda: 8)
        monkeypatch.setattr(pcstatus, "SAMPLE_S", 0)
        monkeypatch.setattr(pcstatus.hardware, "_cpu_counters", lambda: None)
        monkeypatch.setattr(pcstatus.hardware, "cpu_pct", lambda: 12)
        return run
    return setup


class FakeServices:
    def __init__(self, ollama=True, comfy=False, models=None, raises=False):
        self._o, self._c, self._raises = ollama, comfy, raises
        me = self

        class Client:
            def loaded_models(self):
                if me._raises:
                    raise RuntimeError("boom")
                return models or []
        self.ollama = Client()

    def ollama_up(self):
        return self._o

    def comfy_up(self):
        return self._c


# --------------------------------------------------------------------------- the real command runner
def test_run_gives_none_when_a_command_is_missing_or_slow(monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError("no such program")

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)
    monkeypatch.setattr(pcstatus.subprocess, "run", missing)
    assert pcstatus._run(["nvidia-smi"]) is None
    monkeypatch.setattr(pcstatus.subprocess, "run", slow)
    assert pcstatus._run(["powershell"]) is None


def test_run_uses_a_list_no_shell_a_timeout_and_no_window(monkeypatch):
    seen = {}

    def run(argv, **kw):
        seen.update(kw, argv=argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n".encode(), stderr=b"")
    monkeypatch.setattr(pcstatus.subprocess, "run", run)
    assert pcstatus._run(["tasklist", "/FO", "CSV", "/NH"]) == "ok\n"
    assert isinstance(seen["argv"], list) and not seen.get("shell")
    assert seen["timeout"] > 0 and seen["capture_output"] is True and "creationflags" in seen


def test_run_failure_with_no_output_is_none_and_odd_bytes_still_read(monkeypatch):
    monkeypatch.setattr(pcstatus.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"bad"))
    assert pcstatus._run(["ps"]) is None
    monkeypatch.setattr(pcstatus.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=b'"caf\x82.exe","1","C","1","5 K"', stderr=b""))
    assert "caf" in pcstatus._run(["tasklist"])


# --------------------------------------------------------------------------- parsers
def test_parse_tasklist_reads_quoted_csv_with_commas_in_names():
    rows = pcstatus.parse_tasklist(TASKLIST)
    by = {r["pid"]: r for r in rows}
    assert by[1200] == {"pid": 1200, "name": "chrome.exe", "mem": 312_000 * 1024}
    assert by[4400]["name"] == "My App, Deluxe.exe" and by[4400]["mem"] == 20_480 * 1024
    assert by[3300]["mem"] == 1_048_576 * 1024


@pytest.mark.parametrize("text,kb", [(TASKLIST_DE, 312_000), (TASKLIST_FR, 312_000),
                                     ('"a.exe","1","C","1","1.234 K"', 1234), ('"a.exe","1","C","1","1,234 K"', 1234),
                                     ('"a.exe","1","C","1","1\u202f234 K"', 1234)])
def test_parse_tasklist_reads_any_languages_number_format(text, kb):
    assert pcstatus.parse_tasklist(text)[0]["mem"] == kb * 1024


def test_parse_tasklist_empty_and_junk():
    assert pcstatus.parse_tasklist("") == []
    assert pcstatus.parse_tasklist(None) == []
    assert pcstatus.parse_tasklist("INFO: No tasks are running which match the specified criteria.\n") == []


def test_parse_tasklist_drops_user_and_window_title_columns():
    rows = pcstatus.parse_tasklist(TASKLIST_V)
    assert rows == [{"pid": 777, "name": "notepad.exe", "mem": 9000 * 1024}]


def test_parse_win_perf_strips_instance_numbers_and_skips_total_and_idle():
    rows = pcstatus.parse_win_perf(WIN_PERF)
    names = [r["name"] for r in rows]
    assert "_Total" not in names and "Idle" not in names
    assert names.count("chrome") == 2 and "My App, Deluxe" in names
    ch = [r for r in rows if r["pid"] == 1201][0]
    assert ch == {"pid": 1201, "name": "chrome", "cpu_raw": 8.0, "mem": 50_000_000}


def test_parse_win_perf_empty_and_bom():
    assert pcstatus.parse_win_perf("") == []
    assert pcstatus.parse_win_perf(None) == []
    assert len(pcstatus.parse_win_perf("\ufeff" + WIN_PERF)) == 5


def test_parse_ps_mac_keeps_only_the_last_part_of_a_path():
    rows = pcstatus.parse_ps(PS_MAC)
    names = [r["name"] for r in rows]
    assert names == ["launchd", "Google Chrome", "Google Chrome Helper (Renderer)",
                     "Google Chrome Helper (Renderer)", "thing"]
    assert rows[1]["cpu"] == 25.5 and rows[1]["mem"] == 800_000 * 1024
    assert rows[3]["cpu"] == 1.5                       # "1,5" from a comma-decimal language


def test_parse_ps_linux_and_empty():
    rows = pcstatus.parse_ps(PS_LINUX)
    assert [r["name"] for r in rows] == ["systemd", "kthreadd", "firefox", "Web Content"]
    assert pcstatus.parse_ps("") == [] and pcstatus.parse_ps(None) == []


def test_parse_proc_stat_handles_spaces_and_brackets_in_the_name():
    line = "4242 (Web (Content) x) S 1 2 3 0 -1 0 0 0 0 0 150 50 0 0 20 0 1 0 100 1000 2048 0"
    st = pcstatus.parse_proc_stat(line)
    assert st == {"pid": 4242, "name": "Web (Content) x", "ticks": 200, "rss_pages": 2048}
    assert pcstatus.parse_proc_stat("") is None
    assert pcstatus.parse_proc_stat("garbage") is None
    assert pcstatus.parse_proc_stat("12 (x) S 1") is None


def test_parse_nvidia_apps_reads_numbers_by_process_id_only():
    assert pcstatus.parse_nvidia_apps(NVIDIA_APPS) == {3300: 7900 * MB, 1200: 300 * MB}
    assert pcstatus.parse_nvidia_apps("") == {}
    assert pcstatus.parse_nvidia_apps("No running processes found\n") == {}


def test_parse_meminfo_and_vm_stat():
    assert pcstatus.parse_meminfo(MEMINFO) == (32_768_000 * 1024, 12_000_000 * 1024)
    assert pcstatus.parse_meminfo("") is None
    total = 16 * GB
    t, free = pcstatus.parse_vm_stat(VM_STAT, total)
    used_pages = 320_000 - 20_000 + 100_000 + 50_000
    assert t == total and free == total - used_pages * 16384
    assert pcstatus.parse_vm_stat("", total) is None
    assert pcstatus.parse_vm_stat(VM_STAT, 0) is None


def test_parse_cpuinfo():
    assert pcstatus.parse_cpuinfo(CPUINFO) == "AMD Ryzen 7 5800X 8-Core Processor"
    assert pcstatus.parse_cpuinfo("") == ""
    assert pcstatus.parse_cpuinfo("Hardware\t: BCM2835\n") == "BCM2835"


def test_parse_mounts_keeps_real_writable_volumes_once():
    vols = pcstatus.parse_mounts(MOUNTS)
    assert [v["mount"] for v in vols] == ["/", "/media/joseph/Big Disk", "/home/joseph/games"]
    assert pcstatus.parse_mounts("") == []


def test_parse_df_mac_keeps_real_disks_and_names_with_spaces():
    vols = pcstatus.parse_df(DF_MAC)
    assert [v["mount"] for v in vols] == ["/", "/Volumes/Photo Backup"]
    assert vols[1]["free"] == 1_000_000_000 * 1024
    assert pcstatus.parse_df("") == []


def test_plain_mount_hides_user_names():
    assert pcstatus.plain_mount("/media/joseph/Big Disk") == "/media/Big Disk"
    assert pcstatus.plain_mount("/run/media/joseph/USB") == "/media/USB"
    assert pcstatus.plain_mount("/home/joseph/games") == "~/games"
    assert pcstatus.plain_mount("/Users/joseph") == "~"
    assert pcstatus.plain_mount("/mnt/data") == "/mnt/data"


# --------------------------------------------------------------------------- grouping, sorting, clamping
def test_group_adds_same_names_and_sorts_by_memory_then_processor():
    rows = [{"name": "chrome.exe", "cpu": 1.0, "mem": 100, "gpu": None},
            {"name": "Chrome.exe", "cpu": 2.0, "mem": 200, "gpu": 5},
            {"name": "b", "cpu": 9.0, "mem": 50, "gpu": None},
            {"name": "a", "cpu": 1.0, "mem": 50, "gpu": None},
            {"name": "c", "cpu": None, "mem": 50, "gpu": None}]
    g = pcstatus.group(rows)
    assert [x["name"] for x in g] == ["chrome.exe", "b", "a", "c"]
    assert g[0]["count"] == 2 and g[0]["mem"] == 300 and g[0]["cpu"] == 3.0 and g[0]["gpu"] == 5
    assert g[3]["cpu"] is None


@pytest.mark.parametrize("asked,got", [(0, 1), (-5, 1), (1, 1), (25, 25), (100, 100), (101, 100), (10_000, 100),
                                       ("7", 7), ("lots", 25), (None, 25), (3.9, 3)])
def test_clamp_rows(asked, got):
    assert pcstatus.clamp_rows(asked) == got


def test_process_lines_counts_and_columns():
    rows = [{"pid": i, "name": "chrome.exe", "cpu": 1.0, "mem": 100 * MB, "gpu": None} for i in range(23)]
    rows += [{"pid": 99, "name": "ollama.exe", "cpu": 3.0, "mem": 8 * GB, "gpu": 7 * GB}]
    out = pcstatus.process_lines({"rows": rows, "gpu_known": True}, 2)
    assert out[0].startswith("Processes (top 2 of 2 by memory, then processor; 24 running; names and numbers only")
    assert "graphics" in out[1]
    assert out[2].endswith("ollama.exe") and "8.0 GB" in out[2] and "7.0 GB" in out[2]
    assert out[3].endswith("chrome.exe x23") and "2.2 GB" in out[3] and "23%" in out[3]
    assert len(out) == 4


def test_process_lines_without_graphics_or_processor_numbers_say_so():
    out = pcstatus.process_lines({"rows": [{"pid": 1, "name": "a", "cpu": None, "mem": 5 * MB, "gpu": None}],
                                  "gpu_known": False})
    assert "graphics memory per program not reported here" in out[0]
    assert "processor share not known" in out[0]
    assert "graphics" not in out[1]
    assert out[2].split() == ["5", "MB", "-", "a"]
    assert pcstatus.process_lines(None) == ["Processes: " + pcstatus.NOT_KNOWN]


def test_windows_rows_join_names_by_id_and_divide_by_cores():
    rows = pcstatus.windows_rows(pcstatus.parse_win_perf(WIN_PERF), pcstatus.parse_tasklist(TASKLIST), 8)
    by = {r["pid"]: r for r in rows}
    assert by[3300]["name"] == "ollama.exe" and by[3300]["cpu"] == 4.0 and by[3300]["mem"] == 900_000_000
    assert by[4400]["name"] == "My App, Deluxe.exe"
    assert 0 not in by


def test_windows_rows_all_zero_counters_mean_processor_not_known():
    rows = pcstatus.windows_rows(pcstatus.parse_win_perf(WIN_PERF_ZERO), [], 8)
    assert all(r["cpu"] is None for r in rows) and rows[0]["name"] == "chrome"


def test_windows_rows_fall_back_to_tasklist_alone():
    rows = pcstatus.windows_rows([], pcstatus.parse_tasklist(TASKLIST), 8)
    assert {r["name"] for r in rows} >= {"chrome.exe", "System", "ollama.exe"}
    assert all(r["cpu"] is None for r in rows) and all(r["pid"] != 0 for r in rows)


def test_linux_rows_processor_share_over_the_gap():
    a = {10: {"pid": 10, "name": "ollama", "ticks": 1000, "rss_pages": 10},
         11: {"pid": 11, "name": "kworker/0:1", "ticks": 0, "rss_pages": 0}}
    b = {10: {"pid": 10, "name": "ollama", "ticks": 1100, "rss_pages": 1000},
         11: {"pid": 11, "name": "kworker/0:1", "ticks": 50, "rss_pages": 0},
         12: {"pid": 12, "name": "new", "ticks": 5, "rss_pages": 1}}
    rows = pcstatus.linux_rows(a, b, 1.0, 100, 4096, 4)
    by = {r["pid"]: r for r in rows}
    assert by[10]["cpu"] == 25.0 and by[10]["mem"] == 1000 * 4096
    assert 11 not in by                                 # kernel thread: no memory of its own
    assert by[12]["cpu"] == 0.0


# --------------------------------------------------------------------------- each system, end to end
def test_windows_processes_with_both_sources(fake):
    run = fake("windows", {"tasklist": TASKLIST, "powershell": WIN_PERF, "nvidia-smi": NVIDIA_APPS})
    info = pcstatus.running_processes()
    assert info["gpu_known"]
    out = "\n".join(pcstatus.process_lines(info))
    assert "ollama.exe" in out and "7.7 GB" in out
    assert "chrome.exe x2" in out
    tl = [c for c in run.calls if c[0] == "tasklist"][0]
    assert "/V" not in [x.upper() for x in tl]


def test_windows_processes_when_powershell_is_missing_or_times_out(fake):
    fake("windows", {"tasklist": TASKLIST, "powershell": None, "nvidia-smi": None})
    info = pcstatus.running_processes()
    assert info and not info["gpu_known"]
    out = "\n".join(pcstatus.process_lines(info))
    assert "processor share not known" in out and "ollama.exe" in out


def test_windows_processes_when_nothing_answers(fake):
    fake("windows", {})
    assert pcstatus.running_processes() is None


def test_mac_processes(fake):
    run = fake("mac", {"ps": PS_MAC})
    info = pcstatus.running_processes()
    out = "\n".join(pcstatus.process_lines(info))
    assert "Google Chrome Helper (Renderer) x2" in out
    g = [x for x in pcstatus.group(info["rows"]) if x["name"] == "Google Chrome"][0]
    assert g["cpu"] == pytest.approx(25.5 / 8)
    ps = [c for c in run.calls if c[0] == "ps"][0]
    fields = " ".join(ps)
    assert "comm" in fields and "args" not in fields and "command" not in fields


def test_linux_falls_back_to_ps_when_proc_gives_nothing(fake, monkeypatch):
    fake("linux", {"ps": PS_LINUX})
    monkeypatch.setattr(pcstatus, "_linux_snapshot", lambda: {})
    info = pcstatus.running_processes()
    names = {r["name"] for r in info["rows"]}
    assert names == {"systemd", "firefox", "Web Content"}          # kthreadd: no memory, no processor


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc and os.sysconf, which only Linux has")
def test_linux_processes_from_proc(fake, monkeypatch):
    fake("linux", {})
    snaps = iter([{5: {"pid": 5, "name": "python3", "ticks": 0, "rss_pages": 100}},
                  {5: {"pid": 5, "name": "python3", "ticks": 10, "rss_pages": 100}}])
    monkeypatch.setattr(pcstatus, "_linux_snapshot", lambda: next(snaps))
    info = pcstatus.running_processes()
    assert info["rows"][0]["name"] == "python3" and info["rows"][0]["cpu"] > 0


def test_memory_each_system(fake, monkeypatch):
    fake("linux", files={"/proc/meminfo": MEMINFO})
    assert pcstatus.memory_lines() == ["Memory: 31.2 GB, 19.8 used, 11.4 free"]
    fake("mac", {"sysctl": str(16 * GB) + "\n", "vm_stat": VM_STAT})
    assert pcstatus.memory_lines()[0].startswith("Memory: 16.0 GB, 6.9 used, 9.1 free")
    fake("windows")
    monkeypatch.setattr(pcstatus, "_windows_memory", lambda: (32 * GB, 8 * GB))
    assert pcstatus.memory_lines() == ["Memory: 32.0 GB, 24.0 used, 8.0 free"]
    fake("mac", {})
    assert pcstatus.memory_lines() == ["Memory: " + pcstatus.NOT_KNOWN]


def test_processor_line(fake, monkeypatch):
    fake("linux", files={"/proc/cpuinfo": CPUINFO})
    assert pcstatus.processor_lines() == ["Processor: AMD Ryzen 7 5800X 8-Core Processor, 8 cores (logical), 12% busy"]
    counters = iter([(100.0, 1000.0), (150.0, 1100.0)])
    monkeypatch.setattr(pcstatus.hardware, "_cpu_counters", lambda: next(counters))
    assert pcstatus.processor_lines()[0].endswith("50% busy")
    fake("mac", {})
    monkeypatch.setattr(pcstatus.hardware, "cpu_pct", lambda: None)
    assert pcstatus.processor_lines() == ["Processor: 8 cores (logical), load not known"]


def test_graphics_lines(monkeypatch):
    assert pcstatus.graphics_lines() == ["Graphics card: none found that reports itself"]     # conftest hides the real one
    card = {"name": "NVIDIA GeForce RTX 4070 SUPER", "vendor": "nvidia", "unified": False, "temp_c": 61,
            "util_pct": 34, "vram_used_mb": 9318, "vram_total_mb": 12282, "power_w": 120.5, "fan_pct": 30}
    monkeypatch.setattr(hardware, "gpu", lambda: card)
    assert pcstatus.graphics_lines() == ["Graphics card: NVIDIA GeForce RTX 4070 SUPER, 12.0 GB, 9.1 used, 2.9 free, 61 C, 34% busy, 120 W"]
    apple = {"name": "Apple M2 Pro", "vendor": "apple", "unified": True, "temp_c": None, "util_pct": None,
             "vram_used_mb": None, "vram_total_mb": 10813, "power_w": None, "fan_pct": None}
    monkeypatch.setattr(hardware, "gpu", lambda: apple)
    assert pcstatus.graphics_lines() == ["Graphics card: Apple M2 Pro, shares the main memory (about 10.6 GB usable)"]


def test_disks_each_system(fake, monkeypatch):
    usage = {"/": (500 * GB, 100 * GB), "/media/joseph/Big Disk": (2000 * GB, 1500 * GB),
             "/home/joseph/games": (4 * GB, 1 * GB)}
    monkeypatch.setattr(pcstatus, "_usage", lambda p: usage.get(p.rstrip("\\")) or usage.get(p))
    fake("linux", files={"/proc/mounts": MOUNTS})
    line = pcstatus.disk_lines()[0]
    assert line == "Disks: / 500 GB, 100 free | /media/Big Disk 2,000 GB, 1,500 free | ~/games 4.0 GB, 1.0 free"
    assert "joseph" not in line
    fake("mac", {"df": DF_MAC})
    line = pcstatus.disk_lines()[0]
    assert line.startswith("Disks: / 926 GB, 477 free | /Volumes/Photo Backup 1,863 GB, 954 free")
    fake("windows")
    monkeypatch.setattr(pcstatus, "_windows_drives", lambda: ["C:", "D:", "E:"])
    usage.update({"C:": (931 * GB, 212 * GB), "D:": (1863 * GB, 1020 * GB)})          # E: an empty card reader
    assert pcstatus.disk_lines() == ["Disks: C: 931 GB, 212 free | D: 1,863 GB, 1,020 free"]
    fake("mac", {})
    assert pcstatus.disk_lines() == ["Disks: " + pcstatus.NOT_KNOWN]


def test_engines(monkeypatch):
    models = [{"name": "gemma4:12b", "size": int(8.1 * GB), "size_vram": int(8.1 * GB)},
              {"name": "hf.co/someone/tiny:Q4", "size": 2 * GB, "size_vram": 1 * GB}]
    monkeypatch.setattr(pcstatus, "_services", lambda s: FakeServices(True, False, models))
    assert pcstatus.engine_parts(Settings()) == [
        "Ollama yes (gemma4:12b, 8.1 GB, all on the graphics card; hf.co/someone/tiny:Q4, 2.0 GB, 50% on the graphics card)",
        "ComfyUI no"]
    monkeypatch.setattr(pcstatus, "_services", lambda s: FakeServices(True, True, []))
    assert pcstatus.engine_parts(Settings()) == ["Ollama yes (no model loaded)", "ComfyUI yes"]
    monkeypatch.setattr(pcstatus, "_services", lambda s: FakeServices(True, True, raises=True))
    assert pcstatus.engine_parts(Settings())[0] == "Ollama yes"
    monkeypatch.setattr(pcstatus, "_services", lambda s: FakeServices(False, False))
    assert pcstatus.engine_parts(Settings()) == ["Ollama no", "ComfyUI no"]
    assert pcstatus.model_text({"name": "x", "size": 3 * GB, "size_vram": 0}) == "x, 3.0 GB, all on the processor"
    assert pcstatus.model_text({"name": "lms-model", "size": 1, "size_vram": 1}) == "lms-model"


def test_engines_with_the_real_service_manager_when_nothing_runs():
    """conftest refuses the usual ports, so the real ServiceManager says no to both."""
    assert pcstatus.engine_parts(Settings()) == ["Ollama no", "ComfyUI no"]


def test_unsloth_by_name_only():
    assert pcstatus.unsloth_text({"rows": [{"name": "unsloth-studio.exe"}]}) == "Unsloth Studio running"
    assert pcstatus.unsloth_text({"rows": [{"name": "python.exe"}]}) == "Unsloth Studio not seen"
    assert pcstatus.unsloth_text(None) == "Unsloth Studio " + pcstatus.NOT_KNOWN


# --------------------------------------------------------------------------- privacy
SECRETS = ("--api-key", "hunter2", "/Users/joseph", "Secret Project", "secret-plans", "Notepad", "PC\\joseph",
           "C:\\Users", "Applications/", "Contents/")


def test_privacy_nothing_but_names_and_numbers_reaches_the_report(fake, monkeypatch):
    nvidia = "1200, 300\n3300, 7900\n"
    ps = PS_MAC + "  950   0.1  4000 /usr/local/bin/runner --api-key hunter2\n"
    monkeypatch.setattr(pcstatus, "_services", lambda s: FakeServices(False, False))
    monkeypatch.setattr(pcstatus, "_usage", lambda p: None)
    for os_name, cmds in (("windows", {"tasklist": TASKLIST + TASKLIST_V, "powershell": WIN_PERF, "nvidia-smi": nvidia}),
                          ("mac", {"ps": ps, "nvidia-smi": None})):
        run = fake(os_name, cmds)
        if os_name == "windows":
            monkeypatch.setattr(pcstatus, "_windows_memory", lambda: None)
            monkeypatch.setattr(pcstatus, "_windows_drives", lambda: [])
        text = pcstatus.report(Settings(), 100)
        for s in SECRETS:
            assert s not in text, (os_name, s)
        for c in run.calls:
            joined = " ".join(c).lower()
            assert "/v" not in c and "args" not in joined and "command=" not in joined
            assert "commandline" not in joined and "mainwindowtitle" not in joined and "username" not in joined


@pytest.mark.parametrize("raw,name", [
    ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "Google Chrome"),
    ("C:\\Program Files\\Ollama\\ollama.exe", "ollama.exe"),
    ("C:\\Program Files\\x\\app.exe --token abc", "app.exe"),
    ("/usr/bin/python3 /home/joseph/secret.py", "python3"),
    ("runner -k hunter2", "runner"),
    ("node C:\\Users\\joseph\\bot.js", "node"),
    ("Web Content", "Web Content"),
    ("Google Chrome Helper (Renderer)", "Google Chrome Helper (Renderer)"),
    ("bad\x00\x1bname", "badname"),
    ("x" * 200, "x" * 60),
    ("", ""),
])
def test_clean_name_keeps_only_the_programs_name(raw, name):
    assert pcstatus.clean_name(raw) == name


def test_privacy_nvidia_names_are_never_read(fake):
    fake("linux", {"nvidia-smi": "3300, 7900\n"})
    assert pcstatus._NVIDIA_APPS[1] == "--query-compute-apps=pid,used_memory"
    assert pcstatus.gpu_memory_by_pid() == {3300: 7900 * MB}


def test_nothing_here_can_change_a_process():
    import inspect
    src = inspect.getsource(pcstatus)
    for word in ("kill(", "terminate(", "setpriority", "SetPriorityClass", "taskkill", "Stop-Process",
                 "suspend", "TerminateProcess", "/proc/{d}/cmdline", "/environ", "shell=True"):
        assert word not in src, word


# --------------------------------------------------------------------------- the whole report
def _quiet(monkeypatch):
    monkeypatch.setattr(pcstatus, "_services", lambda s: FakeServices(True, False, [
        {"name": "gemma4:12b", "size": int(8.1 * GB), "size_vram": int(8.1 * GB)}]))
    monkeypatch.setattr(pcstatus, "_usage", lambda p: (931 * GB, 212 * GB) if p.startswith("C:") else None)
    monkeypatch.setattr(pcstatus, "_windows_drives", lambda: ["C:"])
    monkeypatch.setattr(pcstatus, "_windows_memory", lambda: (32 * GB, 13 * GB))


def test_report_shape_on_windows(fake, monkeypatch):
    fake("windows", {"tasklist": TASKLIST, "powershell": WIN_PERF, "nvidia-smi": NVIDIA_APPS})
    _quiet(monkeypatch)
    text = pcstatus.report(Settings(), processes=3)
    lines = text.splitlines()
    assert lines[0].startswith("[this computer | Windows")
    assert lines[1].startswith("Processor: ") and "8 cores" in lines[1]
    assert lines[2] == "Memory: 32.0 GB, 19.0 used, 13.0 free"
    assert lines[3].startswith("Graphics card: ")
    assert lines[4] == "Disks: C: 931 GB, 212 free"
    assert lines[5] == "Running: Ollama yes (gemma4:12b, 8.1 GB, all on the graphics card) | ComfyUI no | Unsloth Studio not seen"
    assert lines[6].startswith("Processes (top 3 of 4 by memory, then processor")
    assert lines[8].endswith("ollama.exe")
    assert lines[-1] == pcstatus.FOOTER
    assert len(lines) == 8 + 3 + 1


def test_report_keeps_the_other_parts_when_one_raises(fake, monkeypatch):
    fake("windows", {"tasklist": TASKLIST, "powershell": WIN_PERF})
    _quiet(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("broken")
    for name, label in (("memory_lines", "Memory"), ("processor_lines", "Processor"), ("graphics_lines", "Graphics card"),
                        ("disk_lines", "Disks")):
        with monkeypatch.context() as m:
            m.setattr(pcstatus, name, boom)
            text = pcstatus.report(Settings())
        assert f"{label}: {pcstatus.NOT_KNOWN}" in text
        assert "ollama.exe" in text and "Running: Ollama yes" in text and text.endswith(pcstatus.FOOTER)
    with monkeypatch.context() as m:
        m.setattr(pcstatus, "running_processes", boom)
        text = pcstatus.report(Settings())
    assert "Processes: " + pcstatus.NOT_KNOWN in text and "Unsloth Studio " + pcstatus.NOT_KNOWN in text
    assert "Memory: 32.0 GB" in text
    with monkeypatch.context() as m:
        m.setattr(pcstatus, "engine_parts", boom)
        text = pcstatus.report(Settings())
    assert "Running: writing program " + pcstatus.NOT_KNOWN in text and "ollama.exe" in text


def test_report_a_slow_part_doesnt_hold_up_the_rest(fake, monkeypatch):
    import threading
    fake("windows", {"tasklist": TASKLIST})
    _quiet(monkeypatch)
    gate = threading.Event()
    monkeypatch.setattr(pcstatus, "graphics_lines", lambda: gate.wait(10) and ["Graphics card: late"])
    monkeypatch.setattr(pcstatus, "PART_TIMEOUT_S", 0.3)
    t0 = time.monotonic()
    try:
        text = pcstatus.report(Settings())
    finally:
        gate.set()
    assert time.monotonic() - t0 < 5
    assert "Graphics card: " + pcstatus.NOT_KNOWN in text and "chrome.exe x2" in text


def test_report_clamps_rows_and_when_everything_fails(fake, monkeypatch):
    fake("linux", {})
    monkeypatch.setattr(pcstatus, "_linux_snapshot", lambda: {})
    monkeypatch.setattr(pcstatus, "_services", lambda s: FakeServices(False, False))
    text = pcstatus.report(Settings(), processes=0)
    assert "Memory: " + pcstatus.NOT_KNOWN in text and "Disks: " + pcstatus.NOT_KNOWN in text
    assert "Processes: " + pcstatus.NOT_KNOWN in text and text.endswith(pcstatus.FOOTER)
    fake("mac", {"ps": PS_MAC})
    text = pcstatus.report(Settings(), processes=0)
    assert "Processes (top 1 of 4" in text
    many = "".join(f"{i} 0.0 {1000 + i} prog{i}\n" for i in range(1, 300))
    fake("mac", {"ps": many})
    text = pcstatus.report(Settings(), processes=500)
    assert "Processes (top 100 of 299" in text
    assert len([ln for ln in text.splitlines() if ln.startswith("  ") and "prog" in ln]) == 100
