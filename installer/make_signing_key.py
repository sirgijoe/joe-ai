"""Make Joe's release signing key pair. Run once, on the maker's own computer:

    python installer/make_signing_key.py

It prints two lines:
  PRIVATE: put it in GitHub > the joe-ai repo > Settings > Secrets and variables > Actions >
           New repository secret, named JOE_SIGNING_KEY. Then delete it from anywhere else
           (it never goes in a file, a chat or the repo: whoever has it can sign releases).
  PUBLIC:  paste it into joeai/__init__.py as SIGN_PUBLIC_KEY = "..." and commit.
From then on every release's SHA256SUMS.txt gets a SHA256SUMS.txt.sig, and Joe refuses an update
whose signature doesn't match. Keep a copy of the private key somewhere safe and offline (a
password manager): without it, future releases can't be signed with the same key.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from joeai import sign  # noqa: E402

seed = os.urandom(32)
print("PRIVATE (GitHub secret JOE_SIGNING_KEY):", sign.b64(seed))
print("PUBLIC  (joeai/__init__.py SIGN_PUBLIC_KEY):", sign.b64(sign.public_key(seed)))
