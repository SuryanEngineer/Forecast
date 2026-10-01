#!/usr/bin/env python3
"""
One-time production fix: tournament_classification_service.py's
DEFAULT_RULES now excludes "performance evaluation" windows entirely
(tournament_type=None) instead of classifying them as CASH_CUP -- per
explicit product direction, Performance Evaluation events should never
count toward the tradeable roster even though they do pay real cash.

Editing DEFAULT_RULES in code has NO effect on a production database that
already seeded the old version of this rule: seed_default_rules() only
INSERTS a pattern that isn't already present, it never updates an
existing row (see that function's own docstring for why -- this is the
exact same gap that previously caused the "global championship" rule
fix to not reach production without a manual step, see commit history).
This script is that manual step, made safe/repeatable instead of a
one-off admin API call.

What this does NOT do: retroactively un-IPO or deactivate any player who
was already created from an already-tracked Performance Evaluation
tournament, or un-track/delete that Tournament row itself -- this only
fixes the RULE so Performance Evaluation windows are never auto-tracked
going forward. If you also want to walk back players/tournaments already
created from Performance Evaluation specifically, that's a separate,
deliberately-not-automated decision (same reasoning as every other
cleanup script in this folder -- see deactivate_qualifier_only_players.py).

Usage (dry run by default -- shows what would change, changes nothing):
    cd forecast-backend
    python3 scripts/fix_classification_rules.py

Actually apply it:
    python3 scripts/fix_classification_rules.py --confirm
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.tournament import TournamentType  # noqa: E402
from app.models.tournament_classification import TournamentClassificationRule  # noqa: E402
from app.services import tournament_classification_service  # noqa: E402

NEW_DESCRIPTION = (
    "Osirion's 'Fortnite Performance Evaluation' events pay real cash (seen at $1,600 for a top "
    "finish), but per explicit product direction these should NOT count toward the tradeable "
    "roster/Finals tier -- excluded outright rather than classified as Cash Cup."
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--confirm", action="store_true", help="Actually apply the fix. Without this flag, it's a dry run.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        # Ensures the rules table exists/is seeded at all (idempotent, same
        # as every other classify()/get_active_rules() caller) before we go
        # looking for the specific row to fix.
        tournament_classification_service.seed_default_rules(db)

        rule = (
            db.query(TournamentClassificationRule)
            .filter(TournamentClassificationRule.pattern == "performance evaluation")
            .one_or_none()
        )

        if rule is None:
            print("No 'performance evaluation' classification rule exists yet -- nothing to fix. "
                  "(The corrected exclude-rule version will be seeded automatically the next time "
                  "any classify()/get_active_rules() call runs, since it's a new pattern.)")
            return

        if rule.tournament_type is None:
            print(f"'performance evaluation' rule (id={rule.id}) is already an exclude rule (tournament_type=None). "
                  "Nothing to do.")
            return

        print(f"Found 'performance evaluation' rule (id={rule.id}):")
        print(f"  current tournament_type = {rule.tournament_type.value if rule.tournament_type else None}")
        print(f"  current is_active       = {rule.is_active}")
        print(f"  current description     = {rule.description!r}")
        print(f"\nWill change to: tournament_type=None (excluded), is_active=True, updated description.")

        if not args.confirm:
            print("\nDry run only -- nothing changed. Re-run with --confirm to actually apply this.")
            return

        tournament_classification_service.update_rule(
            db,
            rule.id,
            clear_tournament_type=True,
            is_active=True,
            description=NEW_DESCRIPTION,
        )
        db.commit()
        print(f"\nDone. Rule id={rule.id} is now an exclude rule -- Performance Evaluation windows will "
              "no longer be auto-tracked as Cash Cup tier on the next sync pass.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
