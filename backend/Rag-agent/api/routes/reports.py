"""
Report generation — export chat sessions or search results as Word/PDF.
"""
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.background import BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.core.deps import AuthUser

router = APIRouter()


def _cleanup(path: str):
    """Return a BackgroundTasks that deletes the temp file after it's been sent."""
    tasks = BackgroundTasks()
    tasks.add_task(Path(path).unlink, missing_ok=True)
    return tasks


def _md_to_docx_paragraph(doc, line: str):
    """Add a single markdown line to a docx Document with proper styling."""
    from docx.shared import RGBColor

    # Headings
    h_match = re.match(r"^(#{1,4})\s+(.*)", line)
    if h_match:
        level = min(len(h_match.group(1)), 4)
        doc.add_heading(h_match.group(2).strip(), level=level)
        return

    # Bullet points
    if re.match(r"^[-*]\s+", line):
        text = re.sub(r"^[-*]\s+", "", line)
        p = doc.add_paragraph(style="List Bullet")
        _add_inline_md(p, text)
        return

    # Numbered list
    if re.match(r"^\d+\.\s+", line):
        text = re.sub(r"^\d+\.\s+", "", line)
        p = doc.add_paragraph(style="List Number")
        _add_inline_md(p, text)
        return

    # Normal paragraph
    p = doc.add_paragraph()
    _add_inline_md(p, line)


def _add_inline_md(paragraph, text: str):
    """Add text with inline bold/italic markdown to a docx paragraph. Also honors <br> as a real
    line break (LLMs use it to pack multiple points on one line/bullet)."""
    for seg_idx, seg in enumerate(_split_br(text)):
        if seg_idx > 0:
            paragraph.add_run().add_break()   # <br> -> line break within the paragraph
        # Split on **bold** and *italic* markers
        parts = re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", seg)
        for part in parts:
            if part.startswith("**") and part.endswith("**"):
                run = paragraph.add_run(part[2:-2])
                run.bold = True
            elif part.startswith("*") and part.endswith("*"):
                run = paragraph.add_run(part[1:-1])
                run.italic = True
            else:
                paragraph.add_run(part)


_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _split_br(text: str) -> List[str]:
    """Split a string on <br>/<br/>/<br /> variants (LLMs use these for line breaks inside
    markdown table cells, where a real newline would break the table)."""
    return _BR_RE.split(text or "")


def _cell_to_reportlab(text: str) -> str:
    """Convert a (possibly multi-line via <br>) markdown table cell into reportlab paragraph markup:
    each <br>-separated segment is HTML-escaped + bold/italic-converted, then rejoined with a real
    <br/> so reportlab renders proper line breaks inside the cell."""
    return "<br/>".join(_md_to_reportlab(seg.strip()) for seg in _split_br(text))


def _md_to_reportlab(text: str) -> str:
    """Convert inline markdown bold/italic to reportlab XML tags."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    # Restore <br> (escaped above) as a real reportlab line break, so multi-point paragraphs/bullets
    # don't render literal "<br>" text.
    text = re.sub(r"&lt;br\s*/?&gt;", "<br/>", text, flags=re.IGNORECASE)
    return text


class GenerateReportRequest(BaseModel):
    title: str
    session_id: Optional[str] = None   # export a chat session
    project_id: Optional[str] = None   # export project summary
    include_references: bool = True
    format: str = "docx"               # docx | pdf


def _is_table_line(line: str) -> bool:
    return line.strip().startswith("|") and line.strip().endswith("|")


def _is_table_separator(line: str) -> bool:
    return _is_table_line(line) and re.match(r"^\|[-| :]+\|$", line.strip())


def _parse_table_rows(lines: List[str]) -> List[List[str]]:
    rows = []
    for line in lines:
        if _is_table_separator(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


def _add_docx_table(doc, table_lines: List[str]):
    """Render a markdown table block as a proper docx table."""
    from docx.shared import Pt, RGBColor
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    rows = _parse_table_rows(table_lines)
    if not rows:
        return

    col_count = max(len(r) for r in rows)
    tbl = doc.add_table(rows=len(rows), cols=col_count)
    tbl.style = "Table Grid"

    from docx.enum.table import WD_ALIGN_VERTICAL
    for r_idx, row_cells in enumerate(rows):
        row = tbl.rows[r_idx]
        for c_idx, cell_text in enumerate(row_cells):
            if c_idx >= col_count:
                break
            cell = row.cells[c_idx]
            cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
            cell.text = ""
            p = cell.paragraphs[0]
            # Cells often pack several points separated by <br>; render each on its own line so the
            # cell isn't a cramped run-on with literal "<br>" text. Bold markdown inside is honored.
            segments = _split_br(cell_text)
            for s_idx, seg in enumerate(segments):
                seg = seg.strip()
                if s_idx > 0:
                    p.add_run().add_break()   # line break within the same cell
                if r_idx == 0:  # header row — bold, plain text
                    run = p.add_run(seg.replace("**", ""))
                    run.bold = True
                else:
                    _add_inline_md(p, seg)    # honor **bold**/*italic* inside the cell line

    doc.add_paragraph("")


def _build_docx(title: str, messages: list, include_refs: bool) -> str:
    """Build a .docx report and return its temp file path."""
    try:
        from docx import Document
        from docx.shared import RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="python-docx not installed. Run: pip install python-docx",
        )

    doc = Document()

    title_para = doc.add_heading(title, level=0)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta = doc.add_paragraph("Generated by L&T Files Assistant")
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph("")

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""
        if role == "user":
            p = doc.add_paragraph()
            run = p.add_run(f"Q: {content}")
            run.bold = True
            run.font.color.rgb = RGBColor(0x1a, 0x56, 0xdb)
        elif role == "assistant":
            lines = content.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i]
                # Collect consecutive table lines as one block
                if _is_table_line(line):
                    table_block = []
                    while i < len(lines) and _is_table_line(lines[i]):
                        table_block.append(lines[i])
                        i += 1
                    _add_docx_table(doc, table_block)
                    continue
                if not line.strip():
                    doc.add_paragraph("")
                else:
                    _md_to_docx_paragraph(doc, line)
                i += 1
            if include_refs and msg.get("reference"):
                refs = msg["reference"]
                sources = refs.get("sources", []) if isinstance(refs, dict) else []
                if sources:
                    doc.add_paragraph("Sources:", style="Intense Quote")
                    for ref in sources[:5]:
                        doc.add_paragraph(
                            f"• {ref.get('document_name', ref.get('docnm_kwd', 'Unknown document'))} (score: {ref.get('similarity', 0):.2f})",
                            style="List Bullet",
                        )
        doc.add_paragraph("")

    out_path = os.path.join(tempfile.gettempdir(), f"lt_report_{uuid.uuid4().hex}.docx")
    doc.save(out_path)
    return out_path


def _build_pdf(title: str, messages: list, include_refs: bool) -> str:
    """Build a PDF report using reportlab and return its temp file path."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="reportlab not installed. Run: pip install reportlab",
        )

    out_path = os.path.join(tempfile.gettempdir(), f"lt_report_{uuid.uuid4().hex}.pdf")
    doc = SimpleDocTemplate(out_path, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle("ReportTitle", parent=styles["Title"], fontSize=18, spaceAfter=12)
    style_meta  = ParagraphStyle("Meta", parent=styles["Normal"], fontSize=9, textColor=colors.grey, spaceAfter=16)
    style_q     = ParagraphStyle("Question", parent=styles["Normal"], fontSize=11, textColor=colors.HexColor("#1a56db"), fontName="Helvetica-Bold", spaceBefore=12, spaceAfter=4)
    style_a     = ParagraphStyle("Answer", parent=styles["Normal"], fontSize=11, spaceBefore=4, spaceAfter=6, leading=15)
    style_src   = ParagraphStyle("Source", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#555555"), leftIndent=12)

    style_h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=13, spaceBefore=10, spaceAfter=4)
    style_h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceBefore=8, spaceAfter=3)
    style_h3 = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=11, spaceBefore=6, spaceAfter=2)
    style_bullet = ParagraphStyle("Bullet", parent=styles["Normal"], fontSize=11, leftIndent=16, leading=15)

    story = [
        Paragraph(title, style_title),
        Paragraph("Generated by L&T Files Assistant", style_meta),
    ]

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""
        if role == "user":
            safe = _md_to_reportlab(content)
            story.append(Paragraph(f"Q: {safe}", style_q))
        elif role == "assistant":
            from reportlab.platypus import Table, TableStyle
            from reportlab.lib import colors as rl_colors
            lines = content.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i]
                if _is_table_line(line):
                    table_block = []
                    while i < len(lines) and _is_table_line(lines[i]):
                        table_block.append(lines[i])
                        i += 1
                    rows = _parse_table_rows(table_block)
                    if rows:
                        from reportlab.platypus import Paragraph as _P
                        from reportlab.lib.styles import ParagraphStyle as _PS
                        # Wrap each cell in a Paragraph so long text WRAPS (raw strings overflow the
                        # page) and <br> renders as real line breaks. Fixed column widths keep the
                        # table aligned within the page; header cells are white bold on the blue bg.
                        col_count = max(len(r) for r in rows)
                        cell_style = _PS("PdfCell", fontName="Helvetica", fontSize=9, leading=12)
                        head_style = _PS("PdfCellH", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=rl_colors.white)
                        prows = []
                        for r_idx, row in enumerate(rows):
                            st = head_style if r_idx == 0 else cell_style
                            cells = [_P(_cell_to_reportlab(c), st) for c in row]
                            while len(cells) < col_count:
                                cells.append(_P("", cell_style))
                            prows.append(cells)
                        total_w = 468.0  # ~usable width on letter with 1in margins
                        if col_count <= 1:
                            col_widths = [total_w]
                        else:
                            first = total_w * 0.30
                            col_widths = [first] + [(total_w - first) / (col_count - 1)] * (col_count - 1)
                        tbl = Table(prows, colWidths=col_widths, hAlign="LEFT")
                        tbl.setStyle(TableStyle([
                            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#1a56db")),
                            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.grey),
                            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl_colors.white, rl_colors.HexColor("#f3f4f6")]),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 6),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ]))
                        story.append(tbl)
                        story.append(Spacer(1, 8))
                    continue
                if not line.strip():
                    story.append(Spacer(1, 6))
                    i += 1
                    continue
                h_match = re.match(r"^(#{1,4})\s+(.*)", line)
                if h_match:
                    level = len(h_match.group(1))
                    h_style = {1: style_h1, 2: style_h2}.get(level, style_h3)
                    story.append(Paragraph(_md_to_reportlab(h_match.group(2)), h_style))
                elif re.match(r"^[-*]\s+", line):
                    text = re.sub(r"^[-*]\s+", "", line)
                    story.append(Paragraph(f"• {_md_to_reportlab(text)}", style_bullet))
                elif re.match(r"^\d+\.\s+", line):
                    text = re.sub(r"^\d+\.\s+", "", line)
                    story.append(Paragraph(f"{_md_to_reportlab(line[:line.index('.')+1])} {_md_to_reportlab(text)}", style_bullet))
                else:
                    story.append(Paragraph(_md_to_reportlab(line), style_a))
                i += 1
            if include_refs and msg.get("reference"):
                refs = msg["reference"]
                sources = refs.get("sources", []) if isinstance(refs, dict) else []
                for ref in sources[:5]:
                    doc_name = ref.get("document_name", ref.get("docnm_kwd", "Unknown"))
                    score = ref.get("similarity", 0)
                    story.append(Paragraph(f"• {doc_name} (score: {score:.2f})", style_src))
        story.append(Spacer(1, 4))

    doc.build(story)
    return out_path


@router.post("/reports/generate")
async def generate_report(req: GenerateReportRequest, user: AuthUser):
    """Generate a Word or PDF report from a chat session."""
    if not req.session_id and not req.project_id:
        raise HTTPException(status_code=400, detail="Provide session_id or project_id")

    messages = []

    if req.session_id:
        try:
            from api.db.services.conversation_service import ConversationService
            from api.db.services.dialog_service import DialogService
            _, conv = ConversationService.get_by_id(req.session_id)
            if not conv:
                raise HTTPException(status_code=404, detail="Session not found")
            _, dialog = DialogService.get_by_id(str(conv.dialog_id))
            if not dialog or str(getattr(dialog, "tenant_id", "")) != user.tenant_id:
                raise HTTPException(status_code=403, detail="Forbidden")
            messages = list(getattr(conv, "message", []) or [])
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    elif req.project_id:
        try:
            from api.db.services.knowledgebase_service import KnowledgebaseService
            from api.db.services.document_service import DocumentService
            _, kb = KnowledgebaseService.get_by_id(req.project_id)
            if not kb or str(kb.tenant_id) != user.tenant_id:
                raise HTTPException(status_code=404, detail="Project not found")
            docs = DocumentService.query(kb_id=req.project_id, status="1")
            messages = [
                {"role": "assistant", "content": f"Project: {kb.name}\nTotal documents: {len(docs)}"}
            ]
            for d in docs:
                messages.append({
                    "role": "assistant",
                    "content": (
                        f"Document: {d.name}\n"
                        f"Status: {getattr(d, 'run', 'unknown')}\n"
                        f"Chunks: {getattr(d, 'chunk_num', 0)}"
                    ),
                })
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    if not messages:
        raise HTTPException(status_code=400, detail="No content to generate report from")

    docx_path = _build_docx(req.title, messages, req.include_references)

    if req.format == "pdf":
        try:
            pdf_path = _build_pdf(req.title, messages, req.include_references)
        finally:
            Path(docx_path).unlink(missing_ok=True)
        filename = req.title.replace(" ", "_") + ".pdf"
        return FileResponse(pdf_path, filename=filename, media_type="application/pdf",
                            background=_cleanup(pdf_path))

    filename = req.title.replace(" ", "_") + ".docx"
    return FileResponse(
        docx_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        background=_cleanup(docx_path),
    )


@router.get("/reports/session/{session_id}")
async def download_session_report(
    session_id: str,
    format: str = "docx",
    user: AuthUser = None,
):
    """Shortcut: download a session as a report directly."""
    try:
        from api.db.services.conversation_service import ConversationService
        from api.db.services.dialog_service import DialogService
        _, conv = ConversationService.get_by_id(session_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Session not found")
        _, dialog = DialogService.get_by_id(str(conv.dialog_id))
        if not dialog or (user and str(getattr(dialog, "tenant_id", "")) != user.tenant_id):
            raise HTTPException(status_code=403, detail="Forbidden")
        title = getattr(conv, "name", "Chat Report")
        messages = list(getattr(conv, "message", []) or [])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    docx_path = _build_docx(title, messages, include_refs=True)
    if format == "pdf":
        try:
            pdf_path = _build_pdf(title, messages, include_refs=True)
        finally:
            Path(docx_path).unlink(missing_ok=True)
        return FileResponse(pdf_path, filename=f"{title}.pdf", media_type="application/pdf",
                            background=_cleanup(pdf_path))

    return FileResponse(
        docx_path,
        filename=f"{title}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        background=_cleanup(docx_path),
    )
