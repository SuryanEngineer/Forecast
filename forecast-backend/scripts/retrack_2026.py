#!/usr/bin/env python3
"""
Apply the current tracking rules to the whole of 2026 (dry run by default, --confirm to apply).

What the rules are (see app/engine/tracking_policy.py and app/engine/payout_policy.py):
  * Battle Royale / Reload only (never Zero Build); cash events plus SET-LOBBY qualifiers.
  * FNCS Solo Reload: Heats and Last Chance Qualifier sessions are FNCS_QUALIFIER ($150,000 pool, set lobby only);
    the Finals is FNCS_FINALS (full FNCS pool).
  * Arenas Cash Cup pays its top 10 only.

What this script does:
  1. RECLASSIFY tournaments you already track whose tier is wrong under these rules (e.g. a Last Chance Qualifier that
     was tracked as FNCS Finals). Only ones that have NOT paid dividends are changed; if one already paid at the wrong
     pool it is listed for you to decide (nothing is clawed back automatically).
  2. FIND the set-lobby qualifiers / Finals that Osirion lists (including history) but you do not track yet.
       - started on/after the site's start (--since, default: when the first real user joined): tracked as a real
         tournament, synced and finalized. Dividends are paid to whoever held the player's shares when it STARTED
         (position_service.holdings_at), dated to when the event finished, with a notification dated then too, and every
         affected user's daily net-worth snapshots from that day on are adjusted.
       - started before that: added as hidden HISTORICAL ARCHIVE (no payouts -- nobody owned shares then). They still
         count in each player's 2026 results, the estimates and the bots' valuations.
  3. REOPEN archived tournaments that started after the site's start but never paid (so their holders are paid now).
  4. Prints per-event what was paid and to how many users.

Safe to re-run: tracked / paid events are skipped and payouts are idempotent.

    python3 scripts/retrack_2026.py                       # dry run
    python3 scripts/retrack_2026.py --confirm
    python3 scripts/retrack_2026.py --confirm --since 2026-10-01
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.engine import format_policy, tracking_policy  # noqa: E402
from app.models.account import PortfolioSnapshot  # noqa: E402
from app.models.bot import BotProfile  # noqa: E402
from app.models.dividend import DividendLineItem, DividendPayout  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.models.tournament import Tournament, TournamentStatus, TournamentType  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import economic_params_service, osirion_service  # noqa: E402


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _site_start(db) -> datetime:
    first = (
        db.query(func.min(User.created_at))
        .filter(~User.id.in_(db.query(BotProfile.user_id)), User.email != "house@system.forecast.internal")
        .scalar()
    )
    return _aware(first) or datetime(2026, 1, 1, tzinfo=timezone.utc)


def _has_payouts(db, tournament_id) -> bool:
    return db.query(DividendPayout.id).filter(DividendPayout.tournament_id == tournament_id).first() is not None


def _expected_type(text: str) -> TournamentType | None:
    role = tracking_policy.reload_family_role(text)
    if role == tracking_policy.ROLE_FINAL:
        return TournamentType.FNCS_FINALS
    if role == tracking_policy.ROLE_QUALIFIER:
        return TournamentType.FNCS_QUALIFIER
    return None


def _summarize(db, tournament: Tournament) -> tuple[float, int]:
    paid = (
        db.query(func.coalesce(func.sum(DividendLineItem.amount_paid), 0), func.count(func.distinct(DividendLineItem.user_id)))
        .join(DividendPayout, DividendPayout.id == DividendLineItem.payout_id)
        .filter(DividendPayout.tournament_id == tournament.id)
        .one()
    )
    pool = db.query(func.coalesce(func.sum(DividendPayout.total_pool_amount), 0)).filter(DividendPayout.tournament_id == tournament.id).scalar()
    print(f"      dividend pools ${float(pool):,.2f}; paid to {paid[1]} user(s) ${float(paid[0]):,.2f}  [{tournament.status.value}]")
    return float(paid[0]), int(paid[1])


def _adjust_snapshots(db, tournament_ids: list) -> int:
    """Daily net-worth snapshots are stored values, so a dividend dated in the past has to be added to every snapshot of
    that user from the payout day onward (net worth and cash both rise by the amount). Only called for events paid in THIS
    run, so it is never applied twice."""
    if not tournament_ids:
        return 0
    rows = (
        db.query(DividendLineItem.user_id, DividendLineItem.amount_paid, DividendLineItem.created_at)
        .join(DividendPayout, DividendPayout.id == DividendLineItem.payout_id)
        .filter(DividendPayout.tournament_id.in_(tournament_ids), DividendLineItem.amount_paid > 0)
        .all()
    )
    touched = 0
    for uid, amount, at in rows:
        day = _aware(at).astimezone(timezone.utc).strftime("%Y-%m-%d")
        for snap in db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == uid, PortfolioSnapshot.day >= day).all():
            snap.net_worth = snap.net_worth + amount
            snap.cash = snap.cash + amount
            touched += 1
    db.commit()
    return touched


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--since", help="Events starting on/after this date (YYYY-MM-DD) are paid; earlier ones are archived. Default: when the first real user joined.")
    ap.add_argument("--include-performance-evals", action="store_true", help="Also add / pay Performance Evaluation cups (left out by default).")
    args = ap.parse_args()

    db = SessionLocal()
    db.expire_on_commit = False
    try:
        site_start = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.since else _site_start(db)
        print(f"Events starting on/after {site_start:%Y-%m-%d %H:%M} UTC are paid; earlier ones are archived (no payout).")
        qpool = economic_params_service.get_param(db, "dividend.qualifier_pool")
        print(f"Qualifier pool currently ${float(qpool):,.0f}" + ("" if float(qpool) == 150000 else "  (expected 150,000 -- run the migration / set it in admin)"))
        db.commit()

        # ---- 1. reclassify what is already tracked -------------------------------------------------------------------
        print("\n== 1. Tournaments you track whose tier is wrong ==")
        wrong = 0
        mappings = db.query(OsirionTournamentMapping).all()
        for m in mappings:
            t = db.get(Tournament, m.tournament_id)
            if t is None:
                continue
            want = _expected_type(f"{t.name} {m.osirion_display_name or ''} {m.osirion_event_id or ''}")
            if want is None or t.tournament_type == want:
                continue
            wrong += 1
            paid = _has_payouts(db, t.id)
            tag = "ALREADY PAID at the old tier -- left alone, decide manually" if paid else ("-> fixing" if args.confirm else "-> would fix")
            print(f"  - {t.name}: {t.tournament_type.value} -> {want.value}  {tag}")
            if not paid and args.confirm:
                t.tournament_type = want
        if args.confirm:
            db.commit()
        if not wrong:
            print("  none")

        # ---- 2. missing set-lobby qualifiers / finals ----------------------------------------------------------------
        print("\n== 2. Qualifiers / finals Osirion lists that you do not track yet ==")
        print("Fetching Osirion's listing (including history) ...")
        windows = osirion_service.list_available_windows(include_historic_data=True)
        now = datetime.now(timezone.utc)
        ended = [w for w in windows if w.end_time is not None and _aware(w.end_time) < now and (w.begin_time or w.end_time) >= datetime(2026, 1, 1, tzinfo=timezone.utc)]
        planned, skips = osirion_service.plan_windows(db, ended, strict_set_lobby=True)
        print("  skipped: " + (", ".join(f"{k}={v}" for k, v in sorted(skips.items())) or "nothing"))
        tracked = {(m.leaderboard_event_id, m.leaderboard_event_window_id) for m in mappings}
        todo_pay, todo_archive = [], []
        if not args.include_performance_evals:
            n_pe = sum(1 for p in planned if p.tournament_type == TournamentType.PERFORMANCE_EVAL)
            planned = [p for p in planned if p.tournament_type != TournamentType.PERFORMANCE_EVAL]
            print(f"  (leaving out {n_pe} Performance Evaluation cups; add --include-performance-evals to include them)")
        rules_by_key: dict = {}
        for p in planned:
            wkey = (p.window.leaderboard_event_id, p.window.leaderboard_event_window_id)
            rules_by_key[wkey] = p.format_rules
            if any((s.leaderboard_event_id, s.leaderboard_event_window_id) in tracked for s in (p.siblings or [p.window])):
                continue
            (todo_pay if _aware(p.window.begin_time or p.window.end_time) >= site_start else todo_archive).append(p)

        def _pool_text(p) -> str:
            pool = economic_params_service.get_tournament_pool(
                db, p.tournament_type, p.window.regions[0] if len(p.window.regions) == 1 else None, p.format_rules)
            return f"${float(pool):,.0f}" if pool is not None else "n/a"

        for label, items in (("PAY (started after launch)", todo_pay), ("ARCHIVE (before launch)", todo_archive)):
            print(f"  {label}: {len(items)}")
            for p in sorted(items, key=lambda x: x.window.begin_time or x.window.end_time):
                w = p.window
                print(f"    - {w.begin_time:%Y-%m-%d %H:%M}  {w.display_name}  [{','.join(w.regions)}]  as {p.tournament_type.value}  "
                      f"pool {_pool_text(p)}  ({format_policy.describe(p.format_rules)}"
                      f"{', pays top ' + str(p.format_rules['paid_places']) if (p.format_rules or {}).get('paid_places') else ''})")

        # Tournaments you already track: show / set the pool the format rules give them (never touch one already paid).
        print("\n== 2b. Tracked tournaments: pool under the format rules ==")
        changed_rules = 0
        for m in mappings:
            rec = rules_by_key.get((m.leaderboard_event_id, m.leaderboard_event_window_id))
            t = db.get(Tournament, m.tournament_id)
            if rec is None or t is None or t.format_rules:
                continue
            paid = _has_payouts(db, t.id)
            old = economic_params_service.get_tournament_pool(db, t.tournament_type, t.region, None)
            new = economic_params_service.get_tournament_pool(db, t.tournament_type, t.region, rec)
            same = old == new
            if same and not rec.get("paid_places"):
                continue
            tag = "ALREADY PAID -- left alone" if paid else ("-> setting" if args.confirm else "-> would set")
            print(f"  - {t.name}: ${float(old or 0):,.0f} -> ${float(new or 0):,.0f}  ({format_policy.describe(rec)})  {tag}")
            if not paid:
                changed_rules += 1
                if args.confirm:
                    t.format_rules = rec
        if args.confirm:
            db.commit()
        if not changed_rules:
            print("  nothing to change")

        # ---- 3. archived but should have paid ------------------------------------------------------------------------
        print("\n== 3. Archived tournaments that started after launch but never paid ==")
        reopen = []
        for t in db.query(Tournament).filter(Tournament.is_historical_archive.is_(True)).all():
            if _aware(t.start_time) is None or _aware(t.start_time) < site_start or _has_payouts(db, t.id):
                continue
            if t.tournament_type == TournamentType.PERFORMANCE_EVAL and not args.include_performance_evals:
                continue
            m = db.query(OsirionTournamentMapping).filter(OsirionTournamentMapping.tournament_id == t.id).one_or_none()
            if m is None:
                continue
            reopen.append((t, m))
            print(f"  - {t.start_time:%Y-%m-%d}  {t.name}  [{t.tournament_type.value}]")
        if not reopen:
            print("  none")

        if not args.confirm:
            print("\nDry run only. Re-run with --confirm to apply.")
            return

        paid_now: list = []

        # archive the pre-launch ones
        if todo_archive:
            print("\nArchiving pre-launch events ...")
            res = osirion_service.backfill_historical_tournaments(
                db, [osirion_service.BackfillCandidate(window=p.window, tournament_type=p.tournament_type, format_rules=p.format_rules) for p in todo_archive]
            )
            print(f"  archived {res.tracked}, errors {len(res.errors)}")
            for e in res.errors:
                print(f"    ERROR {e}")

        # pay the post-launch ones, oldest first
        print("\nTracking and paying post-launch events (oldest first) ...")
        for p in sorted(todo_pay, key=lambda x: x.window.begin_time or x.window.end_time):
            w = p.window
            print(f"  - {w.display_name}")
            try:
                mapping = osirion_service.track_tournament(
                    db, name=w.display_name, tournament_type=p.tournament_type,
                    region=w.regions[0] if len(w.regions) == 1 else None, window=w, created_by_admin_id=None,
                    format_rules=p.format_rules,
                )
                res = osirion_service.sync_tournament(db, mapping)
                t = db.get(Tournament, mapping.tournament_id)
                db.refresh(t)
                print(f"      synced: matched {res.matched}, finalized={res.finalized}" + (f" ERROR: {res.error}" if res.error else ""))
                _summarize(db, t)
                if _has_payouts(db, t.id):
                    paid_now.append(t.id)
            except Exception as exc:  # noqa: BLE001 -- keep going with the other events
                db.rollback()
                print(f"      FAILED: {exc}")

        for t, m in sorted(reopen, key=lambda x: x[0].start_time):
            print(f"  - reopening {t.name}")
            try:
                t.is_historical_archive = False
                if not t.format_rules:
                    # an event still in progress isn't in the ended-window plan: give it the cautious cash-round rule and let
                    # the first sync settle open vs set lobby from its leaderboard
                    t.format_rules = rules_by_key.get((m.leaderboard_event_id, m.leaderboard_event_window_id)) or format_policy.decide(
                        lobby=format_policy.LOBBY_UNKNOWN, has_cash=True, stage_index=0)
                if t.status == TournamentStatus.FINALIZED:
                    t.status = TournamentStatus.RESULTS_PENDING
                m.last_sync_complete = False
                db.commit()
                res = osirion_service.sync_tournament(db, m)
                db.refresh(t)
                print(f"      synced: matched {res.matched}, finalized={res.finalized}" + (f" ERROR: {res.error}" if res.error else ""))
                _summarize(db, t)
                if _has_payouts(db, t.id):
                    paid_now.append(t.id)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                print(f"      FAILED: {exc}")

        touched = _adjust_snapshots(db, paid_now)
        print(f"\nDone. {len(paid_now)} event(s) paid; {touched} daily net-worth snapshot(s) adjusted.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
