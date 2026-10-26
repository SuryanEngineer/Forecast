"""
Pure maths for turning earlier-round (qualifier) results into expectations about a Finals. No database, no I/O.

Everything is on a 0..1 "strength" scale where 1 is best:
  q   -- qualifier strength: log-scaled finishing rank in an open field (see qual_score)
  s   -- finals strength: 1 - (placement-1)/(field-1), i.e. 1.0 for the win, 0.0 for last place

The relationship between the two is LEARNED from past events (fit_line / qualify_rates) with shrinkage toward sensible
priors, so with little history the bots lean on the prior and as qualifier data accumulates they lean on what the data says.
"""
from __future__ import annotations

import math


def qual_score(rank: int, field_estimate: int | None) -> float:
    """1 = won the round, 0 = last. Log-scaled: 1st vs 100th matters far more than 20,000th vs 20,100th."""
    if rank <= 1:
        return 1.0
    field = max(int(field_estimate or 0), rank, 2)
    return max(0.0, min(1.0, 1.0 - math.log(rank) / math.log(field)))


def final_strength(placement: int, field_size: int) -> float:
    if field_size <= 1:
        return 0.5
    return max(0.0, min(1.0, 1.0 - (placement - 1) / (field_size - 1)))


def placement_from_strength(s: float, field_size: int) -> int:
    return max(1, min(field_size, int(round(1 + (1.0 - s) * (field_size - 1)))))


def weighted_qual(rounds: list[tuple[int, float]]) -> float | None:
    """Combine a player's round strengths (stage_index, q). Later rounds count more (they are closer to the Finals and
    played against a stronger, filtered field): weight = stage_index."""
    if not rounds:
        return None
    num = sum(stage * q for stage, q in rounds)
    den = sum(stage for stage, _ in rounds)
    return num / den if den > 0 else None


def fit_line(pairs: list[tuple[float, float]], prior_a: float = 0.30, prior_b: float = 0.45, k: float = 40.0) -> tuple[float, float, float, int]:
    """Least-squares s = a + b*q, shrunk toward (prior_a, prior_b) with strength k pseudo-observations.
    Returns (a, b, residual_sd, n)."""
    n = len(pairs)
    if n < 3:
        return prior_a, prior_b, 0.28, n
    mx = sum(q for q, _ in pairs) / n
    my = sum(s for _, s in pairs) / n
    sxx = sum((q - mx) ** 2 for q, _ in pairs)
    if sxx < 1e-9:
        return prior_a, prior_b, 0.28, n
    b_ols = sum((q - mx) * (s - my) for q, s in pairs) / sxx
    a_ols = my - b_ols * mx
    w = n / (n + k)
    b = w * b_ols + (1 - w) * prior_b
    a = w * a_ols + (1 - w) * prior_a
    resid = [s - (a + b * q) for q, s in pairs]
    sd = math.sqrt(sum(r * r for r in resid) / max(1, n - 2))
    return a, b, max(0.05, sd), n


DEFAULT_QUALIFY_PRIOR = (0.05, 0.20, 0.45, 0.70, 0.90)  # by q bucket 0-.2, .2-.4, .4-.6, .6-.8, .8-1


def qualify_rates(rows: list[tuple[float, bool]], prior: tuple[float, ...] = DEFAULT_QUALIFY_PRIOR, strength: float = 6.0) -> list[float]:
    """P(makes the Finals | qualifier strength bucket), smoothed toward the prior (Beta pseudo-counts)."""
    nb = len(prior)
    hits = [0.0] * nb
    tot = [0.0] * nb
    for q, ok in rows:
        i = min(nb - 1, max(0, int(q * nb)))
        tot[i] += 1.0
        hits[i] += 1.0 if ok else 0.0
    return [(hits[i] + prior[i] * strength) / (tot[i] + strength) for i in range(nb)]


def p_qualify(q: float, rates: list[float]) -> float:
    """Interpolate the bucketed rate at q (bucket centres at (i+.5)/n)."""
    nb = len(rates)
    x = q * nb - 0.5
    if x <= 0:
        return rates[0]
    if x >= nb - 1:
        return rates[-1]
    i = int(x)
    f = x - i
    return rates[i] * (1 - f) + rates[i + 1] * f


def expected_strength(a: float, b: float, q: float, team_prior: float | None = None, n_rounds: int = 1, team_weight: float = 1.0) -> float:
    """Expected finals strength for someone with qualifier strength q, blended with how strong their team is on paper
    (their and their teammates' career strength). More rounds of evidence -> trust the qualifiers more."""
    s = a + b * q
    if team_prior is not None:
        evidence = 1.0 + 0.5 * max(0, n_rounds - 1)
        s = (evidence * s + team_weight * team_prior) / (evidence + team_weight)
    return max(0.02, min(0.98, s))
