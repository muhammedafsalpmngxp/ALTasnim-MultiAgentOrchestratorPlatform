import io

import pytest
from rag_agent.parsing import UnsupportedFileType, extract_sections


def test_text_files_decode_utf8_with_bom():
    assert extract_sections("notes.TXT", "﻿retention is 5%".encode()) == [(None, "retention is 5%")]
    assert extract_sections("rows.csv", b"item,qty\nsteel,10") == [(None, "item,qty\nsteel,10")]


def test_docx_paragraphs_and_tables():
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Clause 5: retention is 5%.")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Steel"
    table.rows[0].cells[1].text = "10 t"
    buf = io.BytesIO()
    document.save(buf)

    [(page, text)] = extract_sections("contract.docx", buf.getvalue())
    assert page is None
    assert text.splitlines() == ["Clause 5: retention is 5%.", "Steel | 10 t"]


def _pdf(pages: list[str]) -> bytes:
    """A minimal PDF with one line of Helvetica text per page."""
    n = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n)).encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, n)]
    font = 3 + 2 * n
    for i, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
                       b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (4 + 2 * i, font))
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def test_pdf_text_layer_with_page_numbers():
    pytest.importorskip("pypdf")
    sections = extract_sections("spec.pdf", _pdf(["Scope of work", "Retention is 5 percent"]))
    assert [(page, text.strip()) for page, text in sections] == [(1, "Scope of work"), (2, "Retention is 5 percent")]


def test_unsupported_type():
    with pytest.raises(UnsupportedFileType):
        extract_sections("drawing.dwg", b"...")
    with pytest.raises(UnsupportedFileType):
        extract_sections("no_extension", b"...")
