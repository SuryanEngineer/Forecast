#!/usr/bin/env python3
"""
Track Performance Evaluation cups that already happened since the site launched, and pay their dividends
retroactively -- to whoever held each player's shares when the cup STARTED (not whoever holds them today).

Performance Evaluation cups are set-lobby events that pay per game WON: the cup's pool is $300,000, one game win is
worth a quarter of it ($75,000), split across the winning team (a trio's win = $25,000 to each player's shareholders).
See app/engine/performance_eval.py.

What this does, per cup (dry run by default, --confirm to apply):
  1. flips the "performance evaluation" classification rule from "exclude" to the Performance Evaluation tier;
  2. finds the cups in Osirion's listing (including history) that started on/after --since (default: when the first real
     user joined), in the tracked regions, with a real cash payout, not Zero Build;
  3. tracks each one (or re-opens one that an earlier purge hid), then syncs it. Because the cup is over, the sync walks the
     whole leaderboard and finalizes it, which creates the dividend payouts and pays them out using the share-ledger
     snapshot at the cup's start time (position_service.holdings_at) -- so buying a player AFTER the cup earns nothing,
     and selling after it started still earns the dividend.
  4. prints, per cup: players, game wins, dividend pools and what real users were paid.

Safe to re-run: a tournament already finalized is skipped, payouts are idempotent.

    python3 scripts/retro_performance_evals.py                    # dry run: shows what would be tracked
    python3 scripts/retro_performance_evals.py --confirm
    python3 scripts/retro_performance_evals.py --confirm --since 2026-10-01
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.engine import performance_eval  # noqa: E402
from app.models.bot import BotProfile  # noqa: E402
from app.models.dividend import DividendLineItem, DividendPayout  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.models.tournament import PlacementResult, Tournament, TournamentStatus, TournamentType  # noqa: E402
from app.models.tournament_classification import TournamentClassificationRule  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import osirion_service, tournament_classification_service  # noqa: E402


def _site_start(db) -> datetime:
    first = (
        db.query(func.min(User.created_at))
        .filter(~User.id.in_(db.query(BotProfile.user_id)), User.email != "house@system.forecast.internal")
        .scalar()
    )
    return first or datetime(2026, 1, 1, tzinfo=timezone.utc)


def _summarize(db, tournament: Tournament) -> None:
    rows = db.query(PlacementResult).filter(PlacementResult.tournament_id == tournament.id).all()
    seen_teams: dict[str, int] = {}
    for r in rows:
        key = f"{r.placement}:{r.team_id}"
        seen_teams.setdefault(key, performance_eval.count_game_wins(r.raw_stats))
    wins = sum(seen_teams.values())
    paid = (
        db.query(func.coalesce(func.sum(DividendLineItem.amount_paid), 0), func.count(func.distinct(DividendLineItem.user_id)))
        .join(DividendPayout, DividendPayout.id == DividendLineItem.payout_id)
        .filter(DividendPayout.tournament_id == tournament.id)
        .one()
    )
    pool = db.query(func.coalesce(func.sum(DividendPayout.total_pool_amount), 0)).filter(DividendPayout.tournament_id == tournament.id).scalar()
    print(f"      players {len(rows)}, teams {len(seen_teams)}, games won {wins}, dividend pools ${float(pool):,.2f}, "
          f"paid to {paid[1]} user(s) ${float(paid[0]):,.2f}  [{tournament.status.value}]")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--since", help="Only cups starting on/after this date (YYYY-MM-DD). Default: when the first real user joined.")
    args = ap.parse_args()

    db = SessionLocal()
    db.expire_on_commit = False
    try:
        since = (
            datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.since else _site_start(db)
        )
        print(f"Cups starting on/after {since:%Y-%m-%d %H:%M} UTC\n")

        rule = db.query(TournamentClassificationRule).filter(func.lower(TournamentClassificationRule.pattern) == "performance evaluation").one_or_none()
        if rule is None or rule.tournament_type != TournamentType.PERFORMANCE_EVAL:
            print("Classification rule 'performance evaluation': " + ("missing" if rule is None else f"currently {rule.tournament_type}") + " -> performance_eval")
            if args.confirm:
                tournament_classification_service.seed_default_rules(db)
                rule = db.query(TournamentClassificationRule).filter(func.lower(TournamentClassificationRule.pattern) == "performance evaluation").one()
                rule.tournament_type = TournamentType.PERFORMANCE_EVAL
                rule.is_active = True
                db.commit()

        print("Fetching Osirion's listing (including history) ...")
        windows = osirion_service.list_available_windows(include_historic_data=True)
        picked = []
        for w in windows:
            if "performance evaluation" not in w.classification_text.lower():
                continue
            when = w.begin_time or w.end_time
            if when is None or when < since or w.is_zero_build or not w.has_cash_payout:
                continue
            if not osirion_service._in_tracking_region_scope(TournamentType.PERFORMANCE_EVAL, w.regions):
                continue
            if not w.leaderboard_event_id or not w.leaderboard_event_window_id:
                continue
            picked.append(w)
        picked.sort(key=lambda w: w.begin_time or datetime.min.replace(tzinfo=timezone.utc))
        print(f"{len(picked)} Performance Evaluation cup(s) in scope.\n")

        for w in picked:
            key = (w.leaderboard_event_id, w.leaderboard_event_window_id)
            mapping = (
                db.query(OsirionTournamentMapping)
                .filter(OsirionTournamentMapping.leaderboard_event_id == key[0], OsirionTournamentMapping.leaderboard_event_window_id == key[1])
                .one_or_none()
            )
            tournament = db.get(Tournament, mapping.tournament_id) if mapping else None
            state = "NEW" if tournament is None else f"tracked ({tournament.status.value}{', hidden' if tournament.is_historical_archive else ''})"
            print(f"  - {w.begin_time:%Y-%m-%d %H:%M}  {w.display_name}  [{','.join(w.regions)}]  {state}")
            if tournament is not None and tournament.status == TournamentStatus.FINALIZED and not tournament.is_historical_archive:
                has_payouts = db.query(DividendPayout.id).filter(DividendPayout.tournament_id == tournament.id).first() is not None
                if has_payouts:
                    _summarize(db, tournament)
                    continue
            if not args.confirm:
                continue

            if tournament is None:
                mapping = osirion_service.track_tournament(
                    db, name=w.display_name, tournament_type=TournamentType.PERFORMANCE_EVAL,
                    region=w.regions[0] if len(w.regions) == 1 else None, window=w, created_by_admin_id=None,
                )
                tournament = db.get(Tournament, mapping.tournament_id)
            else:
                # An earlier purge may have hidden this cup and emptied it: bring it back as a Performance Evaluation cup.
                tournament.tournament_type = TournamentType.PERFORMANCE_EVAL
                tournament.is_historical_archive = False
                if tournament.status == TournamentStatus.FINALIZED:
                    tournament.status = TournamentStatus.RESULTS_PENDING
                mapping.last_sync_complete = False
                db.commit()

            res = osirion_service.sync_tournament(db, mapping)
            db.refresh(tournament)
            note = f" ERROR: {res.error}" if res.error else ""
            print(f"      synced: matched {res.matched}, finalized={res.finalized}{note}")
            _summarize(db, tournament)

        if not args.confirm:
            print("\nDry run only. Re-run with --confirm to track, sync and pay.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
