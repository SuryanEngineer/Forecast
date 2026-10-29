"""
Transactional email. Providers (settings.EMAIL_PROVIDER):

- "console" (default): nothing is sent; the message -- including the one-time code -- is logged. Fine for local dev
  (read the code in the uvicorn terminal). Never use for real users.
- "smtp": any SMTP server (Zoho, Google Workspace, Brevo, Mailgun, Amazon SES...). Set SMTP_HOST/PORT/USERNAME/PASSWORD.
- "resend": resend.com HTTP API (RESEND_API_KEY).

Every email is multipart (plain text + branded HTML), has a From of EMAIL_FROM_ADDRESS (use a no-reply address on your
own domain), a Reply-To of EMAIL_REPLY_TO/SUPPORT_EMAIL when set, and a footer telling the reader why they got it.
Sending never raises into the request path: failures are logged and reported via the boolean return value.
"""
from __future__ import annotations

import html
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

import httpx

from app.core.config import settings

logger = logging.getLogger("forecast.email")

BRAND = "Forecast"


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


def send_email(to_email: str, subject: str, text_body: str, html_body: str | None = None) -> bool:
    provider = (settings.EMAIL_PROVIDER or "console").lower()
    try:
        if provider == "smtp":
            if not settings.SMTP_HOST:
                logger.error("EMAIL_PROVIDER=smtp but SMTP_HOST is not set -- logging instead.")
                return _console(to_email, subject, text_body)
            return _smtp(to_email, subject, text_body, html_body)
        if provider == "resend":
            if not settings.RESEND_API_KEY:
                logger.error("EMAIL_PROVIDER=resend but RESEND_API_KEY is not set -- logging instead.")
                return _console(to_email, subject, text_body)
            return _resend(to_email, subject, text_body, html_body)
    except Exception:
        logger.exception("Failed to send email %r to %s via %s", subject, to_email, provider)
        return False
    return _console(to_email, subject, text_body)


def _console(to_email: str, subject: str, text_body: str) -> bool:
    logger.warning("EMAIL_PROVIDER=console -- NOT sending. To: %s | Subject: %s\n%s", to_email, subject, text_body)
    return True


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
    if settings.SMTP_USE_SSL:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15, context=ssl.create_default_context()) as s:
            if settings.SMTP_USERNAME:
                s.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
            s.send_message(msg, from_addr=sender)
    else:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as s:
            s.starttls(context=ssl.create_default_context())
            if settings.SMTP_USERNAME:
                s.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
            s.send_message(msg, from_addr=sender)
    return True


def _resend(to_email: str, subject: str, text_body: str, html_body: str | None) -> bool:
    payload = {"from": settings.EMAIL_FROM_ADDRESS, "to": [to_email], "subject": subject, "text": text_body}
    if html_body:
        payload["html"] = html_body
    if _reply_to():
        payload["reply_to"] = _reply_to()
    r = httpx.post("https://api.resend.com/emails", headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
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
