"""
Tiny pluggable email sender. Right now the only real caller is
app/services/password_reset_service.py, but this is written generic
enough to reuse for any future transactional email.

Two providers today:
- "console" (default, settings.EMAIL_PROVIDER): sends nothing -- just logs
  the message (including the actual reset link) at INFO level. This means
  password reset "works" today in the sense that a token is generated,
  stored, and would validate -- but nobody actually receives an email
  yet. Until a real provider is configured, the practical way to recover
  an account is: the account owner (you, initially) reads the reset link
  out of the server logs (Render's dashboard -> Logs) and relays it to
  whoever asked. Not scalable, but zero setup, and safe (the link itself
  is exactly as secret as it would be in a real email).
- "resend" (resend.com): a real HTTP API call. Sign up, verify a sender
  (or just use the shared onboarding@resend.dev sender for low volume/
  testing), create an API key, and set RESEND_API_KEY + EMAIL_PROVIDER=resend.
  No code changes needed -- see README_SETUP.md.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("forecast.email")


def send_password_reset_email(to_email: str, reset_link: str) -> None:
    subject = "Reset your Forecast password"
    text_body = (
        f"Someone (hopefully you) asked to reset the password on your Forecast account.\n\n"
        f"Reset it here (this link expires in {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes):\n"
        f"{reset_link}\n\n"
        f"If you didn't request this, you can safely ignore this email -- your password won't change."
    )

    if settings.EMAIL_PROVIDER == "resend":
        _send_via_resend(to_email, subject, text_body, reset_link)
    else:
        _send_via_console(to_email, subject, text_body, reset_link)


def _send_via_console(to_email: str, subject: str, text_body: str, reset_link: str) -> None:
    logger.info(
        "EMAIL_PROVIDER=console -- not actually sending an email. "
        "Password reset requested for %s. Reset link (share this with the user manually "
        "for now, or configure a real EMAIL_PROVIDER -- see app/services/email_service.py): %s",
        to_email,
        reset_link,
    )


def _send_via_resend(to_email: str, subject: str, text_body: str, reset_link: str) -> None:
    if not settings.RESEND_API_KEY:
        logger.error(
            "EMAIL_PROVIDER=resend but RESEND_API_KEY is not set -- falling back to logging the "
            "link instead of sending nothing silently. Set RESEND_API_KEY to actually send email."
        )
        _send_via_console(to_email, subject, text_body, reset_link)
        return

    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json={
                "from": settings.EMAIL_FROM_ADDRESS,
                "to": [to_email],
                "subject": subject,
                "text": text_body,
            },
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        # A failed reset email should never surface as a 500 to the
        # requester (see password_reset_service.py -- the endpoint always
        # returns a generic "if that email exists" response either way),
        # but it's worth knowing about in the logs.
        logger.exception("Failed to send password reset email via Resend to %s", to_email)
