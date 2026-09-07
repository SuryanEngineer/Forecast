#!/usr/bin/env python3
"""
Promote an existing user (registered via POST /api/v1/auth/register) to
ADMIN. There's no API endpoint for this on purpose -- an endpoint that
grants admin rights would itself need an admin to call it (or would need
to be unprotected, which is worse). Run this directly against your
database instead, once, for whichever account should be the first admin.

Usage:
    cd forecast-backend
    python3 scripts/make_admin.py you@example.com
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/make_admin.py <email>")
        sys.exit(1)

    email = sys.argv[1]
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is None:
            print(f"No user found with email {email}. Register that account first via POST /api/v1/auth/register.")
            sys.exit(1)
        user.role = UserRole.ADMIN
        db.commit()
        print(f"{email} is now an admin.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
