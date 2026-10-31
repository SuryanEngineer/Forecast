#!/usr/bin/env python3
"""
One-time fix for tournament tiers (dry run by default, --confirm to apply):

  * Majors now pay a dividend pool: FNCS-sized for an online (single-region) major, Global-sized for a LAN major.
    Nothing to change in the data -- the pool is worked out from the type + region -- this just reports what each tracked
    major is now worth.
  * "Last Chance" is a qualifier-style event. Adds/updates the 'last chance' classification rule and re-types every
    already-tracked Last Chance tournament from GLOBAL_CHAMPIONSHIP to FNCS_QUALIFIER (pool: dividend.qualifier_pool).

Dividends ALREADY PAID for a re-typed tournament are left alone (no clawback); only future pricing and payouts change.

    cd forecast-backend
    python3 scripts/fix_tiers.py            # preview
    python3 scripts/fix_tiers.py --confirm  # apply
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.dividend import DividendPayout  # noqa: E402
from app.models.tournament import Tournament, TournamentType  # noqa: E402
from app.models.tournament_classification import TournamentClassificationRule  # noqa: E402
from app.services import economic_params_service, tournament_classification_service  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        tournament_classification_service.seed_default_rules(db)
        rule = db.query(TournamentClassificationRule).filter(TournamentClassificationRule.pattern == "last chance").one_or_none()
        print(f"'last chance' rule: {'present, type=' + str(rule.tournament_type) if rule else 'will be created'}")
        if rule is not None and rule.tournament_type != TournamentType.FNCS_QUALIFIER and args.confirm:
            rule.tournament_type = TournamentType.FNCS_QUALIFIER
            rule.priority = 15
            rule.is_active = True

        print("\nMajors (pool is now paid):")
        for t in db.query(Tournament).filter(Tournament.tournament_type == TournamentType.MAJOR).order_by(Tournament.start_time).all():
            pool = economic_params_service.get_fixed_tournament_pool(db, t.tournament_type, t.region)
            pool = pool * economic_params_service.get_region_multiplier(db, t.region)
            kind = "LAN" if economic_params_service.is_lan_region(t.region) else "online"
            print(f"   {t.start_time.date() if t.start_time else '?'}  region={t.region!s:<6} {kind:<6} pool ${pool:>10,.0f}  {t.name[:50]}")

        print("\nLast Chance tournaments:")
        lc = db.query(Tournament).filter(Tournament.name.ilike("%last chance%")).order_by(Tournament.start_time).all()
        for t in lc:
            paid = db.query(DividendPayout).filter(DividendPayout.tournament_id == t.id).count()
            print(f"   {t.start_time.date() if t.start_time else '?'}  {t.tournament_type.value:<20} -> fncs_qualifier  ({paid} dividend payouts already exist)  {t.name[:50]}")
            if args.confirm:
                t.tournament_type = TournamentType.FNCS_QUALIFIER
        if args.confirm:
            db.commit()
            print("\nDone.")
        else:
            db.rollback()
            print("\nDry run -- nothing changed. Re-run with --confirm.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
