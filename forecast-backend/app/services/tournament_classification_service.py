"""
Turns an Osirion window's display name into a decision: auto-track it as a
given TournamentType tier, or leave it alone entirely. See
app/models/tournament_classification.py for the data model and
app/services/osirion_service.auto_track_new_tournaments for where this
gets called (once per background sync pass, on every window Osirion
currently has open that isn't already tracked).

This is a deliberate WHITELIST, not a blocklist: a window that matches no
rule at all is left untracked, same as one that matches an explicit
"exclude" rule (a rule with tournament_type=NULL). Getting a payout tier
wrong is a real economic mistake (see FIXED_POOL_PARAM_BY_TOURNAMENT_TYPE),
so an unrecognized tournament name is treated the same as "not yet
configured" rather than guessed at -- an admin can always add a new rule
(or fall back to the old manual POST /admin/osirion/track-tournament) for
anything this doesn't cover yet.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.tournament import TournamentType
from app.models.tournament_classification import TournamentClassificationRule

# Seeded once, the first time get_active_rules() is called on a fresh
# database -- exactly the same "seed on first read" pattern as
# economic_params_service.get_placement_curve. Lower priority number =
# checked first; the first pattern that's a case-insensitive substring of
# the window's display name wins. tournament_type=None means "exclude":
# never auto-track a window matching this pattern, no matter what else it
# might also match.
DEFAULT_RULES: list[tuple[str, TournamentType | None, int, str]] = [
    (
        "victory cup", None, 10,
        "Victory Cups are casual/promotional lobbies, never real competitive tiers -- never auto-tracked.",
    ),
    (
        "skin cup", None, 10,
        "Skin/crossover-themed cups (e.g. a character-branded 'Cup') are promotional, not competitive -- never auto-tracked.",
    ),
    (
        "reload cash cup", TournamentType.CASH_CUP, 20,
        "Reload Cash Cup Finals lobby -- Cash Cup tier.",
    ),
    (
        "fncs division", TournamentType.CASH_CUP, 21,
        "FNCS Division practice finals (any region) are tracked as Cash Cup tier, not FNCS tier, per the "
        "product decision that these pay out like a Cash Cup, not like real FNCS.",
    ),
    (
        "cash cup", TournamentType.CASH_CUP, 25,
        "Any other Cash Cup Finals lobby not already matched above.",
    ),
    (
        "esports world cup", TournamentType.GLOBAL_CHAMPIONSHIP, 30,
        "EWC (Esports World Cup) -- Global tier, same pool as FNCS Globals.",
    ),
    (
        "ewc", TournamentType.GLOBAL_CHAMPIONSHIP, 31,
        "EWC abbreviation, same as 'esports world cup' above.",
    ),
    (
        "fncs global", TournamentType.GLOBAL_CHAMPIONSHIP, 32,
        "FNCS Global Championship -- Global tier.",
    ),
    (
        "fncs finals", TournamentType.FNCS_FINALS, 40,
        "Basic FNCS Finals -- auto-tracked once per season, and skipped entirely during a season that has a "
        "Globals event instead (see osirion_service.auto_track_new_tournaments for that dedup logic).",
    ),
]


def seed_default_rules(db: Session) -> None:
    if db.query(TournamentClassificationRule).count() > 0:
        return
    for pattern, tournament_type, priority, description in DEFAULT_RULES:
        db.add(
            TournamentClassificationRule(
                pattern=pattern,
                tournament_type=tournament_type,
                priority=priority,
                is_active=True,
                description=description,
            )
        )
    db.flush()


def get_active_rules(db: Session) -> list[TournamentClassificationRule]:
    seed_default_rules(db)
    return (
        db.query(TournamentClassificationRule)
        .filter(TournamentClassificationRule.is_active.is_(True))
        .order_by(TournamentClassificationRule.priority.asc())
        .all()
    )


def get_all_rules(db: Session) -> list[TournamentClassificationRule]:
    """Includes inactive rules too -- used by the admin listing endpoint so
    a disabled rule doesn't just silently disappear from view."""
    seed_default_rules(db)
    return db.query(TournamentClassificationRule).order_by(TournamentClassificationRule.priority.asc()).all()


def create_rule(
    db: Session,
    *,
    pattern: str,
    tournament_type: TournamentType | None,
    priority: int = 100,
    is_active: bool = True,
    description: str | None = None,
) -> TournamentClassificationRule:
    seed_default_rules(db)  # so a brand-new DB's first admin action doesn't race the seed
    rule = TournamentClassificationRule(
        id=uuid.uuid4(),
        pattern=pattern,
        tournament_type=tournament_type,
        priority=priority,
        is_active=is_active,
        description=description,
    )
    db.add(rule)
    db.flush()
    return rule


def update_rule(
    db: Session,
    rule_id: uuid.UUID,
    *,
    pattern: str | None = None,
    tournament_type: TournamentType | None = None,
    clear_tournament_type: bool = False,
    priority: int | None = None,
    is_active: bool | None = None,
    description: str | None = None,
) -> TournamentClassificationRule:
    rule = db.get(TournamentClassificationRule, rule_id)
    if rule is None:
        raise ValueError(f"classification rule {rule_id} not found")
    if pattern is not None:
        rule.pattern = pattern
    if clear_tournament_type:
        rule.tournament_type = None
    elif tournament_type is not None:
        rule.tournament_type = tournament_type
    if priority is not None:
        rule.priority = priority
    if is_active is not None:
        rule.is_active = is_active
    if description is not None:
        rule.description = description
    db.flush()
    return rule


def delete_rule(db: Session, rule_id: uuid.UUID) -> None:
    rule = db.get(TournamentClassificationRule, rule_id)
    if rule is None:
        raise ValueError(f"classification rule {rule_id} not found")
    db.delete(rule)
    db.flush()


def classify(db: Session, display_name: str) -> TournamentType | None:
    """Returns the TournamentType to auto-track `display_name` as, or None
    if it should NOT be auto-tracked (either an explicit exclude rule
    matched, or nothing matched at all -- see this module's docstring for
    why those are treated the same)."""
    haystack = display_name.lower()
    for rule in get_active_rules(db):
        if rule.pattern.lower() in haystack:
            return rule.tournament_type
    return None
