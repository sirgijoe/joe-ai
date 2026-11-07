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
         "5x8": (5, 8), "7x10": (7, 10), "8.5x8.5": (8.5, 8.5), "8x10": (8, 10), "legal": (8.5, 14),
         "5x7": (5, 7), "4x6": (4, 6)}
PAGE_LABELS = {"letter": "Letter (8.5 x 11 in)", "a4": "A4", "a5": "A5", "6x9": "6 x 9 in (paperback)",
               "5.5x8.5": "5.5 x 8.5 in (digest)", "5x8": "5 x 8 in (pocket)", "7x10": "7 x 10 in (cookbook, workbook)",
               "8.5x8.5": "8.5 x 8.5 in (square picture book)", "8x10": "8 x 10 in (picture book)",
               "legal": "Legal (8.5 x 14 in)", "5x7": "5 x 7 in (recipe card)", "4x6": "4 x 6 in (index card)"}
NUMBERS = {"none": "No page numbers", "bottom-center": "Bottom, middle", "bottom-outside": "Bottom, outside corner",
           "top-right": "Top right (with the header text)"}

DOC_FIELDS = {          # field -> (label, kind, help[, choices])
    "page": ("Page size", "page", "Paper or book size. E-books ignore it."),
    "margins": ("Margins (inches)", "text", "One number for all sides, or four: top right bottom left."),
    "gutter": ("Extra inside margin for binding (inches)", "number", "Printed books: room for the spine. 0 = none."),
    "mirror": ("Mirror margins (left and right pages)", "bool", "Printed books: the inside edge swaps sides on "
               "facing pages."),
    "font": ("Body font", "text", "The font for the text. Several, separated by commas, = first one this PC has "
             "(PDF/EPUB); Word uses the first."),
    "heading_font": ("Heading font", "text", "The font for titles and headings."),
    "size": ("Text size (pt)", "number", "12 is usual; large print 16-18; children's books 18-24."),
    "line": ("Line spacing", "number", "1 = single, 1.5, 2 = double."),
    "indent": ("First-line indent (inches)", "number", "Books indent each paragraph's first line; 0 = none."),
    "para_after": ("Space after paragraphs (pt)", "number", "0 for books (they use the indent instead)."),
    "align": ("Text alignment", "align", "Justified = straight right edge, like printed books."),
    "heading_center": ("Center the headings", "bool", ""),
    "heading_rule": ("Line under section headings", "bool", "Resumes and reports: a thin line under each ## heading."),
    "chapter_break": ("New page at headings", "bool", "Start a new page at headings of the level below."),
    "break_level": ("...at which headings", "choice", "# = chapters only; ## = also each section (one poem, "
                    "recipe or picture per page).", {"1": "# Chapters", "2": "## Sections too"}),
    "show_title": ("Print the title", "bool", "Off for letters and resumes (they start with your own heading)."),
    "title_page": ("Title on its own page", "bool", "Word copies keep the title at the top of page 1."),
    "page_numbers": ("Page numbers", "choice", "Not on the title page.", NUMBERS),
    "header": ("Header text at the top", "text", "Shown on every page. {title} = the document's title. "
               "School papers: your last name. Blank = none."),
    "drop_cap": ("Big first letter in each chapter", "bool", "PDF, web page and EPUB."),
    "line_breaks": ("Keep line breaks as written", "bool", "Poems and song-like text: every line stays its own line."),
    "screenplay": ("Screenplay layout", "bool", "Scene headings (INT./EXT.), character names, dialogue, "
                   "parentheticals and transitions placed where scripts put them."),
    "big_pictures": ("Pictures fill the page", "bool", "Coloring and picture books: each picture as big as fits."),
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
    "money": ("Money columns", "text", "auto = columns named price, cost, total, amount, fee... Or the column "
              "names, separated by commas. Blank = none. Shown as $1,234.50."),
    "currency": ("Money sign", "text", "$, \u20ac, \u00a3... (blank = none)"),
    "totals": ("Totals row at the bottom", "bool", "Adds up each money column (a real formula)."),
}

_DOC_DEFAULTS = {"gutter": 0, "mirror": False, "heading_rule": False, "break_level": "1", "show_title": True,
                 "page_numbers": "none", "header": "", "drop_cap": False, "line_breaks": False,
                 "screenplay": False, "big_pictures": False}
_SHEET_DEFAULTS = {"money": "", "currency": "$", "totals": False}


def _doc(**kw) -> dict:
    return {"for": "doc", **_DOC_DEFAULTS, **kw}


def _sheet(**kw) -> dict:
    return {"for": "sheet", **_SHEET_DEFAULTS, **kw}


SERIF_BOOK = "Garamond, EB Garamond, Georgia, serif"
TEMPLATES: dict[str, dict] = {
    "standard": _doc(label="Everyday document", about="Letters, notes, guides: easy to read on screen and on paper.",
                     page="letter", margins="1", font="Georgia, serif", heading_font="Arial, sans-serif", size=12,
                     line=1.4, indent=0, para_after=8, align="left", heading_center=False, chapter_break=False,
                     title_page=False),
    "book": _doc(label="Book (printed novel)", about="A paperback page: serif type, indented paragraphs, straight "
                 "edges, room for the spine, page numbers, every chapter on a new page with a big first letter.",
                 page="6x9", margins="0.75 0.6 0.75 0.6", gutter=0.15, mirror=True, font=SERIF_BOOK,
                 heading_font=SERIF_BOOK, size=11.5, line=1.3, indent=0.3, para_after=0, align="justify",
                 heading_center=True, chapter_break=True, title_page=True, page_numbers="bottom-outside",
                 drop_cap=True),
    "manuscript": _doc(label="Manuscript (for editors and agents)", about="Standard manuscript format: Times New "
                       "Roman 12, double spaced, 1-inch margins, half-inch indents, title and page number on top.",
                       page="letter", margins="1", font="Times New Roman, Times, serif",
                       heading_font="Times New Roman, Times, serif", size=12, line=2.0, indent=0.5, para_after=0,
                       align="left", heading_center=True, chapter_break=True, title_page=True,
                       page_numbers="top-right", header="{title}"),
    "kids": _doc(label="Children's picture book", about="Big, friendly, easy-to-read letters, centered, a new "
                 "page for each part of the story, pictures as big as fit.", page="8.5x8.5", margins="0.6",
                 font="Andika, Atkinson Hyperlegible, Comic Neue, Verdana, sans-serif",
                 heading_font="Andika, Atkinson Hyperlegible, Verdana, sans-serif", size=22, line=1.5, indent=0,
                 para_after=14, align="center", heading_center=True, chapter_break=True, break_level="2",
                 title_page=True, big_pictures=True),
    "ebook": _doc(label="E-book (EPUB)", about="For e-readers: the reader's own settings win, so this stays light: "
                  "serif text, indents, chapters on new pages.", page="letter", margins="0.5", font="Georgia, serif",
                  heading_font="Georgia, serif", size=12, line=1.4, indent=0.25, para_after=0, align="left",
                  heading_center=True, chapter_break=True, title_page=True, drop_cap=True),
    "report": _doc(label="Report / business", about="Clean and modern: sans-serif, block paragraphs, room between "
                   "them, a line under section headings, page numbers.", page="letter", margins="1",
                   font="Calibri, Carlito, Arial, sans-serif", heading_font="Calibri Light, Calibri, Arial, sans-serif",
                   size=11, line=1.15, indent=0, para_after=8, align="left", heading_center=False,
                   chapter_break=False, title_page=False, heading_rule=True, page_numbers="bottom-center"),
    "largeprint": _doc(label="Large print", about="For older readers and anyone with low vision: big, very clear "
                       "letters (Atkinson Hyperlegible), wide spacing, nothing squeezed.", page="letter",
                       margins="1", font="Atkinson Hyperlegible, Verdana, Arial, sans-serif",
                       heading_font="Atkinson Hyperlegible, Verdana, Arial, sans-serif", size=18, line=1.5,
                       indent=0, para_after=14, align="left", heading_center=False, chapter_break=True,
                       title_page=True, page_numbers="bottom-center"),
    "poetry": _doc(label="Poetry / chapbook", about="Every line kept as written, no indents, one poem per page in "
                   "a small book size.", page="5.5x8.5", margins="0.8 0.7 0.8 0.7", gutter=0.1, mirror=True,
                   font=SERIF_BOOK, heading_font=SERIF_BOOK, size=11.5, line=1.35, indent=0, para_after=10,
                   align="left", heading_center=False, chapter_break=True, break_level="2", title_page=True,
                   page_numbers="bottom-center", line_breaks=True),
    "screenplay": _doc(label="Screenplay", about="Script format: Courier 12, wide left margin, INT./EXT. scene "
                       "headings, character names and dialogue set in, transitions on the right, page numbers "
                       "top right.", page="letter", margins="1 1 1 1.5",
                       font="Courier Prime, Courier New, Courier, monospace",
                       heading_font="Courier Prime, Courier New, Courier, monospace", size=12, line=1.0, indent=0,
                       para_after=12, align="left", heading_center=True, chapter_break=False, title_page=True,
                       page_numbers="top-right", screenplay=True),
    "letter": _doc(label="Letter / cover letter", about="A business letter: no printed title, block paragraphs "
                   "with space between, comfortable margins.", page="letter", margins="1",
                   font="Calibri, Carlito, Georgia, sans-serif", heading_font="Calibri, Carlito, Georgia, sans-serif",
                   size=11.5, line=1.15, indent=0, para_after=10, align="left", heading_center=False,
                   chapter_break=False, title_page=False, show_title=False),
    "resume": _doc(label="Resume", about="Compact and tidy: small margins, tight spacing, a line under each "
                   "section heading, no printed title (your name is the first heading).", page="letter",
                   margins="0.7", font="Calibri, Carlito, Arial, sans-serif",
                   heading_font="Calibri, Carlito, Arial, sans-serif", size=10.5, line=1.1, indent=0, para_after=4,
                   align="left", heading_center=False, chapter_break=False, title_page=False, show_title=False,
                   heading_rule=True),
    "cookbook": _doc(label="Cookbook", about="Each recipe on its own page, clear lists for ingredients and steps, "
                     "pictures big.", page="7x10", margins="0.75", gutter=0.15, mirror=True, font="Georgia, serif",
                     heading_font="Georgia, serif", size=12, line=1.35, indent=0, para_after=8, align="left",
                     heading_center=False, chapter_break=True, break_level="2", title_page=True,
                     page_numbers="bottom-outside", heading_rule=True, big_pictures=True),
    "recipecard": _doc(label="Recipe card (5 x 7)", about="One recipe per card: small page, small margins, "
                       "compact text. Change the page size to 4 x 6 for index cards.", page="5x7", margins="0.4",
                       font="Georgia, serif", heading_font="Georgia, serif", size=10, line=1.2, indent=0,
                       para_after=4, align="left", heading_center=True, chapter_break=True, break_level="2",
                       title_page=False, show_title=False, heading_rule=True),
    "coloring": _doc(label="Coloring / activity book", about="One big picture per page with a small caption, "
                     "plain pages that print well.", page="letter", margins="0.5",
                     font="Atkinson Hyperlegible, Verdana, sans-serif",
                     heading_font="Atkinson Hyperlegible, Verdana, sans-serif", size=14, line=1.3, indent=0,
                     para_after=6, align="center", heading_center=True, chapter_break=True, break_level="2",
                     title_page=True, big_pictures=True),
    "school": _doc(label="School paper (MLA)", about="MLA style: Times New Roman 12, double spaced, 1-inch margins, "
                   "half-inch indents, last name and page number top right. Put your last name in Header text.",
                   page="letter", margins="1", font="Times New Roman, Times, serif",
                   heading_font="Times New Roman, Times, serif", size=12, line=2.0, indent=0.5, para_after=0,
                   align="left", heading_center=True, chapter_break=False, title_page=False,
                   page_numbers="top-right", header="Lastname"),
    "sheet": _sheet(label="Spreadsheet (.xlsx)", about="Excel/LibreOffice copy of a .csv task: a bold colored header "
                    "that stays in place, filter buttons, fitted columns.", font="Calibri", size=11,
                    header_bold=True, header_fill="D9E1F2", freeze_header=True, filters=True, banded=False,
                    col_width="auto"),
    "pricelist": _sheet(label="Price list / inventory (.xlsx)", about="Money columns shown as $1,234.50, a totals "
                        "row that adds them up, striped rows, room for long product names.", font="Calibri",
                        size=11, header_bold=True, header_fill="E2EFDA", freeze_header=True, filters=True,
                        banded=True, col_width="auto", money="auto", currency="$", totals=True),
}
DEFAULTS = {"docx": "standard", "pdf": "standard", "html": "standard", "odt": "standard", "epub": "ebook",
            "xlsx": "sheet"}
ALIASES = {"novel": "book", "children": "kids", "childrens-book": "kids", "picture-book": "kids", "epub": "ebook",
           "e-book": "ebook", "business": "report", "default": "standard", "spreadsheet": "sheet", "excel": "sheet",
           "large-print": "largeprint", "large": "largeprint", "poems": "poetry", "poem": "poetry",
           "chapbook": "poetry", "script": "screenplay", "movie-script": "screenplay", "cover-letter": "letter",
           "cv": "resume", "résumé": "resume", "recipes": "cookbook", "recipe-card": "recipecard",
           "index-card": "recipecard", "coloring-book": "coloring", "activity-book": "coloring", "mla": "school",
           "essay": "school", "school-paper": "school", "price-list": "pricelist", "inventory": "pricelist",
           "prices": "pricelist"}


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
    if kind == "choice":
        v = str(v)
        return v if v in fields_of(tid)[k][3] else TEMPLATES[tid][k]
    if k in ("header", "money", "currency"):                  # may be blank on purpose
        return " ".join(str(v or "").split())[:80]
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
                     "fields": [{"key": k, "label": f[0], "kind": f[1], "help": f[2], "value": t[k],
                                 "choices": f[3] if len(f) > 3 else None,
                                 "joe": base[k], "changed": t[k] != base[k]}
                                for k, f in fields_of(tid).items()]})
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


def _css_str(text: str) -> str:
    return '"' + re.sub(r'["\\\n]', " ", text) + '"'


def header_text(t: dict, title: str = "") -> str:
    return str(t.get("header") or "").replace("{title}", title or "").strip()


def css(t: dict, epub: bool = False, title: str = "") -> str:
    top, right, bottom, left = margins(t)
    w, h = PAGES.get(t.get("page"), PAGES["letter"])
    gut = float(t.get("gutter") or 0)
    head_align = "center" if t.get("heading_center") else "left"
    lvl = "h2" if str(t.get("break_level")) == "2" else "h1"
    rules = []
    if not epub:
        if t.get("mirror") or gut:
            rules.append(f"@page {{ size: {w}in {h}in; margin: {top}in {right}in {bottom}in {left + gut}in; }}")
            if t.get("mirror"):
                rules.append(f"@page :left {{ margin-left: {right}in; margin-right: {left + gut}in; }}")
                rules.append(f"@page :right {{ margin-left: {left + gut}in; margin-right: {right}in; }}")
        else:
            rules.append(f"@page {{ size: {w}in {h}in; margin: {top}in {right}in {bottom}in {left}in; }}")
        num, head = t.get("page_numbers") or "none", header_text(t, title)
        box = "font-family: " + _font_list(t["font"]) + f"; font-size: {min(float(t['size']), 12):g}pt; color: #333;"
        if num == "top-right":
            rules.append(f"@page {{ @top-right {{ content: {_css_str(head + ' ') if head else ''} counter(page); {box} }} }}")
        else:
            if head:
                rules.append(f"@page {{ @top-center {{ content: {_css_str(head)}; {box} }} }}")
            if num == "bottom-center":
                rules.append(f"@page {{ @bottom-center {{ content: counter(page); {box} }} }}")
            elif num == "bottom-outside":
                rules.append(f"@page :left {{ @bottom-left {{ content: counter(page); {box} }} }}")
                rules.append(f"@page :right {{ @bottom-right {{ content: counter(page); {box} }} }}")
                if not t.get("mirror"):
                    rules.append(f"@page {{ @bottom-right {{ content: counter(page); {box} }} }}")
        if (num != "none" or head) and t.get("title_page") and t.get("show_title", True):
            rules.append("@page :first { @top-right { content: none; } @top-center { content: none; } "
                         "@bottom-center { content: none; } @bottom-left { content: none; } "
                         "@bottom-right { content: none; } }")
        rules.append("html, body { margin: 0 !important; padding: 0 !important; max-width: none !important; }")
    rules += [
        f"body {{ font-family: {_font_list(t['font'])}; font-size: {t['size']}pt; line-height: {t['line']}; "
        f"text-align: {t['align']}; hyphens: auto; color: #111; background: #fff; }}",
        f"p {{ margin: 0 0 {t['para_after']}pt 0; text-indent: {t['indent']}in; }}",
        "h1 + p, h2 + p, h3 + p, blockquote p, li p, figure p { text-indent: 0; }",
        f"h1, h2, h3, h4, .title, .subtitle {{ font-family: {_font_list(t['heading_font'])}; "
        f"text-align: {head_align}; line-height: 1.2; text-indent: 0; }}",
        f"h1 {{ font-size: {round(t['size'] * 1.8, 1)}pt; margin: 0.6em 0 0.8em; }}",
        f"h2 {{ font-size: {round(t['size'] * 1.4, 1)}pt; margin: 1em 0 0.5em; }}",
        f"h3 {{ font-size: {round(t['size'] * 1.15, 1)}pt; margin: 1em 0 0.4em; }}",
        "img { max-width: 100%; height: auto; } table { border-collapse: collapse; } "
        "td, th { border: 1px solid #999; padding: 3px 6px; text-indent: 0; }",
    ]
    if t.get("heading_rule"):
        rules.append("h2 { border-bottom: 1px solid #555; padding-bottom: 2pt; }")
    if not t.get("show_title", True):
        rules.append("#title-block-header { display: none; }")
    if t.get("chapter_break"):
        sel = "h1, h2" if lvl == "h2" else "h1"
        rules.append(f"{sel} {{ break-before: page; page-break-before: always; }} "
                     "h1 + h2, body > h1:first-child, body > h2:first-child, #title-block-header + h1, "
                     "#title-block-header + h2 { break-before: auto; page-break-before: auto; }")
    if t.get("title_page") and t.get("show_title", True):
        rules.append("#title-block-header { break-after: page; page-break-after: always; text-align: center; "
                     "padding-top: 30vh; } #title-block-header .title { font-size: "
                     f"{round(t['size'] * 2.4, 1)}pt; }}")
    if t.get("drop_cap"):
        rules.append(f"h1 + p::first-letter, #title-block-header + p::first-letter {{ float: left; font-size: 3.4em; "
                     f"line-height: 0.85; padding: 0.06em 0.08em 0 0; font-family: {_font_list(t['heading_font'])}; }}")
    if t.get("big_pictures"):
        rules.append(f"img {{ display: block; margin: 0 auto 6pt; max-width: 100%; max-height: {max(1.0, h - top - bottom - 1.2):.1f}in; "
                     "width: auto; object-fit: contain; } figure { margin: 0; text-align: center; } "
                     "figcaption { font-size: 0.9em; }")
    if t.get("screenplay"):
        rules.append("p { text-indent: 0; } .scene { font-weight: bold; text-transform: uppercase; margin-top: 12pt; } "
                     ".character { margin: 12pt 0 0 2.2in; text-transform: uppercase; } "
                     ".parenthetical { margin: 0 0 0 1.6in; } .dialogue { margin: 0 1.5in 0 1in; } "
                     ".transition { text-align: right; text-transform: uppercase; margin-top: 12pt; } "
                     ".character p, .parenthetical p, .dialogue p { margin: 0; }")
    return "\n".join(rules) + "\n"


# --------------------------------------------------------------------------- screenplay layout
_SCENE = re.compile(r"^\s*(\.|(INT|EXT|INT\.?/EXT|I/E|EST)[\. ])", re.I)
_TRANSITION = re.compile(r"^\s*[A-Z][A-Z .'-]*(TO:|OUT\.|IN:)\s*$")


def _caps(line: str) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", re.sub(r"\(.*?\)", "", line))
    return bool(letters) and letters.isupper() and len(line.strip()) <= 40


def screenplay_md(text: str) -> str:
    """Plain script text -> Markdown with marked parts (fenced divs), so the same layout comes out
    in Word (custom styles), PDF, EPUB and web pages. Headings (#) and title lines are kept."""
    out: list[str] = []

    def div(kind: str, style: str, lines: list[str]) -> None:
        body = "\\\n".join(x.strip().replace("*", "\\*") for x in lines)
        out.extend([f'::: {{.{kind} custom-style="{style}"}}', body, ":::", ""])

    blocks = re.split(r"\n\s*\n", text.replace("\r", "").strip())
    for blk in blocks:
        lines = [x for x in blk.split("\n") if x.strip()]
        if not lines:
            continue
        first = lines[0].strip()
        if first.startswith("#") or first.startswith(":::"):
            out.extend(lines + [""])
            continue
        if _SCENE.match(first) and _caps(first.lstrip(".")):
            div("scene", "Scene Heading", [first.lstrip(".") if first.startswith(".") else first])
            rest = lines[1:]
            if rest:
                div("action", "Action", rest)
            continue
        if _TRANSITION.match(first) and len(lines) == 1:
            div("transition", "Transition", [first])
            continue
        if _caps(first) and len(lines) > 1:
            div("character", "Character", [first])
            cur: list[str] = []
            for ln in lines[1:]:
                if ln.strip().startswith("(") and ln.strip().endswith(")"):
                    if cur:
                        div("dialogue", "Dialogue", cur)
                        cur = []
                    div("parenthetical", "Parenthetical", [ln])
                else:
                    cur.append(ln)
            if cur:
                div("dialogue", "Dialogue", cur)
            continue
        div("action", "Action", lines)
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------- Word reference document
def _first_font(f: str) -> str:
    for name in str(f).split(","):
        name = name.strip().strip("'\"")
        if name and name not in ("serif", "sans-serif", "monospace"):
            return name
    return "Georgia"


# Fonts nearly every Windows/Mac PC (or Microsoft Office) has: Word copies use the first of these
# in a template's list, so the file looks right on other people's computers too.
WORD_SAFE = ("Georgia", "Times New Roman", "Arial", "Verdana", "Calibri", "Calibri Light", "Cambria",
             "Courier New", "Garamond", "Segoe UI", "Trebuchet MS", "Palatino Linotype", "Book Antiqua",
             "Comic Sans MS", "Tahoma", "Century Gothic")


def word_font(f: str) -> str:
    names = [n.strip().strip("'\"") for n in str(f).split(",") if n.strip()]
    return next((n for n in names if n in WORD_SAFE), _first_font(f))


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


def _para_style(sid: str, name: str, ppr: str, rpr: str = "") -> str:
    return (f'<w:style w:type="paragraph" w:customStyle="1" w:styleId="{sid}"><w:name w:val="{name}"/>'
            f'<w:basedOn w:val="BodyText"/><w:qFormat/><w:pPr>{ppr}</w:pPr>'
            + (f"<w:rPr>{rpr}</w:rPr>" if rpr else "") + "</w:style>")


def docx_styles(styles: str, t: dict) -> str:
    """Pandoc's reference styles.xml with the template's choices written in."""
    body, head = word_font(t["font"]), word_font(t["heading_font"])
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
    brk = ("Heading1", "Heading2") if str(t.get("break_level")) == "2" else ("Heading1",)
    for n, mult in (("Title", 2.4), ("Subtitle", 1.5), ("Heading1", 1.8), ("Heading2", 1.4), ("Heading3", 1.15)):
        hs = int(round(float(t["size"]) * mult * 2))
        ppr = f'<w:jc w:val="{hj}"/><w:ind w:firstLine="0"/>'
        if n in brk and t.get("chapter_break"):
            ppr = "<w:pageBreakBefore/>" + ppr
        if n == "Heading2" and t.get("heading_rule"):
            ppr += '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="555555"/></w:pBdr>'
        styles = _edit_style(styles, n, lambda x, ppr=ppr: _set_ppr(x, ppr))
        styles = _edit_style(styles, n, lambda x, hs=hs: _set_rpr(
            x, f'{_rfonts(head)}<w:color w:val="111111"/><w:sz w:val="{hs}"/><w:szCs w:val="{hs}"/>'))
    if t.get("screenplay"):                        # the parts screenplay_md() marks (pandoc custom-style)
        sp = '<w:spacing w:before="240" w:after="0" w:line="240" w:lineRule="auto"/>'
        tight = '<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
        extra = (_para_style("SceneHeading", "Scene Heading", sp + '<w:ind w:firstLine="0"/><w:keepNext/>',
                             "<w:b/><w:caps/>")
                 + _para_style("Action", "Action", sp + '<w:ind w:firstLine="0"/>')
                 + _para_style("Character", "Character", sp + '<w:ind w:left="3168" w:firstLine="0"/><w:keepNext/>',
                               "<w:caps/>")
                 + _para_style("Parenthetical", "Parenthetical", tight + '<w:ind w:left="2304" w:right="2880" '
                               'w:firstLine="0"/><w:keepNext/>')
                 + _para_style("Dialogue", "Dialogue", tight + '<w:ind w:left="1440" w:right="2160" w:firstLine="0"/>')
                 + _para_style("Transition", "Transition", sp + '<w:jc w:val="right"/><w:ind w:firstLine="0"/>',
                               "<w:caps/>"))
        styles = styles.replace("</w:styles>", extra + "</w:styles>")
    return styles


def docx_page(document: str, t: dict, header_id: str = "", footer_id: str = "") -> str:
    w, h = PAGES.get(t.get("page"), PAGES["letter"])
    top, right, bottom, left = (int(round(x * 1440)) for x in margins(t))
    gut = int(round(float(t.get("gutter") or 0) * 1440))
    refs = ""
    if header_id:
        refs += f'<w:headerReference w:type="default" r:id="{header_id}"/>'
    if footer_id:
        refs += f'<w:footerReference w:type="default" r:id="{footer_id}"/>'
    sect = (f'<w:sectPr>{refs}<w:pgSz w:w="{int(round(w * 1440))}" w:h="{int(round(h * 1440))}"/>'
            f'<w:pgMar w:top="{top}" w:right="{right}" w:bottom="{bottom}" w:left="{left}" '
            f'w:header="{min(720, top // 2)}" w:footer="{min(720, bottom // 2)}" w:gutter="{gut}"/>'
            + ("<w:titlePg/>" if refs and t.get("title_page") and t.get("show_title", True) else "")
            + "</w:sectPr>")
    document = re.sub(r"<w:sectPr\b[^>]*/>|<w:sectPr\b[^>]*>.*?</w:sectPr>", "", document, flags=re.S)
    if refs and 'xmlns:r="' not in document[:2000]:
        document = document.replace("<w:document ", '<w:document xmlns:r="http://schemas.openxmlformats.org/'
                                    'officeDocument/2006/relationships" ', 1)
    return document.replace("</w:body>", sect + "</w:body>")


_W = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
_PAGE_FIELD = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
               '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>')


def _hf(tag: str, jc: str, text: str, page: bool) -> str:
    runs = (f'<w:r><w:t xml:space="preserve">{escape(text)} </w:t></w:r>' if text else "") + (_PAGE_FIELD if page else "")
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:{tag} {_W}><w:p><w:pPr><w:pStyle w:val="'
            f'{"Header" if tag == "hdr" else "Footer"}"/><w:jc w:val="{jc}"/></w:pPr>{runs}</w:p></w:{tag}>')


def docx_parts(t: dict, title: str = "") -> dict:
    """Header / footer parts for page numbers and the header text: {'header': xml, 'footer': xml}."""
    num, head = t.get("page_numbers") or "none", header_text(t, title)
    out = {}
    if num == "top-right":
        out["header"] = _hf("hdr", "right", head, True)
    elif head:
        out["header"] = _hf("hdr", "center", head, False)
    if num == "bottom-center":
        out["footer"] = _hf("ftr", "center", "", True)
    elif num == "bottom-outside":
        out["footer"] = _hf("ftr", "right", "", True)        # Word: outside on odd pages (see mirror below)
    return out


def reference_docx(pandoc: str, t: dict, cache: Path, log=print, title: str = "") -> Path | None:
    """A Word reference document for this template (made once per set of choices)."""
    import subprocess
    parts = docx_parts(t, title)
    key = hashlib.sha1(json.dumps({**{k: t.get(k) for k in DOC_FIELDS}, "_p": parts}, sort_keys=True)
                       .encode()).hexdigest()[:10]
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
        names = set(src.namelist())
        hid = "rIdJoeHeader" if "header" in parts else ""
        fid = "rIdJoeFooter" if "footer" in parts else ""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename == "word/styles.xml":
                    data = docx_styles(data.decode("utf-8"), t).encode("utf-8")
                elif item.filename == "word/document.xml":
                    data = docx_page(data.decode("utf-8"), t, hid, fid).encode("utf-8")
                elif item.filename == "word/_rels/document.xml.rels" and (hid or fid):
                    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
                    add = (f'<Relationship Id="{hid}" Type="{rel}header" Target="joeheader1.xml"/>' if hid else "") + \
                          (f'<Relationship Id="{fid}" Type="{rel}footer" Target="joefooter1.xml"/>' if fid else "")
                    data = data.decode("utf-8").replace("</Relationships>", add + "</Relationships>").encode("utf-8")
                elif item.filename == "[Content_Types].xml" and (hid or fid):
                    ct = "application/vnd.openxmlformats-officedocument.wordprocessingml."
                    add = (f'<Override PartName="/word/joeheader1.xml" ContentType="{ct}header+xml"/>' if hid else "") + \
                          (f'<Override PartName="/word/joefooter1.xml" ContentType="{ct}footer+xml"/>' if fid else "")
                    data = data.decode("utf-8").replace("</Types>", add + "</Types>").encode("utf-8")
                elif item.filename == "word/settings.xml" and t.get("mirror"):
                    data = re.sub(r"(<w:settings\b[^>]*>)", r"\1<w:mirrorMargins/>", data.decode("utf-8"),
                                  count=1).encode("utf-8")
                z.writestr(item, data)
            if hid:
                z.writestr("word/joeheader1.xml", parts["header"])
            if fid:
                z.writestr("word/joefooter1.xml", parts["footer"])
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


MONEY_WORDS = re.compile(r"price|cost|total|amount|fee|subtotal|value|msrp|wholesale|retail|revenue|sales|"
                         r"income|expense|budget|paid|due|balance|\$|\u20ac|\u00a3", re.I)


def money_columns(header: list[str], setting: str) -> set[int]:
    setting = (setting or "").strip()
    if not setting:
        return set()
    if setting.lower() == "auto":
        return {i for i, h in enumerate(header) if MONEY_WORDS.search(h or "")}
    want = {x.strip().lower() for x in setting.split(",") if x.strip()}
    return {i for i, h in enumerate(header) if (h or "").strip().lower() in want}


def money_value(v: str) -> str | None:
    """'$1,234.50' / '12' / '-3.5' -> '1234.50' ...; None when it isn't an amount."""
    x = re.sub(r"[\s$\u20ac\u00a3,]|USD|EUR|GBP", "", v or "")
    return x if re.fullmatch(r"-?\d{1,13}(\.\d{1,4})?", x) else None


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
    cur = escape(str(t.get("currency") or "").replace('"', "")[:4])
    fmt = (f'&quot;{cur}&quot;#,##0.00' if cur else "#,##0.00")
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              f'<numFmts count="1"><numFmt numFmtId="164" formatCode="{fmt}"/></numFmts>'
              f'<fonts count="2"><font><sz val="{size:g}"/><name val="{font}"/></font>'
              f'<font><b/><sz val="{size:g}"/><name val="{font}"/></font></fonts>'
              f'<fills count="4">{fills}</fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="7"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0">'
              '<alignment vertical="top" wrapText="1"/></xf>'
              f'<xf numFmtId="0" fontId="{1 if t.get("header_bold") else 0}" fillId="2" borderId="0" xfId="0" '
              'applyFont="1" applyFill="1"><alignment vertical="top" wrapText="1"/></xf>'
              '<xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyFill="1">'
              '<alignment vertical="top" wrapText="1"/></xf>'
              '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
              '<xf numFmtId="164" fontId="0" fillId="3" borderId="0" xfId="0" applyNumberFormat="1" applyFill="1"/>'
              '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
              '<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>'
              '</cellXfs>'
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
    money = money_columns(rows[0], str(t.get("money") or "")) if len(rows) > 1 else set()
    data = []
    for i, r in enumerate(rows):
        band = bool(t.get("banded") and i % 2 == 0)
        st = 1 if i == 0 else (2 if band else 0)
        cells = []
        for c in range(ncols):
            v, ref = r[c] if c < len(r) else "", f"{_col(c)}{i + 1}"
            mv = money_value(v) if i and c in money else None
            cells.append(f'<c r="{ref}" s="{4 if band else 3}"><v>{mv}</v></c>' if mv is not None
                         else _cell(ref, v, st))
        data.append(f'<row r="{i + 1}">{"".join(cells)}</row>')
    nrows = len(rows)
    if t.get("totals") and money and len(rows) > 1:
        label_col = next((c for c in range(ncols) if c not in money), None)
        cells = []
        for c in range(ncols):
            ref = f"{_col(c)}{nrows + 1}"
            if c in money:
                cells.append(f'<c r="{ref}" s="6"><f>SUM({_col(c)}2:{_col(c)}{nrows})</f></c>')
            elif c == label_col:
                cells.append(f'<c r="{ref}" s="5" t="inlineStr"><is><t>Total</t></is></c>')
        data.append(f'<row r="{nrows + 1}">{"".join(cells)}</row>')
    last = f"{_col(ncols - 1)}{len(data)}"
    filt = f"{_col(ncols - 1)}{nrows}"
    view = ('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
            'state="frozen"/></sheetView></sheetViews>' if t.get("freeze_header") else "")
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             f'<dimension ref="A1:{last}"/>{view}<cols>{"".join(cols)}</cols>'
             f'<sheetData>{"".join(data)}</sheetData>'
             + (f'<autoFilter ref="A1:{filt}"/>' if t.get("filters") and len(rows) > 1 else "")
             + '</worksheet>')
    name = escape(re.sub(r"[\[\]:*?/\\]", "", sheet_name)[:31] or "Sheet1", {'"': "&quot;"})
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          f'<sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets>'
          + (f'<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
             f"'{name}'!$A$1:${_col(ncols - 1)}${nrows}</definedName></definedNames>"
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
