#!/usr/bin/env python3
"""
Broader, season-aware version of merge_fuzzy_duplicates.py / merge_qualified_duplicates.py,
built for the stragglers neither of those two could resolve.

Why those two aren't enough:
  - merge_fuzzy_duplicates.py compares a needle's gamertag against ALL ~89k players by pure
    spelling similarity. If the needle's real "home" identity has a gamertag that doesn't
    closely resemble the LAN tag (team change, rebrand, totally different handle), it never
    crosses the ratio threshold and never even appears as a candidate -- no matter how many
    real placements it has. Ranking-by-placements only helps among whatever happens to pass
    the string-similarity bar first, which in practice is often just other thin duplicates,
    not the real pro.
  - merge_qualified_duplicates.py fixes that for FNCSGC/EWC-tagged needles by restricting the
    candidate pool to players with a REAL placement in a specifically GC-qualifying tournament
    (named "FNCS Division 1" or "Last Chance") within the needle's own chapter window -- but
    that pool is narrow by design (only those two kinds of tournament). A needle whose
    regular-season identity never happened to place in one of those specific qualifying rounds
    here (wrong region tracked, different qualifying path, etc.) gets zero candidates there and
    falls through to merge_fuzzy_duplicates.py's weaker full-database search.

This script closes that gap with a different, broader signal: instead of requiring a
QUALIFYING placement, it only requires the candidate to have been an ACTIVE COMPETITOR during
the SAME CHAPTER -- i.e. any real placement (any tournament, any region) in the 365 days
leading up to the needle's own LAN appearance. A pro who makes Globals or EWC almost always has
a trail of regular Cash Cup / Division placements across that season somewhere in this
database, even if none of them happen to be the specific "Division 1" / "Last Chance" rounds
the narrower script requires. Region is deliberately NOT restricted (same reasoning as the GC
search: qualifiers feed in from every region), and the real LAN tournament's own `region` field
is usually a generic venue marker (e.g. "ONSITE"), not the player's competitive region, so
region can't be used as a filter here anyway.

Within that season-restricted pool, gamertag similarity is used as a LOOSE relevance filter
(default threshold 0.5, much looser than merge_fuzzy_duplicates.py's 0.82) rather than the
primary signal, and candidates are ranked by real placement count first, similarity second --
the opposite priority order from a pure fuzzy-match tool. Each candidate's most recent
tournament is shown too, so you have real context (not just a name and a number) to judge
whether it's actually the same person.

This is the lowest-confidence tool in this family (season overlap + loose spelling is weaker
evidence than an exact match or a qualifying-tournament match), so exactly like
merge_fuzzy_duplicates.py it marks a suggested default (most placements) but still makes you
look at the full candidate list -- including region/date context -- before accepting it.

Mechanics (target selection, safety checks, tombstoning, reactivation) are identical to the
other two scripts in this family -- see merge_duplicate_players.py's docstring for the full
explanation.

Usage:
    cd forecast-backend
    python3 scripts/merge_season_duplicates.py                  # dry run: lists every
                                                                    needle's candidates, no
                                                                    prompts, no writes.
    python3 scripts/merge_season_duplicates.py --confirm         # interactive: accept the
                                                                    suggested candidate with
                                                                    Enter, pick a different
                                                                    number, type a raw player
                                                                    id, 's' to skip, or 'q' to
                                                                    quit.
    python3 scripts/merge_season_duplicates.py --confirm --threshold 0.4
                                                                    # even looser relevance
                                                                    filter within the season
                                                                    pool -- more candidates
                                                                    per needle to choose from.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timedelta
from difflib import SequenceMatcher

sys.path.insert(0, ".")

from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.bot import BotProfile  # noqa: E402
from app.models.dividend import DividendLineItem, DividendPayout  # noqa: E402
from app.models.order import Order, Trade  # noqa: E402
from app.models.osirion import OsirionPlayerMapping  # noqa: E402
from app.models.player import Player, Position  # noqa: E402
from app.models.tournament import PlacementResult, Tournament  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.house_account import HOUSE_ACCOUNT_EMAIL  # noqa: E402
from app.services.osirion_service import clean_gamertag  # noqa: E402

_TOMBSTONE_PREFIX = "[MERGED INTO"
_CHAPTER_LOOKBACK = timedelta(days=365)
_MAX_CANDIDATES_SHOWN = 10


def _real_user_ids(db: Session) -> set:
    bot_ids = {r[0] for r in db.query(BotProfile.user_id).all()}
    house_row = db.query(User.id).filter(User.email == HOUSE_ACCOUNT_EMAIL).one_or_none()
    if house_row is not None:
        bot_ids.add(house_row[0])
    all_user_ids = {r[0] for r in db.query(User.id).all()}
    return all_user_ids - bot_ids


def _placement_count(db: Session, player_id) -> int:
    return db.query(PlacementResult).filter(PlacementResult.player_id == player_id).count()


def _most_recent_tournament(db: Session, player_id) -> str:
    row = (
        db.query(Tournament.name, Tournament.region, Tournament.start_time)
        .join(PlacementResult, PlacementResult.tournament_id == Tournament.id)
        .filter(PlacementResult.player_id == player_id)
        .order_by(Tournament.start_time.desc().nullslast())
        .first()
    )
    if row is None:
        return "no tracked placements"
    name, region, start_time = row
    when = start_time.date() if start_time else "unknown date"
    return f"{name!r} (region={region}, {when})"


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


def _needle_chapter_window(db: Session, needle_player: Player) -> tuple[datetime | None, datetime | None]:
    """Anchored to the needle's OWN tracked tournament(s) -- the LAN placement that gave it its
    tag. Unlike merge_qualified_duplicates.py, this is computed from ANY of the needle's
    placements, not just qualifying-tournament ones, since the whole point here is to not
    require a qualifying-tournament placement at all."""
    rows = (
        db.query(Tournament.start_time)
        .join(PlacementResult, PlacementResult.tournament_id == Tournament.id)
        .filter(PlacementResult.player_id == needle_player.id, Tournament.start_time.isnot(None))
        .all()
    )
    start_times = [r[0] for r in rows]
    if not start_times:
        return None, None
    anchor = max(start_times)
    return anchor - _CHAPTER_LOOKBACK, anchor


def _season_player_ids(db: Session, window: tuple[datetime | None, datetime | None]) -> set | None:
    """Every player with a real placement (any tournament, any region) inside the window.
    Returns None if the window couldn't be determined (needle has no dated placement) --
    callers should fall back to the full haystack in that case rather than returning nothing."""
    window_start, window_end = window
    if window_start is None:
        return None
    rows = (
        db.query(PlacementResult.player_id)
        .join(Tournament, Tournament.id == PlacementResult.tournament_id)
        .filter(Tournament.start_time >= window_start, Tournament.start_time <= window_end)
        .distinct()
        .all()
    )
    return {r[0] for r in rows}


def _find_candidates(
    db: Session, needle: Player, haystack: list[tuple[Player, str]], threshold: float
) -> list[tuple[float, Player]]:
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
    # Rank by similarity first, placement count second. Ranking by placement count first (an
    # earlier version of this script did that) actively misleads: within a season pool, ANY two
    # players who happen to share a team tag (duo teammates, e.g. "[FNCSGC26] twis boltz" and
    # "[FNCSGC26] twis acorn" are almost certainly two DIFFERENT real people, not duplicates) can
    # cross the similarity floor just from that shared prefix, and the one with the most
    # placements would always win regardless of whether the rest of the name matches at all --
    # e.g. ranking 'T1 demuś 10' (ratio 0.53, 16 placements) above 'T1 darmboss' (ratio 0.78, 12
    # placements) as the suggested match for needle '[EWC2026] T1 darm', which is backwards.
    # Similarity-first means the needle's own distinctive name (not just its team tag) has to
    # actually match for a candidate to rank highly; placement count remains visible and still
    # matters for judging which direction to merge, just not as the primary sort.
    candidates.sort(key=lambda t: (t[0], _placement_count(db, t[1].id)), reverse=True)
    return candidates[:_MAX_CANDIDATES_SHOWN]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--threshold", type=float, default=0.5,
                         help="Minimum similarity ratio (0-1) used only as a loose relevance filter within the "
                              "season-restricted pool -- not the primary ranking signal. Default 0.5 (much looser "
                              "than merge_fuzzy_duplicates.py's 0.82), since the season/chapter restriction is what "
                              "actually does the narrowing here.")
    parser.add_argument("--confirm", action="store_true",
                         help="Interactively confirm and perform merges. Without this flag, it's a dry run that "
                              "only lists candidates -- no prompts, no writes.")
    args = parser.parse_args()

    db = SessionLocal()
    # See merge_qualified_duplicates.py for why this matters: without it, SQLAlchemy expires
    # every loaded Player after each commit, and re-touching any of the ~89k rows in
    # full_haystack afterward triggers its own individual re-fetch query.
    db.expire_on_commit = False
    try:
        real_user_ids = _real_user_ids(db)

        all_players = db.query(Player).filter(~Player.gamertag.startswith(_TOMBSTONE_PREFIX)).all()
        full_haystack = [(p, clean_gamertag(p.gamertag).lower()) for p in all_players]

        needles = [p for p in all_players if p.is_active and p.gamertag.startswith("[") and len(p.placement_results) <= 2]

        if not needles:
            print("No active LAN-tagged, low-placement players found -- nothing to check.")
            return

        print(f"Checking {len(needles)} candidate(s), threshold={args.threshold} (loose relevance filter only).\n")

        for i, needle in enumerate(needles, start=1):
            if needle.gamertag.startswith(_TOMBSTONE_PREFIX):
                continue  # merged away earlier in this same run, as someone else's source

            window = _needle_chapter_window(db, needle)
            season_ids = _season_player_ids(db, window)
            if season_ids is None:
                haystack = full_haystack
                label = "ALL PLAYERS (needle has no dated tournament on record, so its chapter couldn't be determined)"
            else:
                haystack = [(p, core) for p, core in full_haystack if p.id in season_ids]
                label = (f"SAME-CHAPTER ACTIVE COMPETITORS (any real placement, any tournament, any region, "
                         f"between {window[0].date()} and {window[1].date()}) -- {len(season_ids)} player(s) in pool")

            candidates = _find_candidates(db, needle, haystack, args.threshold)

            print("=" * 100)
            print(f"[{i}/{len(needles)}] Needle: {_describe(db, needle)}")
            print(f"    Pool: {label}")
            if not candidates:
                print("    No candidates found, even at this loose threshold -- real evidence this player's "
                      "regular-season identity isn't tracked in this database at all (not a search gap).")
                continue

            # Candidates are already sorted similarity-first -- the suggested pick is simply the
            # top of that list, same as merge_fuzzy_duplicates.py. Still shown with placement
            # count and "last seen" context so you can sanity-check it's a real identity and not
            # just a coincidentally-similar teammate.
            suggested_idx = 1
            suggested_candidate = candidates[0][1]

            for idx, (ratio, cand) in enumerate(candidates, start=1):
                marker = "  <-- suggested (best name match)" if idx == suggested_idx else ""
                print(f"    [{idx}] ratio={ratio:.2f}  {_describe(db, cand)}{marker}")
                print(f"          last seen: {_most_recent_tournament(db, cand.id)}")
            if needle.gamertag[1:].split("]", 1)[0].strip().lower() in [
                cand.gamertag[1:].split("]", 1)[0].strip().lower()
                for _, cand in candidates if cand.gamertag.startswith("[")
            ]:
                print("    NOTE: at least one candidate shares this needle's bracketed team tag. Duos mean "
                      "teammates often share a tag while being two different real people -- check that the "
                      "name AFTER the tag actually matches, not just the tag itself.")

            if not args.confirm:
                continue

            choice = input(
                f"\n  Which one is genuinely the SAME real person? [Enter for suggested [{suggested_idx}] "
                f"{suggested_candidate.gamertag!r}] Enter a number, a player id, 's' to skip, or 'q' to quit: "
            ).strip()
            if choice.lower() == "q":
                print("Quitting -- no further needles processed.")
                return
            if choice.lower() == "s":
                print("  Skipped.")
                continue

            chosen = None
            if not choice:
                chosen = suggested_candidate
            elif choice.isdigit() and 1 <= int(choice) <= len(candidates):
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
