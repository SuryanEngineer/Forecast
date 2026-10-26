#!/usr/bin/env python3
"""
Backfill / inspect the EARLIER ROUNDS (qualifiers) of tracked Finals events, which the bots use to judge who will make
the Finals, how they'll place, and who their teammates are.

    cd forecast-backend
    python3 scripts/sync_qualifiers.py --status                  # what is stored so far (no API calls)
    python3 scripts/sync_qualifiers.py --passes 5                # fetch up to 5 rate-limited passes
    python3 scripts/sync_qualifiers.py --passes 40 --pages 20    # bigger backfill (20 pages per pass)
    python3 scripts/sync_qualifiers.py --types cash_cup          # only Cash Cups
    python3 scripts/sync_qualifiers.py --fit                     # show what the bots learned (qualifier -> Finals)

Safe against the real database: this only writes the qualifier_windows / qualifier_results tables, never creates
players, never pays dividends. Results are stored only for players already on the roster. It is resumable -- run it
again and it continues where it stopped. The running server does the same thing automatically in its sync loop.
"""
from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
import app.models  # noqa: E402,F401
from app.models.qualifier import QualifierResult, QualifierWindow  # noqa: E402
from app.models.tournament import Tournament, TournamentType  # noqa: E402
from app.services import qualifier_model_service, qualifier_service  # noqa: E402


def status(db) -> None:
    rows = (
        db.query(Tournament.name, Tournament.start_time, QualifierWindow.stage_index, QualifierWindow.display_name,
                 QualifierWindow.is_complete, QualifierWindow.capped, QualifierWindow.entries_seen, QualifierWindow.matched,
                 QualifierWindow.advance_cutoff, QualifierWindow.field_estimate)
        .join(QualifierWindow, QualifierWindow.tournament_id == Tournament.id)
        .order_by(Tournament.start_time.desc().nullslast(), QualifierWindow.stage_index)
        .all()
    )
    if not rows:
        print("No qualifier windows stored yet. Run:  python3 scripts/sync_qualifiers.py --passes 5")
        return
    last = None
    for name, start, stage, disp, done, capped, seen, matched, cutoff, fld in rows:
        if name != last:
            print(f"\n{name}  ({start:%Y-%m-%d} )" if start else f"\n{name}")
            last = name
        flag = "complete" if done else ("capped" if capped else "in progress")
        print(f"  round {stage}: {disp or '-'}  [{flag}]  entries read {seen}  roster hits {matched}  "
              f"advance cutoff {cutoff or '?'}  field ~{fld or '?'}")
    print(f"\nTotal stored results: {db.query(func.count(QualifierResult.id)).scalar()}")


def fit(db) -> None:
    m = qualifier_model_service.fit_model(db, force=True)
    print(f"Training rows (player-events): {m.n_players_events}   fitted pairs: {m.n_pairs}")
    print(f"Finals strength = {m.a:.3f} + {m.b:.3f} x qualifier strength   (residual sd {m.resid_sd:.3f})")
    print("P(makes Finals) by qualifier strength bucket (0-.2 ... .8-1):", [round(r, 2) for r in m.rates])
    if m.n_pairs < 40:
        print("(Little history yet -- the bots are leaning on the built-in priors; they sharpen as more events are stored.)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--passes", type=int, default=1)
    ap.add_argument("--pages", type=int, default=None, help="pages per pass (default QUALIFIER_PAGES_PER_PASS)")
    ap.add_argument("--types", default=None, help="comma list, e.g. cash_cup,fncs_finals")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.status:
            return status(db)
        if args.fit:
            return fit(db)
        only = {TournamentType(t.strip()) for t in args.types.split(",")} if args.types else None
        for i in range(1, args.passes + 1):
            r = qualifier_service.sync_qualifiers(db, max_pages=args.pages, only_types=only)
            print(f"pass {i}: windows {r.windows_known}, pages {r.pages_fetched}, stored {r.results_stored}, "
                  f"completed {r.windows_completed}, errors {len(r.errors)}")
            for e in r.errors[:5]:
                print("   !", e)
            if r.pages_fetched == 0:
                print("Nothing left to fetch right now.")
                break
            time.sleep(1)
        qualifier_model_service.clear_cache()
        status(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
