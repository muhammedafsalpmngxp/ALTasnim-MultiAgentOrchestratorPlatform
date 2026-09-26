"""Email channels. EMAIL_CHANNEL=console (default) sends nothing; smtp uses SMTP (e.g. Mailpit)."""

from __future__ import annotations

import logging
import os
import smtplib
import uuid
from email.message import EmailMessage

from communication_agent.card import EmailDraft

log = logging.getLogger(__name__)


def send_email(draft: EmailDraft) -> str:
    """Send the email and return a message id."""
    message_id = f"<{uuid.uuid4().hex}@altasnim.local>"
    channel = os.getenv("EMAIL_CHANNEL", "console")

    if channel == "console":
        log.warning("EMAIL_CHANNEL=console, not sending. To=%s Subject=%s", draft.to, draft.subject)
        return message_id

    if channel == "smtp":
        msg = EmailMessage()
        msg["From"] = os.getenv("EMAIL_FROM", "agents@altasnim.local")
        msg["To"] = ", ".join(draft.to)
        msg["Subject"] = draft.subject
        msg["Message-ID"] = message_id
        msg.set_content(draft.body)
        host = os.getenv("EMAIL_SMTP_HOST", "localhost")
        port = int(os.getenv("EMAIL_SMTP_PORT", "1025"))
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            # TODO(team-comms): starttls + login for real SMTP servers / use Microsoft Graph.
            smtp.send_message(msg)
        return message_id

    raise ValueError(f"Unknown EMAIL_CHANNEL={channel!r}")
