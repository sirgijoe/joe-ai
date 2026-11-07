# Code signing policy

Joe's Windows installer will be signed through SignPath Foundation's free program for open-source
projects (applied for; until it's approved, Windows may warn that the installer isn't signed; see
the README).

Once approved: Free code signing provided by [SignPath.io](https://about.signpath.io/),
certificate by [SignPath Foundation](https://signpath.org/).

## What gets signed

Only files built by this repository's own GitHub Actions workflow (`.github/workflows/release.yml`)
from the code in this repository: the Windows installer `Joe-Setup-<version>-windows-x64.exe` and
the program files inside it. Nothing built on a personal computer is ever signed.

Separately, every release's `SHA256SUMS.txt` is signed with Joe's own release key
(`SHA256SUMS.txt.sig`), and Joe refuses an update whose signature doesn't match the public key
built into him (`joeai/__init__.py`).

## Team roles

| Role | Who |
|---|---|
| Author (trusted committer) | [sirgijoe](https://github.com/sirgijoe) |
| Reviewer (reviews changes from anyone else) | [sirgijoe](https://github.com/sirgijoe) |
| Approver (approves each signing request by hand) | [sirgijoe](https://github.com/sirgijoe) |

All team members use multi-factor authentication for GitHub and SignPath.

## Privacy

Joe sends nothing about you anywhere on his own. The README section
[When Joe uses the internet](README.md#when-joe-uses-the-internet) lists every time he goes online
(setup downloads, update checks, and online lookups only when you turn them on). Programs Joe can
install for you (Ollama, ComfyUI, FFmpeg and others) are made by other people and have their own
privacy policies; [THIRD_PARTY.md](THIRD_PARTY.md) lists them.

## Uninstalling

Windows: Settings > Apps > Joe > Uninstall (removes only Joe's program folder; your files in
Documents\Joe-ai stay). Mac: drag Joe from Applications to the Trash. Linux: delete the AppImage.
