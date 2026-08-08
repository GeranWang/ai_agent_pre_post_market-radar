"""Email delivery over plain SMTP (stdlib only — no new dependency).

Configured via .env:
    SMTP_HOST   default "smtp.gmail.com"
    SMTP_PORT   default 587 (STARTTLS); 465 switches to implicit SSL
    SMTP_USER   sender login (e.g. your Gmail address)
    SMTP_PASS   app password (Gmail: generate one under 2FA → App passwords)
    EMAIL_FROM  optional "From" address; defaults to SMTP_USER
    EMAIL_TO    optional default recipient (used by `--send`)

The rendered HTML brief is the email body, with the Markdown brief as the
plain-text alternative. Sending is opt-in from main.py (--email / --send).
"""
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from rich.console import Console

from src.schemas.brief import DailyBrief

console = Console()


def _ssl_context() -> ssl.SSLContext:
    """Build a TLS context with a working CA bundle.

    macOS Python builds often can't find system root certs, which makes
    starttls() fail with CERTIFICATE_VERIFY_FAILED. certifi (already pulled in
    by httpx) ships a portable bundle; use it when available.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class EmailConfigError(RuntimeError):
    """SMTP credentials or recipient missing — surfaced as a clean message."""


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise EmailConfigError(
            f"{name} is not set in .env — cannot send email. "
            f"Need SMTP_USER + SMTP_PASS (Gmail: an App Password under 2FA)."
        )
    return val


def send_alert_email(subject: str, body: str, recipient: str) -> None:
    """Plain-text operational alert (used by the scheduler when a run gives up).

    Deliberately shares nothing with the brief path except the SMTP settings —
    an alert must still go out when brief rendering is what broke.
    """
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = _require("SMTP_USER")
    password = _require("SMTP_PASS")
    sender = os.environ.get("EMAIL_FROM", user)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Pre-market Radar", sender))
    msg["To"] = recipient
    msg.set_content(body)

    context = _ssl_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
            server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(msg)


def send_brief_email(
    brief: DailyBrief,
    html_path: Path,
    recipient: str,
    md_text: str | None = None,
) -> None:
    """Send the rendered brief to `recipient` over SMTP. Raises EmailConfigError
    if credentials are missing; lets smtplib errors propagate to the caller."""
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = _require("SMTP_USER")
    password = _require("SMTP_PASS")
    sender = os.environ.get("EMAIL_FROM", user)

    html = Path(html_path).read_text(encoding="utf-8")
    sig = brief.signal_state
    subject = f"Pre-market Radar · {brief.date} · {sig}"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Pre-market Radar", sender))
    msg["To"] = recipient

    # Plain-text alternative: the Markdown brief if we have it, else a stub.
    if md_text:
        msg.set_content(md_text)
    else:
        msg.set_content("This brief is best viewed in an HTML-capable client.")
    msg.add_alternative(html, subtype="html")

    console.print(f"[dim]Sending via {host}:{port} as {sender} → {recipient}")
    context = _ssl_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
            server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(msg)

    console.print(f"[bold green]Email sent → {recipient}  [dim]({subject})")
