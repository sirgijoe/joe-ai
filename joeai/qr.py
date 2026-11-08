"""A small QR code maker (byte mode, error correction M, versions 1-10), so the phone pairing
picture needs no add-on. Returns the module grid or an SVG.

Follows ISO/IEC 18004: Reed-Solomon over GF(256), the eight masks scored by the four penalty
rules, format bits with BCH, version bits from version 7.
"""
from __future__ import annotations

# (total codewords, ec codewords per block, blocks in group 1, data cw per block g1, blocks g2, data cw g2), level M
_M = {1: (26, 10, 1, 16, 0, 0), 2: (44, 16, 1, 28, 0, 0), 3: (70, 26, 1, 44, 0, 0), 4: (100, 18, 2, 32, 0, 0),
      5: (134, 24, 2, 43, 0, 0), 6: (172, 16, 4, 27, 0, 0), 7: (196, 18, 4, 31, 0, 0), 8: (242, 22, 2, 38, 2, 39),
      9: (292, 22, 3, 36, 2, 37), 10: (346, 26, 4, 43, 1, 44)}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
          9: [6, 26, 46], 10: [6, 28, 50]}

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs(data: list[int], n: int) -> list[int]:
    gen = [1]
    for i in range(n):
        nxt = [0] * (len(gen) + 1)
        for j, g in enumerate(gen):
            nxt[j] ^= g
            nxt[j + 1] ^= _mul(g, _EXP[i])
        gen = nxt
    rem = list(data) + [0] * n
    for i in range(len(data)):
        c = rem[i]
        if c:
            for j in range(1, len(gen)):
                rem[i + j] ^= _mul(gen[j], c)
    return rem[len(data):]


def _codewords(text: bytes) -> tuple[int, list[int]]:
    for ver in range(1, 11):
        total, ec, b1, d1, b2, d2 = _M[ver]
        cap = b1 * d1 + b2 * d2
        count_bits = 8 if ver < 10 else 16
        if 4 + count_bits + 8 * len(text) <= cap * 8:
            break
    else:
        raise ValueError("too long for a QR code here (keep it under about 200 characters)")
    bits = [0, 1, 0, 0] + [(len(text) >> i) & 1 for i in range(count_bits - 1, -1, -1)]
    for byte in text:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, cap * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    data = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    while len(data) < cap:
        data.append(pad[(len(data) - len(bits) // 8) % 2])
    blocks, k = [], 0
    for cnt, size in ((b1, d1), (b2, d2)):
        for _ in range(cnt):
            blocks.append(data[k:k + size])
            k += size
    ecs = [_rs(b, ec) for b in blocks]
    out = []
    for i in range(max(len(b) for b in blocks)):
        out += [b[i] for b in blocks if i < len(b)]
    for i in range(ec):
        out += [e[i] for e in ecs]
    return ver, out


def _bch(value: int, poly: int, bits: int) -> int:
    v = value << (poly.bit_length() - 1)
    while v.bit_length() >= poly.bit_length():
        v ^= poly << (v.bit_length() - poly.bit_length())
    return (value << (poly.bit_length() - 1)) | v


_MASKS = (lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0,
          lambda r, c: (r + c) % 3 == 0, lambda r, c: (r // 2 + c // 3) % 2 == 0,
          lambda r, c: (r * c) % 2 + (r * c) % 3 == 0, lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
          lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0)


def _base(ver: int):
    n = 17 + 4 * ver
    grid = [[None] * n for _ in range(n)]

    def finder(r0, c0):
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = r0 + r, c0 + c
                if 0 <= rr < n and 0 <= cc < n:
                    on = 0 <= r <= 6 and 0 <= c <= 6 and (r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4))
                    grid[rr][cc] = on
    finder(0, 0)
    finder(0, n - 7)
    finder(n - 7, 0)
    for i in range(8, n - 8):
        grid[6][i] = grid[i][6] = i % 2 == 0
    pos = _ALIGN[ver]
    for r in pos:
        for c in pos:
            if (r, c) in ((pos[0], pos[0]), (pos[0], pos[-1]), (pos[-1], pos[0])):
                continue                           # those three would sit on the finder patterns
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    grid[r + dr][c + dc] = max(abs(dr), abs(dc)) != 1
    grid[n - 8][8] = True                          # the dark module
    for i in range(9):                             # reserve format areas
        for (r, c) in ((8, i), (i, 8)):
            if grid[r][c] is None:
                grid[r][c] = False
    for i in range(8):
        if grid[8][n - 1 - i] is None:
            grid[8][n - 1 - i] = False
        if grid[n - 1 - i][8] is None:
            grid[n - 1 - i][8] = False
    if ver >= 7:
        v = _bch(ver, 0x1F25, 12)
        for i in range(18):
            bit = bool((v >> i) & 1)
            grid[i // 3][n - 11 + i % 3] = bit
            grid[n - 11 + i % 3][i // 3] = bit
    return grid


def _place(grid, cws: list[int]):
    n = len(grid)
    func = [[v is not None for v in row] for row in grid]
    bits = [(cw >> i) & 1 for cw in cws for i in range(7, -1, -1)]
    k, up, c = 0, True, n - 1
    while c > 0:
        if c == 6:
            c -= 1
        for r in (range(n - 1, -1, -1) if up else range(n)):
            for cc in (c, c - 1):
                if not func[r][cc]:
                    grid[r][cc] = bool(bits[k]) if k < len(bits) else False
                    k += 1
        up = not up
        c -= 2
    return func


def _format(grid, mask: int):
    n = len(grid)
    v = _bch((0b00 << 3) | mask, 0x537, 10) ^ 0x5412      # level M = 00
    b = [bool((v >> i) & 1) for i in range(15)]
    for i in range(6):
        grid[i][8] = b[i]
    grid[7][8], grid[8][8], grid[8][7] = b[6], b[7], b[8]
    for i in range(9, 15):
        grid[8][14 - i] = b[i]
    for i in range(8):
        grid[8][n - 1 - i] = b[i]
    for i in range(8, 15):
        grid[n - 15 + i][8] = b[i]
    grid[n - 8][8] = True


def _penalty(g) -> int:
    n, p = len(g), 0
    for line in g + [list(col) for col in zip(*g)]:
        run = 1
        for i in range(1, n):
            if line[i] == line[i - 1]:
                run += 1
            else:
                p += run - 2 if run >= 5 else 0
                run = 1
        p += run - 2 if run >= 5 else 0
        s = "".join("1" if x else "0" for x in line)
        p += 40 * (s.count("10111010000") + s.count("00001011101"))
    for r in range(n - 1):
        for c in range(n - 1):
            if g[r][c] == g[r + 1][c] == g[r][c + 1] == g[r + 1][c + 1]:
                p += 3
    dark = sum(sum(row) for row in g)
    p += 10 * (abs(dark * 100 // (n * n) - 50) // 5)
    return p


def matrix(text: str) -> list[list[bool]]:
    ver, cws = _codewords(text.encode("utf-8"))
    best = None
    for m, fn in enumerate(_MASKS):
        g = _base(ver)
        func = _place(g, cws)
        for r in range(len(g)):
            for c in range(len(g)):
                if not func[r][c] and fn(r, c):
                    g[r][c] = not g[r][c]
        _format(g, m)
        score = _penalty(g)
        if best is None or score < best[0]:
            best = (score, g)
    return best[1]


def svg(text: str, scale: int = 6, quiet: int = 4) -> str:
    g = matrix(text)
    n = len(g) + 2 * quiet
    rects = "".join(f'<rect x="{c + quiet}" y="{r + quiet}" width="1" height="1"/>'
                    for r, row in enumerate(g) for c, on in enumerate(row) if on)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" width="{n * scale}" '
            f'height="{n * scale}" shape-rendering="crispEdges"><rect width="{n}" height="{n}" fill="#fff"/>'
            f'<g fill="#000">{rects}</g></svg>')
