# Double-click this file to start Joe (01000001 01001001). No console window.
# Needs Python 3.11+ from python.org. Crashes are written to %APPDATA%\joe-ai\crash.log
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.argv[1:2] in (["mcp"], ["tonight"]):     # connector for AI apps / the night shift
    from joeai.cli import main  # noqa: E402
    sys.exit(main(sys.argv[1:]))

from joeai.app import run_logged  # noqa: E402

run_logged()
