"""The email channel (communication_agent/settings.py).

EMAIL_DELIVERY=console logs the email and sends nothing (development). smtp sends it: STARTTLS (port 587) or SSL
(port 465) when SMTP_USE_TLS=true, with SMTP_USERNAME / SMTP_PASSWORD (Gmail: an App Password), as multipart
plain text + HTML. A temporary error (connection, timeout, disconnect) is tried again; a refused login or
recipient is not. Nothing is sent twice: once the server accepted the message, later errors are ignored.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate

from communication_agent.card import EmailDraft
from communication_agent.settings import Settings, get_settings

log = logging.getLogger(__name__)

ATTEMPTS = 3
_NS = uuid.UUID("0f8b6c1e-7d2a-4c55-9a1e-3b6f4f0d2c71")
SENT: deque[dict] = deque(maxlen=50)  # what the UI lists (GET /custom/sent), newest first; this process only


class EmailError(RuntimeError):
    """The email could not be sent; the message says why (shown to the user)."""


def message_id_for(key: str | None, from_address: str) -> str:
    """A stable id for the same run (so a retry is recognised), on the sender's domain."""
    domain = from_address.rsplit("@", 1)[-1] if "@" in from_address else "localhost"
    token = uuid.uuid5(_NS, key).hex if key else uuid.uuid4().hex
    return f"<{token}@{domain}>"


def build_message(draft: EmailDraft, message_id: str, settings: Settings) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((settings.from_name, settings.from_address))
    msg["To"] = ", ".join(draft.to)
    if draft.cc:
        msg["Cc"] = ", ".join(draft.cc)
    if settings.reply_to:
        msg["Reply-To"] = settings.reply_to
    msg["Subject"] = draft.subject
    msg["Date"] = formatdate(localtime=True)
    # no Message-ID header: the mail server (Gmail) sets its own; a self-made one is a spam signal. message_id
    # stays the run's internal id (no double send).
    msg.set_content(draft.body)
    if draft.html:
        msg.add_alternative(draft.html, subtype="html")
    return msg


def _send_smtp(msg: EmailMessage, recipients: list[str], s: Settings) -> None:
    context = ssl.create_default_context()
    if s.security == "ssl":
        smtp = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout, context=context)
    else:
        smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout)
    try:
        smtp.ehlo()
        if s.security == "starttls":
            smtp.starttls(context=context)
            smtp.ehlo()
        if s.smtp_username and s.smtp_password:
            smtp.login(s.smtp_username, s.smtp_password)
        refused = smtp.send_message(msg, from_addr=s.from_address, to_addrs=recipients)
        if refused:
            log.warning("some recipients were refused: %s", sorted(refused))
    finally:
        try:
            smtp.quit()
        except (smtplib.SMTPException, OSError):  # the message is already accepted (or the error is raised above)
            pass


def send_email(draft: EmailDraft) -> str:
    """Send the email (or log it, EMAIL_DELIVERY=console) and return its Message-ID (``draft.message_id``, else a
    new one). EmailError when it cannot."""
    s = get_settings()
    message_id = draft.message_id or message_id_for(None, s.from_address)
    recipients = [*draft.to, *draft.cc]

    if s.delivery == "console":
        log.warning("EMAIL_DELIVERY=console: not sending. To=%s Cc=%s Subject=%s", draft.to, draft.cc, draft.subject)
    else:
        if missing := s.missing():
            raise EmailError(f"Email is not configured: set {', '.join(missing)} in backend/.env")
        msg = build_message(draft, message_id, s)
        for attempt in range(1, ATTEMPTS + 1):
            try:
                _send_smtp(msg, recipients, s)
                break
            except smtplib.SMTPAuthenticationError as exc:
                raise EmailError(f"The mail server ({s.smtp_host}) rejected the login for {s.smtp_username}: check "
                                 "SMTP_USERNAME and SMTP_PASSWORD (Gmail needs an App Password).") from exc
            except smtplib.SMTPRecipientsRefused as exc:
                raise EmailError(f"The mail server refused the recipients: {', '.join(exc.recipients)}") from exc
            except smtplib.SMTPSenderRefused as exc:
                raise EmailError(f"The mail server refused the sender {s.from_address} (EMAIL_FROM).") from exc
            except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, TimeoutError, ConnectionError,
                    OSError) as exc:
                if attempt == ATTEMPTS:
                    raise EmailError(f"Could not reach the mail server {s.smtp_host}:{s.smtp_port} "
                                     f"({type(exc).__name__}: {exc}).") from exc
                log.warning("mail server error (attempt %d of %d): %s", attempt, ATTEMPTS, exc)
                time.sleep(2 * attempt)

    SENT.appendleft({"message_id": message_id, "to": draft.to, "cc": draft.cc, "subject": draft.subject,
                     "delivery": s.delivery, "writer": draft.writer,
                     "at": datetime.now(UTC).isoformat(timespec="seconds")})
    return message_id
