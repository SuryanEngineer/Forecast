#!/usr/bin/env python3
"""
Send one real test email through your configured provider, so you can confirm delivery, the "From" name, the
Reply-To, and that it lands in the inbox (not spam) BEFORE real users depend on it.

    cd forecast-backend
    python3 scripts/send_test_email.py you@gmail.com
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.core.config import settings  # noqa: E402
from app.services import email_service  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python3 scripts/send_test_email.py you@example.com")
    to = sys.argv[1]
    print(f"Provider: {settings.EMAIL_PROVIDER}   From: {settings.EMAIL_FROM_ADDRESS}   Reply-To: {settings.EMAIL_REPLY_TO or settings.SUPPORT_EMAIL or '(none)'}")
    if settings.EMAIL_PROVIDER == "console":
        print("EMAIL_PROVIDER is 'console' -- nothing will really be sent (the message is just logged). Set it to resend/smtp first.")
    ok = email_service.send_password_reset_code(to, "123456")
    print("Sent." if ok else "FAILED -- see the error above / logs.")


if __name__ == "__main__":
    main()
