#!/usr/bin/env python3
"""
Qualification-aware version of merge_fuzzy_duplicates.py.

merge_fuzzy_duplicates.py fuzzy-matches an LAN-tagged needle (e.g.
"[FNCSGC26] X") against EVERY other player in the database -- 89k+ rows --
using spelling similarity alone. That's noisy: a lot of the "candidates"
it surfaces are just other players who happen to have a similarly-styled
name, with zero real connection to the needle.

This script narrows that search using the actual real-world qualification
rules for each LAN circuit, instead of pure string similarity:

  FNCS Global Championship (tags containing "FNCSGC" / "GC26" / "GLOBAL"):
    Per Epic's published 2026 FNCS rules, a Duo reaches the Global
    Championship by result in the REGULAR FNCS season -- the Division 1
    regular rounds and the Global Championship Last Chance qualifier.

    IMPORTANT, confirmed against real production data via
    scripts/inspect_fncs_classification.py: TournamentType.MAJOR and
    FNCS_QUALIFIER are never actually produced by any classification rule
    in this codebase (they exist on the enum but no rule maps to them),
    and the real "FNCS Division 1 -- Round N" tournaments are classified
    as CASH_CUP (a deliberate product decision for payout purposes, but
    it means `tournament_type` can't be used to find them), while "FNCS
    Global Championship Last Chance -- Round N" -- an ONLINE QUALIFIER,
    not the LAN itself -- is misclassified as GLOBAL_CHAMPIONSHIP because
    its name contains that substring (a real classification bug, flagged
    separately; it means that qualifier round is probably being paid out
    on the same curve as the actual LAN Final).

    Given all that, this script does NOT filter by tournament_type for
    FNCSGC at all. It filters by tournament NAME instead: a player
    qualifies into the candidate pool if they have a real placement in a
    tournament named "FNCS Division 1" (excluding "Practice" rounds --
    those are explicitly non-qualifying per the product decision above)
    or containing "Last Chance". This is a structural, rules-based
    filter grounded in what these tournaments actually are, not a
    spelling heuristic -- if nobody in that restricted set resembles the
    needle, that's real evidence the regular-season identity was never
    tracked here (e.g. they qualified through a region/split this app
    doesn't track), not a bug in the search.

  EWC (tags containing "EWC"):
    The 2026 Fortnite Esports World Cup does NOT run through FNCS/Cash
    Cup at all -- it qualifies through the separate "Reload Elite Series"
    (RES), a different game mode (Fortnite Reload, not Battle Royale)
    with its own regional qualifiers. This codebase has no
    TournamentType for Reload and (as this script checks on every run)
    no tracked Reload/RES tournaments. That means there usually IS no
    legitimate "regular season" identity for an EWC duo anywhere in this
    database to correlate against -- the qualifying event itself was
    never ingested. Rather than pretend otherwise, this script checks for
    any tracked Reload tournament up front and, if none exist, clearly
    labels every EWC candidate below as UNVERIFIED (spelling similarity
    only, no qualification signal) instead of presenting it with the same
    confidence as a FNCSGC match.

Mechanics (target selection, safety checks, tombstoning, reactivation)
are otherwise identical to merge_fuzzy_duplicates.py -- see that script's
docstring. Like that script, this one NEVER suggests a default and NEVER
accepts a bare Enter; you must pick a specific candidate number (or raw
player id) for anything to happen.

Usage:
    cd forecast-backend
    python3 scripts/merge_qualified_duplicates.py                  # dry run
    python3 scripts/merge_qualified_duplicates.py --confirm         # interactive
    python3 scripts/merge_qualified_duplicates.py --confirm --threshold 0.75
                                                                     # looser
                                                                     # threshold
                                                                     # for the
                                                                     # qualification-
                                                                     # restricted
                                                                     # FNCSGC
                                                                     # search
                                                                     # (safe to
                                                                     # loosen
                                                                     # since the
                                                                     # candidate
                                                                     # pool is
                                                                     # already
                                                                     # qualification-
                                                                     # filtered,
                                                                     # not just
                                                                     # similarity-
                                                                     # filtered)
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
from app.models.tournament import PlacementResult, Tournament  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.house_account import HOUSE_ACCOUNT_EMAIL  # noqa: E402
from app.services.osirion_service import clean_gamertag  # noqa: E402

_TOMBSTONE_PREFIX = "[MERGED INTO"

# The real regular-season FNCS tournaments that feed Global Championship
# qualification, identified by NAME rather than tournament_type -- see the
# module docstring for why: MAJOR/FNCS_QUALIFIER are never actually
# produced by any classification rule, "FNCS Division 1" (non-practice)
# rounds are classified as CASH_CUP, and "Last Chance" qualifier rounds
# are misclassified as GLOBAL_CHAMPIONSHIP. Name matching is what actually
# finds the right tournaments given that reality.
# "FNCS Division 1 Practice" rounds are deliberately excluded -- per the
# product decision in tournament_classification_service.py, those are
# explicitly non-qualifying practice lobbies, not real qualifying rounds.

_FNCSGC_MARKERS = ("FNCSGC", "GC26", "GC25", "GLOBALCHAMPIONSHIP", "GLOBAL CHAMPIONSHIP")
_EWC_MARKERS = ("EWC",)

_TAG_RE = re.compile(r"^\[([^\]]*)\]")


def _classify_needle_circuit(gamertag: str) -> str:
    match = _TAG_RE.match(gamertag)
    tag = match.group(1).upper() if match else ""
    if any(marker in tag for marker in _FNCSGC_MARKERS):
        return "fncsgc"
    if any(marker in tag for marker in _EWC_MARKERS):
        return "ewc"
    return "other"


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
    parser.add_argument("--threshold", type=float, default=0.75,
                         help="Minimum similarity ratio (0-1) for the qualification-restricted FNCSGC search and "
                              "the fallback/EWC search. Default 0.75 (looser than merge_fuzzy_duplicates.py's 0.82 "
                              "default, since the FNCSGC pool is already qualification-filtered, not just similarity-filtered).")
    parser.add_argument("--confirm", action="store_true",
                         help="Interactively confirm and perform merges. Without this flag, it's a dry run that "
                              "only lists candidates -- no prompts, no writes.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        real_user_ids = _real_user_ids(db)

        reload_tournaments = (
            db.query(Tournament)
            .filter(Tournament.name.ilike("%reload%"))
            .all()
        )
        print("=" * 100)
        print("STEP 1: Checking whether this database tracks the EWC qualifying pathway (Reload Elite Series)...")
        # NOTE: having SOME tournament with "reload" in the name is not the same as having the actual
        # RES regional qualifiers tracked -- the 2024 "Reload Cash Cup" rows below are two years stale and
        # irrelevant to 2026 EWC qualification, and the one real 2026 "Reload Elite Series Championship"
        # row IS the EWC LAN itself (where the needles' own placements come from), not a regular-season
        # identity to merge into. So this script restricts EWC candidates to players with a REAL placement
        # in one of these tournaments too, exactly like the FNCSGC restriction below -- it does not just
        # take "a Reload tournament exists somewhere" as license to trust the full unrestricted search.
        reload_qualified_player_ids = {
            r[0]
            for r in (
                db.query(PlacementResult.player_id)
                .join(Tournament, Tournament.id == PlacementResult.tournament_id)
                .filter(Tournament.name.ilike("%reload%"))
                .distinct()
                .all()
            )
        }
        if reload_tournaments:
            print(f"  Found {len(reload_tournaments)} tournament(s) with 'Reload' in the name:")
            for t in reload_tournaments:
                print(f"    - {t.name!r} (type={t.tournament_type.value}, region={t.region})")
            print(f"  {len(reload_qualified_player_ids)} player(s) have a real placement in one of these. EWC "
                  f"candidates below are restricted to that pool -- but note most of these rows are 2024 Reload "
                  f"Cash Cups (stale, pre-dates the current roster) or the EWC LAN itself, so this pool is likely "
                  f"thin or empty even though the check technically 'passes'.")
            ewc_verified = True
        else:
            reload_qualified_player_ids = set()
            print("  None found. The 2026 EWC Fortnite event qualifies through the Reload Elite Series (RES) -- a "
                  "separate game mode (Fortnite Reload, not Battle Royale) with its own regional qualifiers. This app "
                  "has no TournamentType for Reload and, confirmed above, no tracked Reload tournaments. That means "
                  "there is usually no legitimate 'regular season' identity for an EWC duo in this database at all -- "
                  "the qualifying event itself was never ingested, not that the search is missing it.")
            print("  EWC candidates below are therefore UNVERIFIED: spelling similarity only, no qualification signal.")
            ewc_verified = False
        print()

        print("STEP 2: Building the qualification-restricted candidate pool for FNCSGC needles...")
        gc_qualifying_tournaments = (
            db.query(Tournament)
            .filter(
                (Tournament.name.ilike("%fncs division%") & ~Tournament.name.ilike("%practice%"))
                | Tournament.name.ilike("%last chance%")
            )
            .all()
        )
        print(f"  Found {len(gc_qualifying_tournaments)} real GC-qualifying tournament(s) by name "
              f"('FNCS Division' excluding 'Practice', or 'Last Chance'):")
        for t in gc_qualifying_tournaments:
            print(f"    - {t.name!r} (type={t.tournament_type.value}, region={t.region})")
        gc_qualifying_tournament_ids = {t.id for t in gc_qualifying_tournaments}
        qualified_player_ids = {
            r[0]
            for r in (
                db.query(PlacementResult.player_id)
                .filter(PlacementResult.tournament_id.in_(gc_qualifying_tournament_ids))
                .distinct()
                .all()
            )
        } if gc_qualifying_tournament_ids else set()
        print(f"  {len(qualified_player_ids)} player(s) have a real placement in one of these.")
        print()

        all_players = db.query(Player).filter(~Player.gamertag.startswith(_TOMBSTONE_PREFIX)).all()
        full_haystack = [(p, clean_gamertag(p.gamertag).lower()) for p in all_players]
        qualified_haystack = [(p, core) for p, core in full_haystack if p.id in qualified_player_ids]
        reload_qualified_haystack = [(p, core) for p, core in full_haystack if p.id in reload_qualified_player_ids]

        needles = [p for p in all_players if p.is_active and p.gamertag.startswith("[") and len(p.placement_results) <= 2]

        if not needles:
            print("No active LAN-tagged, low-placement players found -- nothing to check.")
            return

        print(f"STEP 3: Checking {len(needles)} candidate(s), threshold={args.threshold}.\n")

        for i, needle in enumerate(needles, start=1):
            if needle.gamertag.startswith(_TOMBSTONE_PREFIX):
                continue  # merged away earlier in this same run, as someone else's source

            circuit = _classify_needle_circuit(needle.gamertag)

            if circuit == "fncsgc":
                haystack = qualified_haystack
                label = "QUALIFICATION-RESTRICTED (real FNCS Major/Qualifier/Finals placement -- the actual GC pathway)"
            elif circuit == "ewc":
                if ewc_verified:
                    haystack = reload_qualified_haystack
                    label = "QUALIFICATION-RESTRICTED (real placement in a tracked Reload/RES tournament)"
                else:
                    haystack = full_haystack
                    label = "UNVERIFIED (no Reload/RES data tracked -- spelling similarity only, no qualification signal)"
            else:
                haystack = full_haystack
                label = "untagged circuit -- full-database spelling search, same as merge_fuzzy_duplicates.py"

            candidates = _find_candidates(needle, haystack, args.threshold)

            print("=" * 100)
            print(f"[{i}/{len(needles)}] Needle: {_describe(db, needle)}  circuit={circuit}")
            print(f"    Search: {label}")
            if not candidates:
                if circuit == "fncsgc":
                    print("    No candidates found in the qualification-restricted pool, even at this threshold. "
                          "Real evidence this player's regular-season FNCS result isn't tracked here (likely a "
                          "region/split this app doesn't track), not a search gap.")
                elif circuit == "ewc" and ewc_verified:
                    print("    No candidates found in the Reload/RES-qualified pool, even at this threshold. Most "
                          "tracked Reload tournaments are 2024 Cash Cups or the EWC LAN itself, so an empty result "
                          "here is expected, not a search gap.")
                else:
                    print("    No candidates found above threshold.")
                continue
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
