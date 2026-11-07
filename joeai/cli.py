"""Command line (optional: the app window, Joe.pyw, does all of this too).

    python -m joeai init [--workspace PATH]
    python -m joeai status
    python -m joeai doctor              (system check; asks before installing anything)
    python -m joeai check  MISSION      (dry run: validate + plan + estimate)
    python -m joeai run    MISSION      (MISSION = file in Missions/, or '-' to paste)
    python -m joeai mcp                 (Joe as a connector for Claude Desktop and other MCP apps)
    python -m joeai tonight             (the night shift: what the computer's scheduler runs)
"""
from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path

from . import __version__
from .config import Settings, config_path
from .engine import Engine
from .mission import MissionError, parse
from .sandbox import Sandbox, SandboxError
from .services import ServiceManager

SECONDS_PER_PART = 25   # rough estimate for qwen3:14b on a 12 GB card; refined by stats later


def _read_mission(sb: Sandbox, arg: str) -> str:
    if arg == "-":
        print("Paste the mission block, then press Ctrl+Z, Enter (Windows) or Ctrl+D:")
        return sys.stdin.read()
    p = Path(arg)
    if not p.is_absolute():
        p = sb.resolve(arg, base="Missions")
    sb.check(p)                               # missions must live in the workspace
    return p.read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="joe-ai", description=f"Joe {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser("init", help="create settings and workspace folders")
    p_init.add_argument("--workspace", help="workspace folder (default Documents\\Joe-ai)")
    sub.add_parser("status", help="check Ollama / ComfyUI")
    sub.add_parser("doctor", help="system check; offers to install/start what's missing")
    for name in ("check", "run"):
        p = sub.add_parser(name)
        p.add_argument("mission")
    sub.add_parser("mcp", help="talk MCP on stdin/stdout (for Claude Desktop and other AI apps)")
    sub.add_parser("tonight", help="start the plans saved for tonight (run by the night shift)")
    sub.add_parser("restart", help="start Joe's window after the old Joe has closed (RESTART JOE)")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):        # Windows consoles: an emoji in a title mustn't crash
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    from . import portable
    portable.start()
    if a.cmd == "mcp":
        from .mcp import serve
        return serve()
    if a.cmd == "restart":
        from .app import main as app_main, wait_for_old
        wait_for_old()
        return app_main()
    if a.cmd == "tonight":
        from .schedule import tonight
        return tonight()

    s = Settings.load()
    if a.cmd == "init":
        if a.workspace:
            s.workspace = str(Path(a.workspace).expanduser().resolve())
        sb = Sandbox(s.workspace_path).ensure()
        s.workspace = str(sb.root)
        cfg = s.save()
        print(f"Settings:  {cfg}\nWorkspace: {sb.root}")
        return 0

    sb = Sandbox(s.workspace_path).ensure()
    if a.cmd == "doctor":
        from . import doctor
        sm = ServiceManager(s)
        d = doctor.check(s, sm)
        g = d["gpu"]
        print(f"GPU:     {g['name'] + ', ' + str(d['vram_gb']) + ' GB' if g else 'no graphics card found'}")
        if d.get("gpu_advice"):
            print(f"         {d['gpu_advice']}")
        print(f"Ollama:  installed={d['ollama']['installed']} running={d['ollama']['running']} "
              f"best fit={d['ollama']['best']}")
        print(f"ComfyUI: installed={d['comfyui']['installed']} running={d['comfyui']['running']} "
              f"best image={d['comfyui']['best_image']} best video={d['comfyui']['best_video']}")
        for it in d["issues"]:
            ans = input(f"{it['text']}  Fix it now? [y/N] ").strip().lower()
            if ans != "y":
                continue
            act = it["action"]
            if act == "install":
                doctor.install(it["tool"], print, approved=True)
            elif act == "start":
                (sm.ensure_ollama if it["tool"] == "ollama" else sm.ensure_comfy)()
            elif act == "pull" and doctor.pull_ollama_model(sm, it["model"], print, approved=True):
                s.ollama.text_model = it["model"]
                s.save()
            elif act == "use":
                s.ollama.text_model = it["model"]
                s.save()
            elif act == "download-image-model":
                doctor.download_image_model(s, print, approved=True)
        return 0
    if a.cmd == "status":
        st = ServiceManager(s).status()
        print(f"Workspace: {sb.root}\nSettings:  {config_path()}")
        print(f"Ollama:    {'UP' if st['ollama'] else 'DOWN'}   ComfyUI: "
              f"{'UP' if st['comfyui'] else 'DOWN'}")
        for m in st["loaded"]:
            warn = "" if m["gpu_pct"] >= 100 else "  <- not fully on GPU, will be slow"
            print(f"  loaded: {m['name']}  {m['gpu_pct']}% GPU{warn}")
        return 0

    try:
        mission = parse(_read_mission(sb, a.mission))
        for j in mission.jobs:
            sb.resolve(j.save)
    except (MissionError, SandboxError, OSError) as e:
        print(f"MISSION ERROR: {e}")
        return 2

    total_parts = sum(j.parts for j in mission.jobs if not j.media)
    print(f"Project: {mission.project or '(none)'}")
    for j in mission.jobs:
        n = len(j.part_prompts) or j.parts * j.part_size
        shape = (f"{n} prompt(s) x {j.variants}" if j.media else
                 f"{j.parts} guided parts" if j.guided else f"{j.parts} x {j.part_size} = {j.total_items} items")
        print(f"  [{'csv' if j.is_csv else j.type}] {j.name}: {shape}"
              f" -> Output/{j.save}" + (f"  (min {j.min_words} words)" if j.min_words else ""))
    eta = total_parts * SECONDS_PER_PART / 60
    print(f"Estimate: {total_parts} parts, about {eta:.0f} min (more if items are long or retried)")
    if a.cmd == "check":
        return 0

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: (print("\nStopping after current step..."), stop.set()))
    states = Engine(s, sb, stop=stop).run_mission(mission)
    print(f"Report: {sb.output / '_REPORT.md'}")
    return 0 if all(x.status == "done" for x in states) else 1


if __name__ == "__main__":
    sys.exit(main())
