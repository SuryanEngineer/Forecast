#!/usr/bin/env python3
"""
Interactive, human-confirmed merge tool for the duplicate Player groups
scripts/find_duplicate_players.py reports (same clean_gamertag() exact-
collision grouping as that script's Pass 1 -- see that script's module
docstring for why these duplicates exist: Osirion reporting a different
accountId for the same real competitor across different LAN circuits).

This is the one script in this folder that DOES merge/move real data --
but only ever the kind of data that's safe to move automatically, and
never without you confirming the target first. For each duplicate group:

  1. Prints every player in the group (gamertag, placements, most recent
     tournament, accountId) and suggests a default target -- whichever
     player has the most real placements (the "home" identity most of
     these turn out to have, e.g. the one with 14 FNCS Division Practice
     placements vs. a one-off LAN appearance with 1).
  2. Asks you to confirm the target, type a different player id from the
     group, or skip the group entirely. Nothing happens to a group you
     skip.
  3. For every OTHER player in the group (the ones being merged away),
     checks whether it's SAFE to auto-merge:
       - no Position with quantity > 0 held by a real (non-bot, non-House)
         user
       - no Order (any status) ever placed by a real user on this player
       - no DividendPayout on this player whose line items paid a real user
     If ANY of those is true, this specific player is left COMPLETELY
     UNTOUCHED and flagged for manual review -- real share ownership,
     real trade history, or a real historical payout is exactly what this
     script will never move on its own. The group's OTHER (safe) members,
     if any, still get merged.
  4. For a safe-to-merge player, moves its OsirionPlayerMapping rows (so
     future Osirion syncs of that accountId land on the target going
     forward), its PlacementResult rows (skipping -- and reporting -- any
     that would collide with a placement the target already has for the
     same tournament, since (tournament_id, player_id) must stay unique),
     and its DividendPayout rows (same collision handling). Its own
     House/bot-only Position and Order rows are deleted (there's nothing
     real left to preserve once the safety check above has passed). The
     merged-away player is then DEACTIVATED and its gamertag is prefixed
     with "[MERGED INTO <target gamertag>]" so it's unambiguous in the
     database and never resurfaces in a future duplicate scan (which only
     looks at active players).

Nothing here is undoable by re-running the script -- a merged-away player
is deactivated, not deleted, so its full history is still inspectable.

Usage:
    cd forecast-backend
    python3 scripts/merge_duplicate_players.py            # dry run: shows
                                                            # every group,
                                                            # the suggested
                                                            # target, and
                                                            # the safety
                                                            # check result
                                                            # for each
                                                            # other member
                                                            # -- no prompts,
                                                            # no writes.
    python3 scripts/merge_duplicate_players.py --confirm   # interactive:
                                                            # asks you to
                                                            # confirm/choose
                                                            # a target (or
                                                            # skip) per
                                                            # group, then
                                                            # actually
                                                            # performs the
                                                            # safe merges.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from collections import defaultdict

sys.path.insert(0, ".")

from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.bot import BotProfile  # noqa: E402
from app.models.dividend import DividendLineItem, DividendPayout  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.osirion import OsirionPlayerMapping  # noqa: E402
from app.models.player import Player, Position  # noqa: E402
from app.models.tournament import PlacementResult, Tournament  # noqa: E402
from app.models.order import Trade  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.house_account import HOUSE_ACCOUNT_EMAIL  # noqa: E402
from app.services.osirion_service import clean_gamertag  # noqa: E402


def _real_user_ids(db: Session) -> set:
    """Every user id that is NOT a bot and NOT the House account -- the
    exact same exclusion pattern used by every cleanup script in this
    folder."""
    bot_ids = {r[0] for r in db.query(BotProfile.user_id).all()}
    house_row = db.query(User.id).filter(User.email == HOUSE_ACCOUNT_EMAIL).one_or_none()
    if house_row is not None:
        bot_ids.add(house_row[0])
    all_user_ids = {r[0] for r in db.query(User.id).all()}
    return all_user_ids - bot_ids


def _build_groups(db: Session) -> list[list[Player]]:
    """Groups by clean_gamertag() across BOTH active and inactive players
    (not just active, unlike find_duplicate_players.py) -- a player who
    made FNCS Global Championship / EWC almost certainly has real regular-
    season FNCS Division history somewhere, but if that history is from a
    region outside the current NAC/EU scope, scripts/deactivate_out_of_
    scope_players.py would have already deactivated that "home" identity
    while the LAN appearance (region-exempt) stayed active -- leaving
    exactly this script's earlier active-only scan blind to it. Excludes
    any gamertag already carrying a "[MERGED INTO ...]" tombstone marker
    (from a previous run of this script) -- clean_gamertag() strips ALL
    bracket segments, so a tombstone's own cleaned name collapses back to
    its original one and would otherwise look like a fresh duplicate of
    the player it was already merged into."""
    players = db.query(Player).filter(~Player.gamertag.startswith("[MERGED INTO")).all()
    groups: dict = defaultdict(list)
    for p in players:
        groups[clean_gamertag(p.gamertag).lower()].append(p)
    # Only groups with at least one currently-active member are worth
    # surfacing -- a group that's entirely inactive has nothing bearing on
    # the current roster.
    return [g for g in groups.values() if len(g) > 1 and any(p.is_active for p in g)]


def _placement_count(db: Session, player_id) -> int:
    return db.query(PlacementResult).filter(PlacementResult.player_id == player_id).count()


def _describe(db: Session, p: Player) -> str:
    pcount = _placement_count(db, p.id)
    status = "active" if p.is_active else "INACTIVE (region/year out of scope)"
    return f"id={p.id}  gamertag={p.gamertag!r}  placements={pcount}  status={status}  region={p.region}"


def _why_unsafe_to_merge_away(db: Session, player_id, real_user_ids: set) -> str | None:
    """Returns a human-readable reason this player can NOT be safely
    merged away automatically, or None if it's safe. Checked in order so
    the first real reason found is what gets reported."""
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
        .filter(
            Trade.player_id == player_id,
            (Trade.buyer_user_id.in_(real_user_ids)) | (Trade.seller_user_id.in_(real_user_ids)),
        )
        .first()
    )
    if real_trade is not None:
        return "has a historical trade involving a real user (even if they don't currently hold shares)"

    return None


def _merge_player(db: Session, source: Player, target: Player) -> dict:
    """Moves everything safe to move from `source` into `target`, then
    deactivates `source`. Assumes the caller already confirmed `source`
    passed `_why_unsafe_to_merge_away` (returned None)."""
    summary = {"mappings_moved": 0, "placements_moved": 0, "placements_conflicted": 0,
               "dividends_moved": 0, "dividends_conflicted": 0}

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

    # Only bot/House positions and orders can still exist here (the safety
    # check already ruled out any real-user Position/Order) -- nothing
    # real to preserve, just noise on a stock that's about to be retired.
    db.query(Position).filter(Position.player_id == source.id).delete(synchronize_session=False)
    db.query(Order).filter(Order.player_id == source.id).delete(synchronize_session=False)

    merged_label = f"[MERGED INTO {target.gamertag}] {source.gamertag}"
    source.gamertag = merged_label[:100]
    source.is_active = False

    # The target is, by definition, a confirmed currently-relevant real
    # competitor (the whole premise of this merge) -- if it had been
    # deactivated earlier (e.g. its own regular-season history is from a
    # region outside the current NAC/EU scope, while this LAN appearance
    # is region-exempt), reactivate it now rather than leaving a
    # newly-consolidated, richer-history identity sitting inactive.
    if not target.is_active:
        summary["target_reactivated"] = True
        target.is_active = True
    else:
        summary["target_reactivated"] = False

    db.commit()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--confirm", action="store_true",
                         help="Interactively confirm and actually perform merges. Without this flag, it's a "
                              "non-interactive dry run that only shows the plan and safety checks.")
    args = parser.parse_args()

    db = SessionLocal()
    # Keeps already-loaded group members valid across each merge's db.commit() instead of
    # expiring them (which would force an individual re-fetch query per player on next access) --
    # see the identical comment/incident in scripts/merge_fuzzy_duplicates.py for the full story.
    # Low-impact here given how few players are in a duplicate group, but cheap and consistent.
    db.expire_on_commit = False
    try:
        real_user_ids = _real_user_ids(db)
        groups = _build_groups(db)

        if not groups:
            print("No duplicate-gamertag groups found among active players. Nothing to do.")
            return

        print(f"Found {len(groups)} duplicate group(s).\n")

        for i, group in enumerate(groups, start=1):
            group_sorted = sorted(group, key=lambda p: _placement_count(db, p.id), reverse=True)
            suggested_target = group_sorted[0]

            print("=" * 100)
            print(f"Group {i}/{len(groups)}:")
            for p in group_sorted:
                marker = "  <-- suggested target (most placements)" if p.id == suggested_target.id else ""
                print(f"    - {_describe(db, p)}{marker}")

            if not args.confirm:
                for p in group_sorted:
                    if p.id == suggested_target.id:
                        continue
                    reason = _why_unsafe_to_merge_away(db, p.id, real_user_ids)
                    if reason is None:
                        print(f"    Would merge {p.id} into {suggested_target.id} -- safe (no real holdings/orders/payouts).")
                    else:
                        print(f"    Would SKIP merging {p.id} -- {reason}.")
                continue

            choice = input(
                f"\n  Merge into which id? [Enter for suggested {suggested_target.id}] "
                "('s' to skip this group, 'q' to quit): "
            ).strip()
            if choice.lower() == "q":
                print("Quitting -- no further groups processed.")
                return
            if choice.lower() == "s":
                print("  Skipped.")
                continue

            if choice:
                target = db.get(Player, uuid.UUID(choice)) if _looks_like_uuid(choice) else None
                if target is None or target.id not in {p.id for p in group}:
                    print("  Not a valid id from this group -- skipping this group.")
                    continue
            else:
                target = suggested_target

            for p in group_sorted:
                if p.id == target.id:
                    continue
                reason = _why_unsafe_to_merge_away(db, p.id, real_user_ids)
                if reason is not None:
                    print(f"  SKIPPED {p.id} ({p.gamertag!r}) -- {reason}. Left completely untouched.")
                    continue
                summary = _merge_player(db, p, target)
                reactivated_note = " (target was inactive -- reactivated)" if summary["target_reactivated"] else ""
                print(f"  Merged {p.id} ({p.gamertag!r}) into {target.id} ({target.gamertag!r}){reactivated_note}: "
                      f"{summary['mappings_moved']} mapping(s), {summary['placements_moved']} placement(s) moved "
                      f"({summary['placements_conflicted']} skipped as duplicate tournament), "
                      f"{summary['dividends_moved']} dividend payout(s) moved "
                      f"({summary['dividends_conflicted']} skipped as duplicate tournament).")

        if not args.confirm:
            print("\n\nDry run only -- nothing changed. Re-run with --confirm to interactively confirm and apply merges.")
    finally:
        db.close()


def _looks_like_uuid(value: str) -> bool:
    import uuid
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    main()
