# Double-click this file to start Joe (01000001 01001001). No console window.
# Needs Python 3.11.4+ from python.org. Crashes are written to %APPDATA%\joe-ai\crash.log
# (portable Joe: JoeData\settings\crash.log on the drive).
import os
import sys

if sys.version_info < (3, 11, 4):                # older Pythons unpack downloads less safely
    _msg = (f"Joe needs Python 3.11.4 or newer; this computer has {sys.version.split()[0]}. "
            "Get the newest Python from python.org, then start Joe again.")
    try:
        import tkinter
        from tkinter import messagebox
        tkinter.Tk().withdraw()
        messagebox.showerror("Joe", _msg)
    except Exception:
        print(_msg)
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.argv[1:2] in (["mcp"], ["tonight"], ["disconnect-all"]):   # connector / night shift / uninstall
    from joeai.cli import main  # noqa: E402
    sys.exit(main(sys.argv[1:]))

from joeai.app import run_logged, wait_for_old  # noqa: E402

if sys.argv[1:2] == ["restart"]:                 # RESTART JOE: wait for the old Joe to close first
    wait_for_old()

run_logged()
