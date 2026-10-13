#!/usr/bin/env python3
"""
Give the existing bot accounts realistic usernames (replaces "Momentum Bot #14"-style names).

Only bot users (those with a BotProfile row) are touched, and only their display_name -- emails, wallets, positions and
history are unchanged. By default only bots that still carry a generated "... Bot #N" name are renamed; use --all to
rename every bot. Dry run unless --confirm.

    python3 scripts/rename_bots.py             # preview
    python3 scripts/rename_bots.py --confirm   # apply
"""
from __future__ import annotations

import argparse
import random
import re
import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.bot import BotProfile  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.bot_names import generate_username  # noqa: E402

_OLD_STYLE = re.compile(r"\bBot #\d+$", re.IGNORECASE)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--all", action="store_true", help="Rename every bot, not just old-style 'Bot #N' names.")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        bot_ids = [uid for (uid,) in db.query(BotProfile.user_id).all()]
        users = db.query(User).filter(User.id.in_(bot_ids)).order_by(User.created_at.asc()).all() if bot_ids else []
        targets = [u for u in users if args.all or _OLD_STYLE.search(u.display_name or "")]
        # Names already in use by anyone not being renamed stay reserved.
        renaming = {u.id for u in targets}
        taken = {(n or "").lower() for uid, n in db.query(User.id, User.display_name).all() if uid not in renaming}
        rng = random.Random()
        for u in targets:
            new = generate_username(rng, taken)
            print(f"  {u.display_name!r:32} -> {new!r}")
            if args.confirm:
                u.display_name = new
        print(f"\n{len(targets)} of {len(users)} bot(s) {'renamed' if args.confirm else 'would be renamed'}.")
        if args.confirm:
            db.commit()
        else:
            print("Dry run only -- re-run with --confirm to apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
