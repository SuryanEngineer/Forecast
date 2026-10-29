#!/usr/bin/env python3
"""List admin accounts (read-only).   python3 scripts/list_admins.py"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        rows = db.query(User).filter(User.role == UserRole.ADMIN).order_by(User.created_at).all()
        for u in rows:
            print(f"{u.email:<40} {u.display_name:<22} active={u.is_active}  created={u.created_at:%Y-%m-%d}")
        print(f"\n{len(rows)} admin(s)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
