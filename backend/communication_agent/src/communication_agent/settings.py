"""The communication agent's settings (backend/.env, section communication_agent). Read on every use, so a test or
a changed environment applies at once; nothing here is hardcoded in the nodes.

    COMMUNICATION_LLM_MODEL=gpt-4o-mini      writes the email (key: OPENAI_API_KEY); empty = plain template
    EMAIL_DELIVERY=smtp                      smtp = send | console = log only (default: smtp when SMTP_HOST is set)
    SMTP_HOST / SMTP_PORT                    e.g. smtp.gmail.com / 587
    SMTP_USERNAME / SMTP_PASSWORD            the account and its password (Gmail: an App Password)
    SMTP_USE_TLS=true                        TLS: STARTTLS (port 587) or SSL (port 465); false = plain (Mailpit)
    EMAIL_FROM                               the sender address (default: SMTP_USERNAME)
    EMAIL_FROM_NAME / EMAIL_SIGNATURE        the sender's display name / the closing lines (\\n = new line)
    EMAIL_REPLY_TO                           optional
    EMAIL_ALLOWED_DOMAINS                    recipients' domains allowed, comma separated; empty = any
    EMAIL_MAX_RECIPIENTS / SMTP_TIMEOUT_SECONDS
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_NAME = "ALTasnim Agent Platform"


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip().strip('"').strip("'")


def _flag(name: str, default: bool) -> bool:
    value = _env(name)
    return default if not value else value.lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    llm_model: str | None
    delivery: str  # smtp | console
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_use_tls: bool
    smtp_timeout: float
    from_address: str
    from_name: str
    reply_to: str
    signature: str
    allowed_domains: tuple[str, ...]
    max_recipients: int

    @property
    def security(self) -> str:
        """starttls | ssl | none"""
        if not self.smtp_use_tls:
            return "none"
        return "ssl" if self.smtp_port == 465 else "starttls"

    def missing(self) -> list[str]:
        """What must be set before an email can be sent (empty: ready)."""
        if self.delivery != "smtp":
            return []
        needed = {"SMTP_HOST": self.smtp_host, "SMTP_PORT": self.smtp_port}
        if self.smtp_use_tls:  # a TLS server (Gmail) needs a login
            needed |= {"SMTP_USERNAME": self.smtp_username, "SMTP_PASSWORD": self.smtp_password}
        if self.smtp_username or not self.smtp_use_tls:
            needed["EMAIL_FROM"] = self.from_address  # (defaults to SMTP_USERNAME)
        return [name for name, value in needed.items() if not value]

    def public(self) -> dict:
        """For the UI and logs: never the password."""
        return {
            "delivery": self.delivery, "smtp_host": self.smtp_host or None, "smtp_port": self.smtp_port,
            "security": self.security, "smtp_username": self.smtp_username or None,
            "password_set": bool(self.smtp_password), "from": self.from_address or None, "from_name": self.from_name,
            "reply_to": self.reply_to or None, "allowed_domains": list(self.allowed_domains),
            "max_recipients": self.max_recipients, "llm_model": self.llm_model,
            "ready": not self.missing(), "missing": self.missing(),
        }


def get_settings() -> Settings:
    host = _env("SMTP_HOST")
    delivery = (_env("EMAIL_DELIVERY") or ("smtp" if host else "console")).lower()
    if delivery not in ("smtp", "console"):
        raise ValueError(f"EMAIL_DELIVERY={delivery!r} must be smtp or console")
    username = _env("SMTP_USERNAME")
    name = _env("EMAIL_FROM_NAME") or DEFAULT_NAME
    return Settings(
        llm_model=_env("COMMUNICATION_LLM_MODEL") or None,
        delivery=delivery,
        smtp_host=host,
        smtp_port=_int("SMTP_PORT", 587),
        smtp_username=username,
        smtp_password=os.getenv("SMTP_PASSWORD", "").strip(),
        smtp_use_tls=_flag("SMTP_USE_TLS", True),
        smtp_timeout=float(_int("SMTP_TIMEOUT_SECONDS", 20)),
        from_address=_env("EMAIL_FROM") or username,
        from_name=name,
        reply_to=_env("EMAIL_REPLY_TO"),
        signature=(_env("EMAIL_SIGNATURE") or f"Best regards,\\n{name}").replace("\\n", "\n"),
        allowed_domains=tuple(d.strip().lower().lstrip("@") for d in _env("EMAIL_ALLOWED_DOMAINS").split(",")
                              if d.strip()),
        max_recipients=_int("EMAIL_MAX_RECIPIENTS", 10),
    )
