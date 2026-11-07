"""Release signing: is this release really from Joe's maker?

SHA256SUMS.txt (one line per release file) only catches a damaged download: anyone who could
change a release could change that list too. So the release workflow also signs the list with
the maker's private key (Ed25519, kept only as a GitHub secret), and Joe checks the signature
with the public key built into him (joeai/__init__.py SIGN_PUBLIC_KEY) before he installs
an update. A wrong or missing signature = Joe won't install it.

Ed25519 as in RFC 8032, written out here in plain Python because the standard library has
no Ed25519 (and Joe has no other dependencies). It's slow next to a C library, but one check
of one small file takes a fraction of a second. Checked against the RFC's test vectors.

    python installer/make_signing_key.py     makes a key pair (once, on the maker's PC)
    python installer/sign_release.py FILE    signs FILE -> FILE.sig (the release workflow)
"""
from __future__ import annotations

import base64
import hashlib

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


_D = -121665 * _inv(121666) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _I % _P
    if (x * x - x2) % _P:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)
_ZERO = (0, 1, 1, 0)


def _add(a, b):
    A = (a[1] - a[0]) * (b[1] - b[0]) % _P
    B = (a[1] + a[0]) * (b[1] + b[0]) % _P
    C = 2 * a[3] * b[3] * _D % _P
    D = 2 * a[2] * b[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(s: int, pt):
    q = _ZERO
    while s > 0:
        if s & 1:
            q = _add(q, pt)
        pt = _add(pt, pt)
        s >>= 1
    return q


def _same(a, b) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _compress(pt) -> bytes:
    z = _inv(pt[2])
    x, y = pt[0] * z % _P, pt[1] * z % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(s: bytes):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _h(m: bytes) -> int:
    return int.from_bytes(hashlib.sha512(m).digest(), "little")


def _expand(seed: bytes) -> tuple[int, bytes]:
    if len(seed) != 32:
        raise ValueError("an Ed25519 private key is 32 bytes")
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed: bytes) -> bytes:
    return _compress(_mul(_expand(seed)[0], _G))


def sign(seed: bytes, msg: bytes) -> bytes:
    a, prefix = _expand(seed)
    pub = _compress(_mul(a, _G))
    r = _h(prefix + msg) % _L
    R = _compress(_mul(r, _G))
    s = (r + _h(R + pub + msg) % _L * a) % _L
    return R + int.to_bytes(s, 32, "little")


def verify(pub: bytes, msg: bytes, sig: bytes) -> bool:
    if len(sig) != 64 or len(pub) != 32:
        return False
    A, R = _decompress(pub), _decompress(sig[:32])
    if A is None or R is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= _L:
        return False
    k = _h(sig[:32] + pub + msg) % _L
    return _same(_mul(s, _G), _add(R, _mul(k, A)))


# --------------------------------------------------------------------------- Joe's files
def b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def unb64(s: str) -> bytes:
    try:
        return base64.b64decode((s or "").strip(), validate=True)
    except (ValueError, TypeError):
        return b""


def sign_file_text(seed_b64: str, data: bytes) -> str:
    """The .sig file: one line of base64."""
    return b64(sign(unb64(seed_b64), data)) + "\n"


def check(data: bytes, sig_text: str, pub_b64: str) -> bool:
    return verify(unb64(pub_b64), data, unb64(sig_text.strip().splitlines()[0] if sig_text.strip() else ""))
