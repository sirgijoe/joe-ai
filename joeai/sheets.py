"""Reading and writing tables for the spreadsheet tools: CSV, TSV and Excel (.xlsx, first
sheet, values only). Standard library only, works the same on every OS.

Tables come back as (header, rows): lists of strings, every row as long as the header.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_ROWS = 20_000                     # bigger sheets are cut (and the report says so)
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
_DATE_IDS = set(range(14, 23)) | {45, 46, 47}


class SheetError(ValueError):
    pass


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _square(rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise SheetError("the sheet is empty")
    width = max(len(r) for r in rows)
    header = [h.strip() or f"Column {i + 1}" for i, h in enumerate(rows[0] + [""] * (width - len(rows[0])))]
    seen: dict[str, int] = {}
    for i, h in enumerate(header):                       # unique column names
        n = seen.get(h.lower(), 0)
        seen[h.lower()] = n + 1
        if n:
            header[i] = f"{h} {n + 1}"
    body = [r + [""] * (width - len(r)) for r in rows[1:]]
    return header, body


def read_csv(p: Path) -> tuple[list[str], list[list[str]]]:
    text = _decode(p.read_bytes())
    if p.suffix.lower() == ".tsv":
        delim = "\t"
    else:
        try:
            delim = csv.Sniffer().sniff(text[:20_000], delimiters=",;\t|").delimiter
        except csv.Error:
            delim = ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    return _square(rows)


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _number(v: str) -> str:
    try:
        f = float(v)
    except ValueError:
        return v
    return str(int(f)) if f.is_integer() and abs(f) < 1e15 else repr(f)


def read_xlsx(p: Path) -> tuple[list[str], list[list[str]]]:
    try:
        z = zipfile.ZipFile(p)
    except zipfile.BadZipFile as e:
        raise SheetError("that Excel file couldn't be opened") from e
    with z:
        names = set(z.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
        date_styles: set[int] = set()
        if "xl/styles.xml" in names:
            st = ET.fromstring(z.read("xl/styles.xml"))
            custom = {int(n.get("numFmtId")): n.get("formatCode", "")
                      for n in st.findall("m:numFmts/m:numFmt", _NS)}
            for i, xf in enumerate(st.findall("m:cellXfs/m:xf", _NS)):
                fid = int(xf.get("numFmtId", "0"))
                code = re.sub(r'"[^"]*"|\[[^\]]*\]', "", custom.get(fid, "")).lower()
                if fid in _DATE_IDS or (code and re.search(r"[dy]", code) and "h" not in code):
                    date_styles.add(i)
        sheet = "xl/worksheets/sheet1.xml"
        try:                                             # the first sheet in the workbook's order
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            first = wb.find("m:sheets/m:sheet", _NS)
            rid = first.get(f"{{{_NS['r']}}}id")
            rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            for rel in rels.findall("pr:Relationship", _NS):
                if rel.get("Id") == rid:
                    t = rel.get("Target").lstrip("/")
                    sheet = t if t.startswith("xl/") else "xl/" + t
        except (KeyError, AttributeError, ET.ParseError):
            pass
        if sheet not in names:
            raise SheetError("no sheet found in that Excel file")
        rows: list[list[str]] = []
        for r in ET.fromstring(z.read(sheet)).iter(f"{{{_NS['m']}}}row"):
            row: list[str] = []
            for c in r.findall("m:c", _NS):
                idx = _col_index(c.get("r", "A1")) if c.get("r") else len(row)
                t = c.get("t", "")
                v = c.find("m:v", _NS)
                val = v.text if v is not None and v.text is not None else ""
                if t == "s" and val:
                    val = shared[int(val)] if int(val) < len(shared) else ""
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(f"{{{_NS['m']}}}t"))
                elif t == "b":
                    val = "TRUE" if val == "1" else "FALSE"
                elif val and t in ("", "n"):
                    if int(c.get("s", "0")) in date_styles:
                        try:
                            val = (date(1899, 12, 30) + timedelta(days=float(val))).isoformat()
                        except (ValueError, OverflowError):
                            pass
                    else:
                        val = _number(val)
                row += [""] * (idx - len(row))
                row.append(val)
            rows.append(row)
            if len(rows) > MAX_ROWS:
                break
    return _square(rows)


def read_table(p: Path) -> tuple[list[str], list[list[str]], bool]:
    """(header, rows, cut): `cut` is True when the sheet had more than MAX_ROWS rows."""
    ext = p.suffix.lower()
    if ext == ".xlsx":
        header, rows = read_xlsx(p)
    elif ext in (".csv", ".tsv", ".txt"):
        header, rows = read_csv(p)
    else:
        raise SheetError(f"{ext} files aren't spreadsheets Joe can read (CSV, TSV or .xlsx)")
    return header, rows[:MAX_ROWS], len(rows) > MAX_ROWS


def write_csv(p: Path, header: list[str], rows: list[list[str]]) -> None:
    """UTF-8 with a BOM, so Excel shows accents and other languages correctly."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(header)
    w.writerows(rows)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(buf.getvalue(), encoding="utf-8-sig", newline="")
    tmp.replace(p)
