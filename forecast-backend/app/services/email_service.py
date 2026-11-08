"""
Transactional email. Providers (settings.EMAIL_PROVIDER):

- "console" (default): nothing is sent; the message -- including the one-time code -- is logged. Fine for local dev
  (read the code in the uvicorn terminal). Never use for real users.
- "smtp": any SMTP server (Zoho, Google Workspace, Brevo, Mailgun, Amazon SES...). Set SMTP_HOST/PORT/USERNAME/PASSWORD.
- "resend": resend.com HTTP API (RESEND_API_KEY).
- "webhook": a Google Apps Script web app (gmail_relay.gs) that sends from a Gmail account over HTTPS. Works where SMTP
  ports are blocked (Render free plan). Set EMAIL_WEBHOOK_URL and EMAIL_WEBHOOK_SECRET.

Every email is multipart (plain text + branded HTML), has a From of EMAIL_FROM_ADDRESS (use a no-reply address on your
own domain), a Reply-To of EMAIL_REPLY_TO/SUPPORT_EMAIL when set, and a footer telling the reader why they got it.
Sending never raises into the request path: failures are logged and reported via the boolean return value.
"""
from __future__ import annotations

import html
import logging
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from typing import Callable

import httpx

from app.core.config import settings

logger = logging.getLogger("forecast.email")

BRAND = "Forecast"

# Pauses between retries of a failed send (so up to len+1 attempts). Only used by `send_with_retry`, which is only
# called from background tasks -- never make a user wait on these. Tests set this to () for instant runs.
RETRY_DELAYS: tuple[float, ...] = (2.0, 6.0)


def _clean(value: str | None) -> str:
    """Env values pasted into dashboards often carry a trailing space/newline/quotes; those silently break matching
    (e.g. 'webhook ' != 'webhook' would fall back to console mode and never send anything)."""
    return (value or "").strip().strip('"').strip("'").strip()


def provider_name() -> str:
    return _clean(settings.EMAIL_PROVIDER).lower() or "console"


def is_live() -> bool:
    """True when real emails can actually go out with the current settings."""
    p = provider_name()
    if p == "smtp":
        return bool(_clean(settings.SMTP_HOST))
    if p == "webhook":
        return bool(_clean(settings.EMAIL_WEBHOOK_URL) and _clean(settings.EMAIL_WEBHOOK_SECRET))
    if p == "resend":
        return bool(_clean(settings.RESEND_API_KEY))
    return False


def log_status() -> None:
    """One line at startup so a missing/misspelled email config is obvious in the Render logs."""
    if is_live():
        logger.info("Email: provider=%s is configured; password-reset codes will be emailed.", provider_name())
    else:
        logger.error(
            "Email: NOT CONFIGURED (EMAIL_PROVIDER=%r). Password-reset codes will NOT be emailed -- they only appear in "
            "these logs. Set EMAIL_PROVIDER and its credentials in the Render environment (see EMAIL_SETUP.md).",
            settings.EMAIL_PROVIDER,
        )


def _footer_text() -> str:
    support = settings.EMAIL_REPLY_TO or settings.SUPPORT_EMAIL
    lines = ["", "--", f"{BRAND} - the fantasy stock market for Fortnite esports.",
             "This is an automated message from a no-reply address; please do not reply to it."]
    if support:
        lines.append(f"Need help? Contact {support}.")
    return "\n".join(lines)


def _render_html(heading: str, intro: str, code: str | None, outro: str) -> str:
    support = settings.EMAIL_REPLY_TO or settings.SUPPORT_EMAIL
    code_block = ""
    if code:
        code_block = (
            '<div style="margin:24px 0;text-align:center;">'
            '<span style="display:inline-block;padding:14px 26px;border-radius:12px;background:#0b1424;'
            'border:1px solid #1d2b45;font-family:Consolas,Menlo,monospace;font-size:32px;letter-spacing:10px;'
            f'color:#00c8ff;font-weight:700;">{html.escape(code)}</span></div>'
        )
    support_html = f' Need help? Contact <a href="mailto:{html.escape(support)}" style="color:#00c8ff;">{html.escape(support)}</a>.' if support else ""
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#050b16;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#050b16;padding:32px 12px;">
<tr><td align="center">
<table role="presentation" width="480" cellspacing="0" cellpadding="0" style="max-width:480px;width:100%;background:#0a1322;border:1px solid #16233b;border-radius:16px;font-family:Segoe UI,Helvetica,Arial,sans-serif;color:#dbe6f5;">
<tr><td style="padding:28px 32px 8px 32px;">
<div style="font-size:18px;font-weight:700;letter-spacing:3px;color:#ffffff;">FORECAST</div>
<div style="font-size:11px;color:#7d8fae;margin-top:2px;">Esports Markets</div></td></tr>
<tr><td style="padding:8px 32px 0 32px;">
<h2 style="margin:16px 0 8px 0;font-size:20px;color:#ffffff;">{html.escape(heading)}</h2>
<p style="margin:0;font-size:14px;line-height:1.6;color:#b9c7dc;">{html.escape(intro)}</p>
{code_block}
<p style="margin:0 0 8px 0;font-size:13px;line-height:1.6;color:#8fa1bf;">{html.escape(outro)}</p></td></tr>
<tr><td style="padding:20px 32px 28px 32px;border-top:1px solid #16233b;font-size:11px;line-height:1.6;color:#667896;">
This is an automated message from a no-reply address - please don't reply to it.{support_html}</td></tr>
</table></td></tr></table></body></html>"""


def try_send(to_email: str, subject: str, text_body: str, html_body: str | None = None) -> tuple[bool, str | None]:
    """Attempts one send. Returns (ok, error_text). Never raises. A console/unconfigured provider counts as a FAILURE
    (nothing reaches the person), so callers can retry, clean up, or tell the admin -- it is not silently 'sent'."""
    provider = provider_name()
    try:
        if provider == "smtp":
            if not _clean(settings.SMTP_HOST):
                return _unconfigured(to_email, subject, text_body, "EMAIL_PROVIDER=smtp but SMTP_HOST is not set")
            return _smtp(to_email, subject, text_body, html_body), None
        if provider == "webhook":
            if not (_clean(settings.EMAIL_WEBHOOK_URL) and _clean(settings.EMAIL_WEBHOOK_SECRET)):
                return _unconfigured(to_email, subject, text_body, "EMAIL_PROVIDER=webhook but EMAIL_WEBHOOK_URL / EMAIL_WEBHOOK_SECRET is not set")
            return _webhook(to_email, subject, text_body, html_body), None
        if provider == "resend":
            if not _clean(settings.RESEND_API_KEY):
                return _unconfigured(to_email, subject, text_body, "EMAIL_PROVIDER=resend but RESEND_API_KEY is not set")
            return _resend(to_email, subject, text_body, html_body), None
    except Exception as exc:  # noqa: BLE001 -- every provider failure ends up here
        logger.exception("Failed to send email %r to %s via %s", subject, to_email, provider)
        return False, f"{type(exc).__name__}: {exc}"
    if provider == "console":
        # Deliberate dev mode: the message (and its code) is printed to the server log. Counts as success so local
        # development works; `log_status()` shouts at startup if this is accidentally what production is running.
        logger.warning("EMAIL_PROVIDER=console -- NOT sending. To: %s | Subject: %s\n%s", to_email, subject, text_body)
        return True, None
    # A typo such as "webook" must not quietly behave like console mode.
    return _unconfigured(to_email, subject, text_body, f"Unknown EMAIL_PROVIDER {settings.EMAIL_PROVIDER!r} (use console, smtp, webhook or resend)")


def send_email(to_email: str, subject: str, text_body: str, html_body: str | None = None) -> bool:
    return try_send(to_email, subject, text_body, html_body)[0]


def send_with_retry(send: Callable[[], bool | None], what: str) -> bool:
    """Calls `send()` until it stops returning False, pausing RETRY_DELAYS between attempts. Blocking -- only call it
    from a background task. (Returning None counts as success: only an explicit False is a failure.)"""
    attempts = len(RETRY_DELAYS) + 1
    for i in range(attempts):
        try:
            result = send()
        except Exception:  # noqa: BLE001 -- an exception is just another failed attempt
            logger.exception("Email (%s) raised on attempt %d", what, i + 1)
            result = False
        if result is not False:
            if i:
                logger.info("Email (%s) went through on attempt %d.", what, i + 1)
            return True
        if i < attempts - 1:
            logger.warning("Email (%s) failed (attempt %d/%d) -- retrying in %.0fs.", what, i + 1, attempts, RETRY_DELAYS[i])
            time.sleep(RETRY_DELAYS[i])
    logger.error("Email (%s) FAILED after %d attempts -- the person did not receive it.", what, attempts)
    return False


def _unconfigured(to_email: str, subject: str, text_body: str, why: str) -> tuple[bool, str]:
    # Still prints the message (that is how local dev reads its codes) but reports failure: it was NOT delivered.
    logger.error("%s -- email NOT sent. To: %s | Subject: %s\n%s", why, to_email, subject, text_body)
    return False, why


def _reply_to() -> str | None:
    return settings.EMAIL_REPLY_TO or settings.SUPPORT_EMAIL


def _smtp(to_email: str, subject: str, text_body: str, html_body: str | None) -> bool:
    msg = EmailMessage()
    msg["From"] = settings.EMAIL_FROM_ADDRESS
    msg["To"] = to_email
    msg["Subject"] = subject
    if _reply_to():
        msg["Reply-To"] = _reply_to()
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    sender = parseaddr(settings.EMAIL_FROM_ADDRESS)[1] or settings.EMAIL_FROM_ADDRESS
    host = _clean(settings.SMTP_HOST)
    if settings.SMTP_USE_SSL:
        with smtplib.SMTP_SSL(host, settings.SMTP_PORT, timeout=15, context=ssl.create_default_context()) as s:
            if settings.SMTP_USERNAME:
                s.login(_clean(settings.SMTP_USERNAME), settings.SMTP_PASSWORD or "")
            s.send_message(msg, from_addr=sender)
    else:
        with smtplib.SMTP(host, settings.SMTP_PORT, timeout=15) as s:
            s.starttls(context=ssl.create_default_context())
            if settings.SMTP_USERNAME:
                s.login(_clean(settings.SMTP_USERNAME), settings.SMTP_PASSWORD or "")
            s.send_message(msg, from_addr=sender)
    return True


def _webhook(to_email: str, subject: str, text_body: str, html_body: str | None) -> bool:
    payload = {
        "secret": _clean(settings.EMAIL_WEBHOOK_SECRET),
        "to": to_email,
        "subject": subject,
        "text": text_body,
        "html": html_body,
        "from_name": parseaddr(settings.EMAIL_FROM_ADDRESS)[0] or BRAND,
        "reply_to": _reply_to(),
    }
    # Apps Script answers through a redirect, so follow it. The email has already been sent by then.
    r = httpx.post(_clean(settings.EMAIL_WEBHOOK_URL), json=payload, timeout=30.0, follow_redirects=True)
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError:
        # Google answered with a web page (sign-in / "Sorry, unable to open the file") instead of the script's JSON.
        raise RuntimeError(
            "email relay did not return JSON (got a web page). The EMAIL_WEBHOOK_URL must be the Apps Script web app "
            "URL ending in /exec, deployed with 'Execute as: Me' and 'Who has access: Anyone'."
        ) from None
    if not data.get("ok"):
        err = str(data.get("error"))
        hint = {
            "forbidden": " -- EMAIL_WEBHOOK_SECRET does not match SECRET in the Apps Script (or the script still has the placeholder).",
            "quota": " -- the Gmail account hit its daily sending limit (about 100/day); it resets within 24 hours.",
        }.get(err.split(":")[0], "")
        raise RuntimeError(f"email relay refused the message: {err}{hint}")
    remaining = data.get("remaining")
    if isinstance(remaining, (int, float)):
        (logger.warning if remaining <= 20 else logger.info)("Email relay: %s sends left in today's Gmail quota.", remaining)
    return True


def _resend(to_email: str, subject: str, text_body: str, html_body: str | None) -> bool:
    payload = {"from": settings.EMAIL_FROM_ADDRESS, "to": [to_email], "subject": subject, "text": text_body}
    if html_body:
        payload["html"] = html_body
    if _reply_to():
        payload["reply_to"] = _reply_to()
    r = httpx.post("https://api.resend.com/emails", headers={"Authorization": f"Bearer {_clean(settings.RESEND_API_KEY)}"},
                   json=payload, timeout=10.0)
    r.raise_for_status()
    return True


# ---- Templates -------------------------------------------------------------------------------------------------

def _code_email(to_email: str, subject: str, heading: str, intro: str, code: str, outro: str) -> bool:
    text = f"{heading}\n\n{intro}\n\n    {code}\n\n{outro}{_footer_text()}"
    return send_email(to_email, subject, text, _render_html(heading, intro, code, outro))


def send_password_reset_code(to_email: str, code: str) -> bool:
    minutes = settings.EMAIL_CODE_EXPIRE_MINUTES
    return _code_email(
        to_email, f"{code} is your Forecast password reset code", "Reset your password",
        f"Use this code to reset your Forecast password. It expires in {minutes} minutes.", code,
        "If you didn't ask for this, you can ignore this email - your password won't change.",
    )


def send_change_email_code(to_email: str, code: str) -> bool:
    minutes = settings.EMAIL_CODE_EXPIRE_MINUTES
    return _code_email(
        to_email, f"{code} confirms your new Forecast email", "Confirm your new email",
        f"Enter this code to make this the email on your Forecast account. It expires in {minutes} minutes.", code,
        "If you didn't request this change, ignore this email.",
    )


def send_security_notice(to_email: str, heading: str, message: str) -> bool:
    text = f"{heading}\n\n{message}{_footer_text()}"
    return send_email(to_email, f"Forecast security notice: {heading}", text,
                      _render_html(heading, message, None, "If this wasn't you, reset your password right away."))
