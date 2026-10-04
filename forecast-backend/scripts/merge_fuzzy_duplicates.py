#!/usr/bin/env python3
"""
Interactive, human-confirmed merge tool for NEAR-MISS (not exact) spelling
duplicates -- the output of scripts/find_near_miss_matches.py, turned into
an action instead of just a report. Companion to
scripts/merge_duplicate_players.py (exact clean_gamertag() matches); this
one is for the cosmetic-unicode-variant case (e.g. "HAVOK SwizzY" vs.
"havok swizzуǃ" -- a Cyrillic у, decorative "ǃ") that exact matching
structurally cannot catch.

THIS IS LOWER CONFIDENCE THAN merge_duplicate_players.py. An exact
clean_gamertag() match is proof two rows are the same string; a fuzzy
similarity score is not proof of anything -- two different real
competitors can coincidentally have similarly-styled names. That's why,
unlike the exact-match tool, this one NEVER suggests a default and never
accepts a bare Enter -- you must actively pick a specific candidate by
number for anything to happen. If a needle has no candidate you're
confident in, skip it; nothing is lost by leaving a small, low-impact
one-off LAN stock unmerged.

Safety and mechanics are otherwise identical to merge_duplicate_players.py
(see that script's docstring for the full explanation):
  - Whichever of the two players has more real placements becomes the
    target; the other is merged away IF AND ONLY IF nobody real (not a
    bot, not House) currently holds its shares, has ever ordered it,
    received a dividend from it, or traded it. Otherwise it's left
    completely untouched and flagged for manual review.
  - A safe merge moves OsirionPlayerMapping/PlacementResult/DividendPayout
    rows onto the target (skipping -- and reporting -- any that would
    collide with a placement/payout the target already has for the same
    tournament), deletes the source's own bot/House-only Position/Order
    rows, and deactivates the source with a "[MERGED INTO ...]" gamertag
    marker. If the target had been deactivated (region/year out of
    scope), it's reactivated.

Usage:
    cd forecast-backend
    python3 scripts/merge_fuzzy_duplicates.py                  # dry run:
                                                                 # lists
                                                                 # every
                                                                 # needle's
                                                                 # candidates,
                                                                 # no
                                                                 # prompts,
                                                                 # no writes.
    python3 scripts/merge_fuzzy_duplicates.py --confirm         # interactive:
                                                                 # pick a
                                                                 # candidate
                                                                 # by number
                                                                 # per needle,
                                                                 # or skip.
    python3 scripts/merge_fuzzy_duplicates.py --confirm --threshold 0.9
                                                                 # tighter
                                                                 # threshold
                                                                 # -- fewer,
                                                                 # higher-
                                                                 # confidence
                                                                 # candidates.
"""
from __future__ import annotations

import argparse
import re
import sys
import uuid
from difflib import SequenceMatcher

sys.path.insert(0, ".")

from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.bot import BotProfile  # noqa: E402
from app.models.dividend import DividendLineItem, DividendPayout  # noqa: E402
from app.models.order import Order, Trade  # noqa: E402
from app.models.osirion import OsirionPlayerMapping  # noqa: E402
from app.models.player import Player, Position  # noqa: E402
from app.models.tournament import PlacementResult  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.house_account import HOUSE_ACCOUNT_EMAIL  # noqa: E402
from app.services.osirion_service import clean_gamertag  # noqa: E402

_TOMBSTONE_PREFIX = "[MERGED INTO"


def _real_user_ids(db: Session) -> set:
    bot_ids = {r[0] for r in db.query(BotProfile.user_id).all()}
    house_row = db.query(User.id).filter(User.email == HOUSE_ACCOUNT_EMAIL).one_or_none()
    if house_row is not None:
        bot_ids.add(house_row[0])
    all_user_ids = {r[0] for r in db.query(User.id).all()}
    return all_user_ids - bot_ids


def _placement_count(db: Session, player_id) -> int:
    return db.query(PlacementResult).filter(PlacementResult.player_id == player_id).count()


def _describe(db: Session, p: Player) -> str:
    pcount = _placement_count(db, p.id)
    status = "active" if p.is_active else "INACTIVE (region/year out of scope)"
    return f"id={p.id}  gamertag={p.gamertag!r}  placements={pcount}  status={status}"


def _why_unsafe_to_merge_away(db: Session, player_id, real_user_ids: set) -> str | None:
    real_position = (
        db.query(Position)
        .filter(Position.player_id == player_id, Position.quantity > 0, Position.user_id.in_(real_user_ids))
        .first()
    )
    if real_position is not None:
        holder = db.get(User, real_position.user_id)
        return f"held by a real user ({holder.email if holder else real_position.user_id}, {real_position.quantity} shares)"

    real_order = db.query(Order).filter(Order.player_id == player_id, Order.user_id.in_(real_user_ids)).first()
    if real_order is not None:
        holder = db.get(User, real_order.user_id)
        return f"has an order from a real user ({holder.email if holder else real_order.user_id})"

    real_dividend = (
        db.query(DividendPayout)
        .join(DividendLineItem, DividendLineItem.payout_id == DividendPayout.id)
        .filter(DividendPayout.player_id == player_id, DividendLineItem.user_id.in_(real_user_ids))
        .first()
    )
    if real_dividend is not None:
        return "has a historical dividend payout that paid a real user"

    real_trade = (
        db.query(Trade)
        .filter(Trade.player_id == player_id, (Trade.buyer_user_id.in_(real_user_ids)) | (Trade.seller_user_id.in_(real_user_ids)))
        .first()
    )
    if real_trade is not None:
        return "has a historical trade involving a real user (even if they don't currently hold shares)"

    return None


def _merge_player(db: Session, source: Player, target: Player) -> dict:
    summary = {"mappings_moved": 0, "placements_moved": 0, "placements_conflicted": 0,
               "dividends_moved": 0, "dividends_conflicted": 0, "target_reactivated": False}

    for mapping in db.query(OsirionPlayerMapping).filter(OsirionPlayerMapping.player_id == source.id).all():
        mapping.player_id = target.id
        summary["mappings_moved"] += 1

    target_tournament_ids = {
        r[0] for r in db.query(PlacementResult.tournament_id).filter(PlacementResult.player_id == target.id).all()
    }
    for placement in db.query(PlacementResult).filter(PlacementResult.player_id == source.id).all():
        if placement.tournament_id in target_tournament_ids:
            summary["placements_conflicted"] += 1
            continue
        placement.player_id = target.id
        target_tournament_ids.add(placement.tournament_id)
        summary["placements_moved"] += 1

    target_dividend_tournament_ids = {
        r[0] for r in db.query(DividendPayout.tournament_id).filter(DividendPayout.player_id == target.id).all()
    }
    for payout in db.query(DividendPayout).filter(DividendPayout.player_id == source.id).all():
        if payout.tournament_id in target_dividend_tournament_ids:
            summary["dividends_conflicted"] += 1
            continue
        payout.player_id = target.id
        target_dividend_tournament_ids.add(payout.tournament_id)
        summary["dividends_moved"] += 1

    db.query(Position).filter(Position.player_id == source.id).delete(synchronize_session=False)
    db.query(Order).filter(Order.player_id == source.id).delete(synchronize_session=False)

    merged_label = f"{_TOMBSTONE_PREFIX} {target.gamertag}] {source.gamertag}"
    source.gamertag = merged_label[:100]
    source.is_active = False

    if not target.is_active:
        target.is_active = True
        summary["target_reactivated"] = True

    db.commit()
    return summary


_TAG_RE = re.compile(r"^\[[^\]]*\]\s*")


def _find_candidates(needle: Player, haystack: list[tuple[Player, str]], threshold: float) -> list[tuple[float, Player]]:
    needle_core = clean_gamertag(needle.gamertag).lower()
    candidates = []
    for other, other_core in haystack:
        if other.id == needle.id or other_core == needle_core:
            continue
        if other.gamertag.startswith(_TOMBSTONE_PREFIX):
            continue
        ratio = SequenceMatcher(None, needle_core, other_core).ratio()
        if ratio >= threshold:
            candidates.append((ratio, other))
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[:5]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--threshold", type=float, default=0.82, help="Minimum similarity ratio (0-1). Default 0.82.")
    parser.add_argument("--confirm", action="store_true",
                         help="Interactively confirm and perform merges. Without this flag, it's a dry run that "
                              "only lists candidates -- no prompts, no writes.")
    args = parser.parse_args()

    db = SessionLocal()
    # Without this, SQLAlchemy's default expire-on-commit behavior marks every object already
    # loaded in this session (including every Player row in `haystack` below, which can be
    # 80k+ rows) as expired after each db.commit() inside _merge_player. The next time any of
    # their attributes gets touched (e.g. iterating `haystack` for the following needle), each
    # expired object triggers its own individual round-trip query to re-fetch itself -- one at a
    # time, for the entire haystack. On a large table that looks exactly like a frozen script;
    # it's actually tens of thousands of sequential single-row SELECTs (confirmed the hard way in
    # scripts/merge_qualified_duplicates.py). Disabling expire-on-commit keeps the in-memory
    # snapshot valid across commits.
    db.expire_on_commit = False
    try:
        real_user_ids = _real_user_ids(db)
        all_players = db.query(Player).filter(~Player.gamertag.startswith(_TOMBSTONE_PREFIX)).all()
        haystack = [(p, clean_gamertag(p.gamertag).lower()) for p in all_players]

        needles = [p for p in all_players if p.is_active and p.gamertag.startswith("[") and len(p.placement_results) <= 2]

        if not needles:
            print("No active LAN-tagged, low-placement players found -- nothing to check.")
            return

        print(f"Checking {len(needles)} candidate(s) against {len(all_players)} total player(s), threshold={args.threshold}.\n")

        for i, needle in enumerate(needles, start=1):
            if needle.gamertag.startswith(_TOMBSTONE_PREFIX):
                continue  # merged away earlier in this same run, as someone else's source

            candidates = _find_candidates(needle, haystack, args.threshold)
            if not candidates:
                continue

            print("=" * 100)
            print(f"[{i}/{len(needles)}] Needle: {_describe(db, needle)}")
            for idx, (ratio, cand) in enumerate(candidates, start=1):
                print(f"    [{idx}] ratio={ratio:.2f}  {_describe(db, cand)}")

            if not args.confirm:
                continue

            choice = input(
                "\n  Which one is genuinely the SAME real person? Enter a number, a player id, "
                "'s' to skip, or 'q' to quit: "
            ).strip()
            if choice.lower() == "q":
                print("Quitting -- no further needles processed.")
                return
            if choice.lower() == "s" or not choice:
                print("  Skipped.")
                continue

            chosen = None
            if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                chosen = candidates[int(choice) - 1][1]
            elif _looks_like_uuid(choice):
                chosen = db.get(Player, uuid.UUID(choice))

            if chosen is None:
                print("  Not a valid choice -- skipping this needle.")
                continue

            if chosen.gamertag.startswith(_TOMBSTONE_PREFIX):
                print("  That candidate was already merged elsewhere earlier in this run -- skipping.")
                continue

            needle_count = _placement_count(db, needle.id)
            chosen_count = _placement_count(db, chosen.id)
            if chosen_count >= needle_count:
                target, source = chosen, needle
            else:
                target, source = needle, chosen

            reason = _why_unsafe_to_merge_away(db, source.id, real_user_ids)
            if reason is not None:
                print(f"  SKIPPED -- {source.gamertag!r} {reason}. Left completely untouched.")
                continue

            summary = _merge_player(db, source, target)
            reactivated_note = " (target was inactive -- reactivated)" if summary["target_reactivated"] else ""
            print(f"  Merged {source.id} ({source.gamertag!r}) into {target.id} ({target.gamertag!r}){reactivated_note}: "
                  f"{summary['mappings_moved']} mapping(s), {summary['placements_moved']} placement(s) moved "
                  f"({summary['placements_conflicted']} skipped as duplicate tournament), "
                  f"{summary['dividends_moved']} dividend payout(s) moved "
                  f"({summary['dividends_conflicted']} skipped as duplicate tournament).")

        if not args.confirm:
            print("\n\nDry run only -- nothing changed. Re-run with --confirm to interactively confirm and apply merges.")
    finally:
        db.close()


def _looks_like_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    main()
