"""The email's layout: one structure -> a plain-text and an HTML version (email-safe: inline CSS, 600 px, no
images or scripts, everything escaped). The signature and the sources are added here, by code. The layout is kept
plain (like a personal email), because bulk-mail layouts (banners, boxes, tiny grey footers) are what spam filters
flag."""

from __future__ import annotations

import html
import re

from pydantic import BaseModel, Field

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


class Table(BaseModel):
    headers: list[str] = Field(description="Column headers.")
    rows: list[list[str]] = Field(description="Rows, one value per header.")


class EmailContent(BaseModel):
    """The parts of the email the writer (LLM or template) fills."""

    subject: str = Field(description="Specific subject line, at most 80 characters, no 'Re:', no emojis.")
    greeting: str = Field(description="'Dear <name>,' when the recipient's name is known, else 'Hello,'.")
    opening: str = Field(description="One sentence: why this email is sent.")
    paragraphs: list[str] = Field(default_factory=list,
                                  description="Short paragraphs with the facts; key figures in **bold**.")
    bullets: list[str] = Field(default_factory=list, description="Key points as a list, when that reads better.")
    table: Table | None = Field(None, description="Only to compare items side by side (e.g. two countries).")
    closing: str = Field("", description="One closing line, without promises (no signature).")


def _plain(text: str) -> str:
    return BOLD_RE.sub(r"\1", text)


def _inline(text: str) -> str:
    """Escaped HTML with **bold** and links."""
    out = BOLD_RE.sub(r"<strong>\1</strong>", html.escape(text))
    return re.sub(r"(https?://[^\s<]+)", r'<a href="\1" style="color:#1a56db;">\1</a>', out)


def to_text(email: EmailContent, signature: str, sources: list[str], from_name: str) -> str:
    lines = [_plain(email.greeting), "", _plain(email.opening)]
    for p in email.paragraphs:
        lines += ["", _plain(p)]
    if email.bullets:
        lines += [""] + [f"- {_plain(b)}" for b in email.bullets]
    if email.table and email.table.headers:
        lines += ["", " | ".join(email.table.headers)]
        lines += [" | ".join(_plain(c) for c in row) for row in email.table.rows]
    if email.closing:
        lines += ["", _plain(email.closing)]
    lines += ["", signature]
    if sources:
        lines += ["", "Sources"] + [f"{i}. {s}" for i, s in enumerate(sources, start=1)]
    return "\n".join(lines).strip() + "\n"


P = 'style="margin:0 0 14px 0;"'


def to_html(email: EmailContent, signature: str, sources: list[str], from_name: str) -> str:
    body = [f"<p {P}>{_inline(email.greeting)}</p>", f"<p {P}>{_inline(email.opening)}</p>"]
    body += [f"<p {P}>{_inline(p)}</p>" for p in email.paragraphs]
    if email.bullets:
        items = "".join(f'<li style="margin:0 0 6px 0;">{_inline(b)}</li>' for b in email.bullets)
        body.append(f'<ul style="margin:0 0 14px 0;padding-left:22px;">{items}</ul>')
    if email.table and email.table.headers:
        cell = 'style="border:1px solid #d9dee5;padding:8px 10px;text-align:left;"'
        head = "".join(f'<th {cell[:-1]}background:#f3f5f8;">{_inline(h)}</th>' for h in email.table.headers)
        rows = "".join("<tr>" + "".join(f"<td {cell}>{_inline(c)}</td>" for c in row) + "</tr>"
                       for row in email.table.rows)
        body.append('<table role="presentation" style="border-collapse:collapse;margin:0 0 14px 0;width:100%;">'
                    f"<tr>{head}</tr>{rows}</table>")
    if email.closing:
        body.append(f"<p {P}>{_inline(email.closing)}</p>")
    body.append(f'<p style="margin:18px 0 0 0;">{"<br>".join(_inline(line) for line in signature.splitlines())}</p>')
    if sources:
        items = "".join(f'<li style="margin:0 0 4px 0;">{_inline(s)}</li>' for s in sources)
        body.append(f'<p style="margin:18px 0 4px 0;">Sources:</p><ol style="margin:0;padding-left:20px;">{items}</ol>')
    return _page(email.subject, "".join(body))


def text_to_html(text: str, subject: str) -> str:
    """HTML for an email the approver edited as plain text: paragraphs, '- ' lists, links."""
    blocks = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if lines and all(line.lstrip().startswith(("- ", "• ")) for line in lines):
            items = "".join(f'<li style="margin:0 0 6px 0;">{_inline(line.lstrip()[2:])}</li>' for line in lines)
            blocks.append(f'<ul style="margin:0 0 14px 0;padding-left:22px;">{items}</ul>')
        else:
            blocks.append(f"<p {P}>{'<br>'.join(_inline(line) for line in lines)}</p>")
    return _page(subject, "".join(blocks))


def _page(subject: str, inner: str) -> str:
    """A plain, personal-looking page: no background, box or banner (those look like bulk mail to spam filters)."""
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<title>{html.escape(subject)}</title></head>"
        '<body style="margin:0;padding:0;">'
        '<div style="max-width:640px;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;'
        f'color:#222222;">{inner}</div></body></html>'
    )
