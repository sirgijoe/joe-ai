"""Small real files for the paperwork tool tests, made with the standard library only:
a PDF (pages of text, optionally with a fill-in form) and a Word file (text split over runs)."""
from __future__ import annotations

import zipfile
from pathlib import Path


def make_pdf(path: Path, pages=("Page 1",), form: bool = False) -> Path:
    """A valid PDF. form=True adds a text field 'Full name', a tick box 'Agree' and a pick list 'Color'."""
    objs: list[str] = []

    def add(s: str) -> int:
        objs.append(s)
        return len(objs)
    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pages_id = add("PAGES")
    page_ids: list[int] = []
    fields: list[int] = []
    for i, t in enumerate(pages):
        stream = f"BT /F1 24 Tf 72 700 Td ({t}) Tj ET"
        c = add(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        annots = ""
        if form and i == 0:
            name = add("TEXT")
            yes = add("<< /Length 0 >>\nstream\n\nendstream")
            off = add("<< /Length 0 >>\nstream\n\nendstream")
            box = add("CHECK")
            pick = add("CHOICE")
            fields = [name, box, pick]
            annots = f" /Annots [{name} 0 R {box} 0 R {pick} 0 R]"
        p = add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 792] /Contents {c} 0 R "
                f"/Resources << /Font << /F1 {font} 0 R >> >>{annots} >>")
        page_ids.append(p)
        if form and i == 0:
            objs[name - 1] = (f"<< /Type /Annot /Subtype /Widget /FT /Tx /T (Full name) /TU (Your full name) /V () "
                              f"/Rect [72 600 300 620] /P {p} 0 R /F 4 /DA (/Helv 12 Tf 0 g) >>")
            objs[box - 1] = (f"<< /Type /Annot /Subtype /Widget /FT /Btn /T (Agree) /V /Off /AS /Off "
                             f"/AP << /N << /Yes {yes} 0 R /Off {off} 0 R >> >> /Rect [72 560 90 578] /P {p} 0 R /F 4 >>")
            objs[pick - 1] = (f"<< /Type /Annot /Subtype /Widget /FT /Ch /Ff 131072 /T (Color) /Opt [(Red) (Blue)] /V () "
                              f"/Rect [72 520 200 540] /P {p} 0 R /F 4 /DA (/Helv 12 Tf 0 g) >>")
    objs[pages_id - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{x} 0 R' for x in page_ids)}] "
                          f"/Count {len(page_ids)} >>")
    acro = ""
    if form:
        helv = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        af = add(f"<< /Fields [{' '.join(f'{x} 0 R' for x in fields)}] /DR << /Font << /Helv {helv} 0 R >> >> "
                 "/DA (/Helv 0 Tf 0 g) >>")
        acro = f" /AcroForm {af} 0 R"
    cat = add(f"<< /Type /Catalog /Pages {pages_id} 0 R{acro} >>")
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offsets:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root {cat} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _p(*runs: str) -> str:
    return "<w:p><w:pPr><w:jc w:val=\"left\"/></w:pPr>" + "".join(
        f'<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">{r}</w:t></w:r>' for r in runs) + "</w:p>"


def make_docx(path: Path, paragraphs: list[list[str]], header: list[str] | None = None,
              author: str = "Jane Writer") -> Path:
    """A Word file: each paragraph is a list of runs (so a word can be split over runs, like Word does)."""
    body = "".join(_p(*runs) for runs in paragraphs)
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W}><w:body>{body}'
           '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr></w:body></w:document>')
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>')
        z.writestr("word/document.xml", doc)
        if header:
            z.writestr("word/header1.xml", f'<?xml version="1.0"?><w:hdr {W}>{_p(*header)}</w:hdr>')
        z.writestr("docProps/core.xml", '<?xml version="1.0"?><cp:coreProperties xmlns:cp="x" xmlns:dc="y">'
                   f"<dc:creator>{author}</dc:creator><cp:lastModifiedBy>{author}</cp:lastModifiedBy>"
                   "</cp:coreProperties>")
    return path
