"""Joe (01000001 01001001) - overnight grunt work on local AI models.

Copyright (C) 2026 Joe contributors.
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

__version__ = "2.0.0.dev139"
APP_NAME = "Joe"
REPO = "sirgijoe/joe-ai"            # where releases are published (update check)
# Release signing (joeai/sign.py): the public half of the key that signs each release's
# SHA256SUMS.txt. Blank = releases aren't signed yet (only the checksums are checked).
# Made with installer/make_signing_key.py; once set, an update without a matching signature is refused.
SIGN_PUBLIC_KEY = ""
