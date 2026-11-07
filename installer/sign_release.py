"""Sign a release file with the key in the JOE_SIGNING_KEY environment variable (the release
workflow's secret): FILE -> FILE.sig (one line of base64). Checks the result before it ends.

    JOE_SIGNING_KEY=... python installer/sign_release.py dist/SHA256SUMS.txt
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from joeai import sign  # noqa: E402

key = os.environ.get("JOE_SIGNING_KEY", "").strip()
if not key:
    sys.exit("JOE_SIGNING_KEY isn't set")
f = Path(sys.argv[1])
data = f.read_bytes()
text = sign.sign_file_text(key, data)
pub = sign.b64(sign.public_key(sign.unb64(key)))
if not sign.check(data, text, pub):
    sys.exit("signing failed its own check")
Path(str(f) + ".sig").write_text(text, encoding="ascii")
print(f"Signed {f.name}. Public key: {pub}")
