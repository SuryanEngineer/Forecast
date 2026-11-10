"""
Per-event payout SHAPE rules (pure, no database).

Most events pay the whole field: the placement curve's explicit top places, then a smooth tail down to last place (see
dividend_calculator.placement_payout_fraction). A few events pay only their top N: the whole pool is split between those N
places and everyone below earns nothing. The Arenas Cash Cup is one round and pays the top 10 only.

Implemented as a per-event CURVE, so every place that already prices a placement through
`placement_payout_fraction(place, field, curve)` (dividend payouts, previews, the bots' valuations, the fair price, the
player history) gets the right answer just by being handed `curve_for(curve, tournament.name)` instead of the global curve:
a curve whose entries add up to 1 leaves no tail budget, so every place past N is worth exactly 0.
"""
from __future__ import annotations

from decimal import Decimal

from app.engine.dividend_calculator import DEFAULT_PLACEMENT_CURVE

# (case-insensitive substring of the tournament's name, number of paid places). First match wins.
PAID_PLACES_BY_NAME: tuple[tuple[str, int], ...] = (
    ("arenas cash cup", 10),
)

_SIX = Decimal("0.000001")


def paid_places(name: str | None) -> int | None:
    """How many places this event pays, or None when it pays the whole field."""
    text = (name or "").lower()
    for needle, places in PAID_PLACES_BY_NAME:
        if needle in text:
            return places
    return None


def top_n_curve(curve: dict[int, Decimal], places: int) -> dict[int, Decimal]:
    """The first `places` entries of `curve`, rescaled so they add up to exactly 1 (the whole pool goes to the top N, in the
    same proportions the normal curve gives them). Places the curve doesn't list fall back to the built-in default curve,
    then to the smallest listed share, so an admin-trimmed curve can't leave a paid place at 0."""
    base = {p: Decimal(str(v)) for p, v in curve.items() if v is not None}
    positives = [v for v in base.values() if v > 0] or [Decimal(str(v)) for v in DEFAULT_PLACEMENT_CURVE.values()]
    floor = min(positives)
    raw: dict[int, Decimal] = {}
    for p in range(1, places + 1):
        v = base.get(p)
        if v is None or v <= 0:
            v = Decimal(str(DEFAULT_PLACEMENT_CURVE.get(p, floor)))
        raw[p] = v
    total = sum(raw.values(), Decimal("0"))
    out = {p: (v / total).quantize(_SIX) for p, v in raw.items()}
    # rounding dust goes to 1st place so the shares add up to exactly 1 (no pool is created or lost)
    out[1] += Decimal("1") - sum(out.values(), Decimal("0"))
    return out


def curve_for(curve: dict[int, Decimal], name: str | None) -> dict[int, Decimal]:
    """The curve to use for the event called `name`: the global curve, or its top-N version for a top-N event."""
    n = paid_places(name)
    return curve if n is None else top_n_curve(curve, n)
