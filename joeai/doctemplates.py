"""Writing templates: how finished copies look (EXPORT: docx, pdf, epub, html, odt, xlsx).

Each template is a set of plain choices: page size, margins, fonts, text size, line spacing,
first-line indent, alignment, space between paragraphs, a new page for each chapter, a title
page. Joe's built-in ones cover the usual projects (everyday documents, a printed book, a
manuscript for an editor, a children's picture book, an e-book, a report, a spreadsheet).
Setup > Writing > TEMPLATES shows every one filled in, with EDIT; your changes are kept in
settings.json (Settings.templates) and RESET brings Joe's back. A task picks one with
TEMPLATE: <id>; otherwise each kind of file uses the default set in Setup.

How they're applied (no extra programs beyond Pandoc):
- PDF / HTML / EPUB: a style sheet (CSS) made from the template.
- Word (.docx): a "reference document" made from Pandoc's own, with the template's fonts,
  sizes, spacing, margins and page size written into its styles (cached per template).
- Spreadsheets (.xlsx from a .csv task): Joe writes the .xlsx himself (font, bold colored
  header row that stays in place, filter buttons, column widths, optional striped rows).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

# page name -> (width, height) in inches
PAGES = {"letter": (8.5, 11), "a4": (8.27, 11.69), "a5": (5.83, 8.27), "6x9": (6, 9), "5.5x8.5": (5.5, 8.5),
         "5x8": (5, 8), "8.5x8.5": (8.5, 8.5), "8x10": (8, 10), "legal": (8.5, 14)}
PAGE_LABELS = {"letter": "Letter (8.5 x 11 in)", "a4": "A4", "a5": "A5", "6x9": "6 x 9 in (paperback)",
               "5.5x8.5": "5.5 x 8.5 in (digest)", "5x8": "5 x 8 in (pocket)",
               "8.5x8.5": "8.5 x 8.5 in (square picture book)", "8x10": "8 x 10 in (picture book)",
               "legal": "Legal (8.5 x 14 in)"}

DOC_FIELDS = {          # field -> (label, kind, help)
    "page": ("Page size", "page", "Paper or book size. E-books ignore it."),
    "margins": ("Margins (inches)", "text", "One number for all sides, or four: top right bottom left."),
    "font": ("Body font", "text", "The font for the text. Several, separated by commas, = first one this PC has "
             "(PDF/EPUB); Word uses the first."),
    "heading_font": ("Heading font", "text", "The font for titles and headings."),
    "size": ("Text size (pt)", "number", "12 is usual; children's books 18-24."),
    "line": ("Line spacing", "number", "1 = single, 1.5, 2 = double."),
    "indent": ("First-line indent (inches)", "number", "Books indent each paragraph's first line; 0 = none."),
    "para_after": ("Space after paragraphs (pt)", "number", "0 for books (they use the indent instead)."),
    "align": ("Text alignment", "align", "Justified = straight right edge, like printed books."),
    "heading_center": ("Center the headings", "bool", ""),
    "chapter_break": ("Each chapter on a new page", "bool", "A new page at every top heading (# Chapter)."),
    "title_page": ("Title on its own page", "bool", "PDF and EPUB; Word keeps the title at the top."),
}
SHEET_FIELDS = {
    "font": ("Font", "text", ""),
    "size": ("Text size (pt)", "number", ""),
    "header_bold": ("Bold header row", "bool", ""),
    "header_fill": ("Header color", "text", "A color code like D9E1F2 (light blue). Blank = none."),
    "freeze_header": ("Header stays in place when scrolling", "bool", ""),
    "filters": ("Filter buttons on the header", "bool", ""),
    "banded": ("Striped rows", "bool", "Every other row lightly shaded, easier to read across."),
    "col_width": ("Column width", "text", "auto = fit the words (up to 60), or a number."),
}

TEMPLATES: dict[str, dict] = {
    "standard": {"label": "Everyday document", "for": "doc", "about": "Letters, notes, guides: easy to read on "
                 "screen and on paper.", "page": "letter", "margins": "1", "font": "Georgia, serif",
                 "heading_font": "Arial, sans-serif", "size": 12, "line": 1.4, "indent": 0, "para_after": 8,
                 "align": "left", "heading_center": False, "chapter_break": False, "title_page": False},
    "book": {"label": "Book (printed novel)", "for": "doc", "about": "A paperback page: serif type, indented "
             "paragraphs, straight edges, every chapter on a new page.", "page": "6x9",
             "margins": "0.75 0.6 0.75 0.75", "font": "Garamond, EB Garamond, Georgia, serif",
             "heading_font": "Garamond, EB Garamond, Georgia, serif", "size": 11.5, "line": 1.3, "indent": 0.3,
             "para_after": 0, "align": "justify", "heading_center": True, "chapter_break": True, "title_page": True},
    "manuscript": {"label": "Manuscript (for editors and agents)", "for": "doc", "about": "Standard manuscript "
                   "format: Times New Roman 12, double spaced, 1-inch margins, half-inch indents.",
                   "page": "letter", "margins": "1", "font": "Times New Roman, Times, serif",
                   "heading_font": "Times New Roman, Times, serif", "size": 12, "line": 2.0, "indent": 0.5,
                   "para_after": 0, "align": "left", "heading_center": True, "chapter_break": True,
                   "title_page": True},
    "kids": {"label": "Children's picture book", "for": "doc", "about": "Big, friendly, easy-to-read letters, "
             "centered, a new page for each part of the story.", "page": "8.5x8.5", "margins": "0.6",
             "font": "Andika, Atkinson Hyperlegible, Comic Neue, Verdana, sans-serif",
             "heading_font": "Andika, Atkinson Hyperlegible, Verdana, sans-serif", "size": 22, "line": 1.5,
             "indent": 0, "para_after": 14, "align": "center", "heading_center": True, "chapter_break": True,
             "title_page": True},
    "ebook": {"label": "E-book (EPUB)", "for": "doc", "about": "For e-readers: the reader's own settings win, "
              "so this stays light: serif text, indents, chapters on new pages.", "page": "letter",
              "margins": "0.5", "font": "Georgia, serif", "heading_font": "Georgia, serif", "size": 12,
              "line": 1.4, "indent": 0.25, "para_after": 0, "align": "left", "heading_center": True,
              "chapter_break": True, "title_page": True},
    "report": {"label": "Report / business", "for": "doc", "about": "Clean and modern: sans-serif, block "
               "paragraphs, room between them.", "page": "letter", "margins": "1",
               "font": "Calibri, Carlito, Arial, sans-serif", "heading_font": "Calibri Light, Calibri, Arial, sans-serif",
               "size": 11, "line": 1.15, "indent": 0, "para_after": 8, "align": "left", "heading_center": False,
               "chapter_break": False, "title_page": False},
    "sheet": {"label": "Spreadsheet (.xlsx)", "for": "sheet", "about": "Excel/LibreOffice copy of a .csv task: "
              "a bold colored header that stays in place, filter buttons, fitted columns.",
              "font": "Calibri", "size": 11, "header_bold": True, "header_fill": "D9E1F2", "freeze_header": True,
              "filters": True, "banded": False, "col_width": "auto"},
}
DEFAULTS = {"docx": "standard", "pdf": "standard", "html": "standard", "odt": "standard", "epub": "ebook",
            "xlsx": "sheet"}


# --------------------------------------------------------------------------- settings
def _store(settings) -> dict:
    t = getattr(settings, "templates", None)
    return t if isinstance(t, dict) else {}


def fields_of(tid: str) -> dict:
    return SHEET_FIELDS if TEMPLATES.get(tid, {}).get("for") == "sheet" else DOC_FIELDS


def _coerce(tid: str, k: str, v):
    kind = fields_of(tid)[k][1]
    if kind == "bool":
        return v in (True, "true", "on", "yes", 1, "1")
    if kind == "number":
        try:
            n = float(v)
        except (TypeError, ValueError):
            return TEMPLATES[tid][k]
        n = max(0.0, min(n, 96.0))
        return int(n) if n == int(n) else round(n, 2)
    if kind == "page":
        return v if v in PAGES else TEMPLATES[tid][k]
    if kind == "align":
        return v if v in ("left", "justify", "center") else TEMPLATES[tid][k]
    return " ".join(str(v or "").split())[:200] or TEMPLATES[tid][k]


def get(settings, tid: str) -> dict:
    """A template with your edits on top of Joe's."""
    tid = tid if tid in TEMPLATES else "standard"
    t = dict(TEMPLATES[tid])
    mine = (_store(settings).get("edits") or {}).get(tid) or {}
    for k in fields_of(tid):
        if k in mine:
            t[k] = _coerce(tid, k, mine[k])
    t["id"] = tid
    return t


def default_for(settings, fmt: str) -> str:
    d = (_store(settings).get("defaults") or {}).get(fmt) or DEFAULTS.get(fmt, "standard")
    return d if d in TEMPLATES else DEFAULTS.get(fmt, "standard")


def entries(settings) -> dict:
    rows = []
    for tid, base in TEMPLATES.items():
        t = get(settings, tid)
        rows.append({"id": tid, "label": base["label"], "about": base["about"], "for": base["for"],
                     "fields": [{"key": k, "label": lab, "kind": kind, "help": hlp, "value": t[k],
                                 "joe": base[k], "changed": t[k] != base[k]}
                                for k, (lab, kind, hlp) in fields_of(tid).items()]})
    return {"rows": rows, "pages": PAGE_LABELS,
            "defaults": {f: default_for(settings, f) for f in DEFAULTS}}


def save(settings, tid: str, values: dict | None) -> dict:
    """values None = reset this template to Joe's."""
    if tid not in TEMPLATES:
        return {"ok": False, "error": "Unknown template."}
    store = dict(_store(settings))
    edits = dict(store.get("edits") or {})
    keep = {}
    for k, v in (values or {}).items():
        if k in fields_of(tid):
            c = _coerce(tid, k, v)
            if c != TEMPLATES[tid][k]:
                keep[k] = c
    if keep:
        edits[tid] = keep
    else:
        edits.pop(tid, None)
    store["edits"] = edits
    settings.templates = store
    settings.save()
    return {"ok": True}


def save_defaults(settings, defaults: dict) -> dict:
    store = dict(_store(settings))
    d = {}
    for fmt, tid in (defaults or {}).items():
        if fmt in DEFAULTS and tid in TEMPLATES and TEMPLATES[tid]["for"] == ("sheet" if fmt == "xlsx" else "doc") \
                and tid != DEFAULTS[fmt]:
            d[fmt] = tid
    store["defaults"] = d
    settings.templates = store
    settings.save()
    return {"ok": True}


# --------------------------------------------------------------------------- CSS (PDF, HTML, EPUB)
def margins(t: dict) -> tuple[float, float, float, float]:
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(t.get("margins") or "1"))][:4] or [1.0]
    if len(nums) == 1:
        nums *= 4
    elif len(nums) == 2:
        nums = [nums[0], nums[1], nums[0], nums[1]]
    elif len(nums) == 3:
        nums = [nums[0], nums[1], nums[2], nums[1]]
    return tuple(min(4.0, n) for n in nums)          # type: ignore[return-value]


def _font_list(f: str) -> str:
    out = []
    for name in [x.strip().strip("'\"") for x in str(f).split(",") if x.strip()]:
        out.append(name if name in ("serif", "sans-serif", "monospace") else f'"{name}"')
    return ", ".join(out) or "serif"


def css(t: dict, epub: bool = False) -> str:
    top, right, bottom, left = margins(t)
    w, h = PAGES.get(t.get("page"), PAGES["letter"])
    head_align = "center" if t.get("heading_center") else "left"
    rules = []
    if not epub:
        rules.append(f"@page {{ size: {w}in {h}in; margin: {top}in {right}in {bottom}in {left}in; }}")
        rules.append("html, body { margin: 0 !important; padding: 0 !important; max-width: none !important; }")
    rules += [
        f"body {{ font-family: {_font_list(t['font'])}; font-size: {t['size']}pt; line-height: {t['line']}; "
        f"text-align: {t['align']}; hyphens: auto; color: #111; background: #fff; }}",
        f"p {{ margin: 0 0 {t['para_after']}pt 0; text-indent: {t['indent']}in; }}",
        "h1 + p, h2 + p, h3 + p, blockquote p, li p { text-indent: 0; }",
        f"h1, h2, h3, h4, .title, .subtitle {{ font-family: {_font_list(t['heading_font'])}; "
        f"text-align: {head_align}; line-height: 1.2; text-indent: 0; }}",
        f"h1 {{ font-size: {round(t['size'] * 1.8, 1)}pt; margin: 0.6em 0 0.8em; }}",
        f"h2 {{ font-size: {round(t['size'] * 1.4, 1)}pt; margin: 1em 0 0.5em; }}",
        f"h3 {{ font-size: {round(t['size'] * 1.15, 1)}pt; margin: 1em 0 0.4em; }}",
        "img { max-width: 100%; height: auto; } table { border-collapse: collapse; } "
        "td, th { border: 1px solid #999; padding: 3px 6px; text-indent: 0; }",
    ]
    if t.get("chapter_break"):
        rules.append("h1 { break-before: page; page-break-before: always; } "
                     "header + h1, #title-block-header + h1, body > h1:first-child { break-before: auto; "
                     "page-break-before: auto; }")
    if t.get("title_page"):
        rules.append("#title-block-header { break-after: page; page-break-after: always; text-align: center; "
                     "padding-top: 30vh; } #title-block-header .title { font-size: "
                     f"{round(t['size'] * 2.4, 1)}pt; }}")
        if t.get("chapter_break"):
            rules.append("#title-block-header + h1 { break-before: auto; page-break-before: auto; }")
    return "\n".join(rules) + "\n"


# --------------------------------------------------------------------------- Word reference document
def _first_font(f: str) -> str:
    for name in str(f).split(","):
        name = name.strip().strip("'\"")
        if name and name not in ("serif", "sans-serif", "monospace"):
            return name
    return "Georgia"


def _rfonts(name: str) -> str:
    n = escape(name, {'"': "&quot;"})
    return f'<w:rFonts w:ascii="{n}" w:hAnsi="{n}" w:eastAsia="{n}" w:cs="{n}"/>'


def _set_ppr(style_xml: str, ppr_inner: str) -> str:
    """Put ppr_inner's elements into a <w:style>'s <w:pPr> (replacing the same elements)."""
    tags = re.findall(r"<w:(\w+)\b", ppr_inner)
    m = re.search(r"<w:pPr>(.*?)</w:pPr>", style_xml, re.S)
    if m:
        body = m.group(1)
        for tag in tags:
            body = re.sub(rf"<w:{tag}\b[^>]*/>|<w:{tag}\b[^>]*>.*?</w:{tag}>", "", body, flags=re.S)
        return style_xml[:m.start(1)] + ppr_inner + body + style_xml[m.end(1):]
    at = re.search(r"<w:rPr>|</w:style>", style_xml)
    return style_xml[:at.start()] + f"<w:pPr>{ppr_inner}</w:pPr>" + style_xml[at.start():]


def _set_rpr(style_xml: str, rpr_inner: str) -> str:
    tags = re.findall(r"<w:(\w+)\b", rpr_inner)
    m = re.search(r"<w:rPr>(.*?)</w:rPr>", style_xml, re.S)
    if m:
        body = m.group(1)
        for tag in tags:
            body = re.sub(rf"<w:{tag}\b[^>]*/>", "", body)
        return style_xml[:m.start(1)] + rpr_inner + body + style_xml[m.end(1):]
    at = style_xml.rfind("</w:style>")
    return style_xml[:at] + f"<w:rPr>{rpr_inner}</w:rPr>" + style_xml[at:]


def _edit_style(styles: str, sid: str, fn) -> str:
    m = re.search(rf'<w:style\b[^>]*w:styleId="{sid}"[^>]*>.*?</w:style>', styles, re.S)
    return styles if not m else styles[:m.start()] + fn(m.group(0)) + styles[m.end():]


def docx_styles(styles: str, t: dict) -> str:
    """Pandoc's reference styles.xml with the template's choices written in."""
    body, head = _first_font(t["font"]), _first_font(t["heading_font"])
    sz = int(round(float(t["size"]) * 2))
    line = int(round(float(t["line"]) * 240))
    after = int(round(float(t["para_after"]) * 20))
    ind = int(round(float(t["indent"]) * 1440))
    jc = {"left": "left", "justify": "both", "center": "center"}[t["align"]]
    # defaults for every paragraph and run
    styles = re.sub(r"<w:rPrDefault>.*?</w:rPrDefault>",
                    f"<w:rPrDefault><w:rPr>{_rfonts(body)}<w:sz w:val=\"{sz}\"/><w:szCs w:val=\"{sz}\"/>"
                    "<w:lang w:val=\"en-US\"/></w:rPr></w:rPrDefault>", styles, count=1, flags=re.S)
    body_ppr = (f'<w:spacing w:before="0" w:after="{after}" w:line="{line}" w:lineRule="auto"/>'
                f'<w:ind w:firstLine="{ind}"/><w:jc w:val="{jc}"/>')
    for sid in ("BodyText", "FirstParagraph", "Normal"):
        styles = _edit_style(styles, sid, lambda x: _set_ppr(x, body_ppr))
    styles = _edit_style(styles, "FirstParagraph", lambda x: _set_ppr(x, '<w:ind w:firstLine="0"/>'))
    styles = _edit_style(styles, "Compact", lambda x: _set_ppr(
        x, f'<w:spacing w:before="0" w:after="0" w:line="{line}" w:lineRule="auto"/><w:ind w:firstLine="0"/>'))
    hj = "center" if t.get("heading_center") else "left"
    for n, mult in (("Title", 2.4), ("Subtitle", 1.5), ("Heading1", 1.8), ("Heading2", 1.4), ("Heading3", 1.15)):
        hs = int(round(float(t["size"]) * mult * 2))
        ppr = f'<w:jc w:val="{hj}"/><w:ind w:firstLine="0"/>'
        if n == "Heading1" and t.get("chapter_break"):
            ppr = "<w:pageBreakBefore/>" + ppr
        styles = _edit_style(styles, n, lambda x, ppr=ppr: _set_ppr(x, ppr))
        styles = _edit_style(styles, n, lambda x, hs=hs: _set_rpr(
            x, f'{_rfonts(head)}<w:color w:val="111111"/><w:sz w:val="{hs}"/><w:szCs w:val="{hs}"/>'))
    return styles


def docx_page(document: str, t: dict) -> str:
    w, h = PAGES.get(t.get("page"), PAGES["letter"])
    top, right, bottom, left = (int(round(x * 1440)) for x in margins(t))
    sect = (f'<w:sectPr><w:pgSz w:w="{int(round(w * 1440))}" w:h="{int(round(h * 1440))}"/>'
            f'<w:pgMar w:top="{top}" w:right="{right}" w:bottom="{bottom}" w:left="{left}" '
            'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>')
    document = re.sub(r"<w:sectPr\b[^>]*/>|<w:sectPr\b[^>]*>.*?</w:sectPr>", "", document, flags=re.S)
    return document.replace("</w:body>", sect + "</w:body>")


def reference_docx(pandoc: str, t: dict, cache: Path, log=print) -> Path | None:
    """A Word reference document for this template (made once per set of choices)."""
    import subprocess
    key = hashlib.sha1(json.dumps({k: t.get(k) for k in DOC_FIELDS}, sort_keys=True).encode()).hexdigest()[:10]
    out = cache / f"reference-{t.get('id', 'x')}-{key}.docx"
    if out.exists():
        return out
    cache.mkdir(parents=True, exist_ok=True)
    try:
        p = subprocess.run([pandoc, "--print-default-data-file", "reference.docx"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        log(f"  Word template: couldn't ask Pandoc for its reference document ({e}).")
        return None
    if p.returncode != 0 or not p.stdout:
        log("  Word template: Pandoc didn't give its reference document; using its plain look.")
        return None
    try:
        src = zipfile.ZipFile(io.BytesIO(p.stdout))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename == "word/styles.xml":
                    data = docx_styles(data.decode("utf-8"), t).encode("utf-8")
                elif item.filename == "word/document.xml":
                    data = docx_page(data.decode("utf-8"), t).encode("utf-8")
                z.writestr(item, data)
        out.write_bytes(buf.getvalue())
    except (zipfile.BadZipFile, KeyError, OSError, UnicodeDecodeError) as e:
        log(f"  Word template: couldn't make it ({e}); using Pandoc's plain look.")
        return None
    return out


# --------------------------------------------------------------------------- spreadsheets (.xlsx)
def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, v: str, style: int) -> str:
    v = (v or "").strip()
    if re.fullmatch(r"-?\d{1,15}(\.\d+)?", v) and not (len(v) > 1 and v.startswith("0") and "." not in v):
        return f'<c r="{ref}" s="{style}"><v>{v}</v></c>'
    clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", v)
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(clean)}</t></is></c>'


def write_xlsx(rows: list[list[str]], dest: Path, t: dict, sheet_name: str = "Sheet1") -> Path:
    """A real .xlsx (no extra libraries) from table rows; the first row is the header."""
    rows = [r for r in rows if any((c or "").strip() for c in r)] or [[""]]
    ncols = max(len(r) for r in rows)
    font, size = escape(_first_font(t.get("font") or "Calibri")), float(t.get("size") or 11)
    fill = re.sub(r"[^0-9A-Fa-f]", "", str(t.get("header_fill") or ""))[:6]
    fills = '<fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    fills += (f'<fill><patternFill patternType="solid"><fgColor rgb="FF{fill.upper()}"/></patternFill></fill>'
              if len(fill) == 6 else '<fill><patternFill patternType="none"/></fill>')
    fills += '<fill><patternFill patternType="solid"><fgColor rgb="FFF2F2F2"/></patternFill></fill>'
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              f'<fonts count="2"><font><sz val="{size:g}"/><name val="{font}"/></font>'
              f'<font><b/><sz val="{size:g}"/><name val="{font}"/></font></fonts>'
              f'<fills count="4">{fills}</fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0">'
              '<alignment vertical="top" wrapText="1"/></xf>'
              f'<xf numFmtId="0" fontId="{1 if t.get("header_bold") else 0}" fillId="2" borderId="0" xfId="0" '
              'applyFont="1" applyFill="1"><alignment vertical="top" wrapText="1"/></xf>'
              '<xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyFill="1">'
              '<alignment vertical="top" wrapText="1"/></xf></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    width = str(t.get("col_width") or "auto")
    cols = []
    for c in range(ncols):
        if width.replace(".", "", 1).isdigit():
            w = float(width)
        else:
            longest = max((len(r[c]) if c < len(r) else 0) for r in rows[:500])
            w = min(60, max(8, longest * 1.1 + 2))
        cols.append(f'<col min="{c + 1}" max="{c + 1}" width="{w:.1f}" customWidth="1"/>')
    data = []
    for i, r in enumerate(rows):
        st = 1 if i == 0 else (2 if t.get("banded") and i % 2 == 0 else 0)
        cells = "".join(_cell(f"{_col(c)}{i + 1}", r[c] if c < len(r) else "", st) for c in range(ncols))
        data.append(f'<row r="{i + 1}">{cells}</row>')
    last = f"{_col(ncols - 1)}{len(rows)}"
    view = ('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
            'state="frozen"/></sheetView></sheetViews>' if t.get("freeze_header") else "")
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             f'<dimension ref="A1:{last}"/>{view}<cols>{"".join(cols)}</cols>'
             f'<sheetData>{"".join(data)}</sheetData>'
             + (f'<autoFilter ref="A1:{last}"/>' if t.get("filters") and len(rows) > 1 else "")
             + '</worksheet>')
    name = escape(re.sub(r"[\[\]:*?/\\]", "", sheet_name)[:31] or "Sheet1", {'"': "&quot;"})
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          f'<sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets>'
          + (f'<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
             f"'{name}'!$A$1:${_col(ncols - 1)}${len(rows)}</definedName></definedNames>"
             if t.get("filters") and len(rows) > 1 else "")
          + '</workbook>')
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>',
        "xl/workbook.xml": wb, "xl/styles.xml": styles, "xl/worksheets/sheet1.xml": sheet,
    }
    tmp = dest.with_suffix(".xlsx.part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n, body in files.items():
            z.writestr(n, body)
    tmp.replace(dest)
    return dest


def csv_to_xlsx(src: Path, t: dict) -> Path:
    text = src.read_text(encoding="utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    return write_xlsx(rows, src.with_suffix(".xlsx"), t, src.stem)
