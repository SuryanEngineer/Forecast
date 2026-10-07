#!/usr/bin/env python3
"""
Find tournament FINALS straight from Osirion's own tournament details -- no name rules needed.

A window counts as a finals when ALL of these hold:
  1. CASH PRIZE      its score location pays real money (rewardType "ecomm" with quantity > 0 -- NOT tokens and
                     NOT in-game "game" items).
  2. SCORING         its scoringRules award BOTH kill/elimination points (an *ELIMS* stat with points > 0) AND
                     placement points beyond just winning (PLACEMENT stat with points for places other than 1st).
  3. FINALS LOBBY    the leaderboard is one small field: <= 100 entries for Battle Royale, <= 40 for Reload
                     (and >= --min-field). Open qualifier / cup lobbies have hundreds or thousands of entrants.
Per event, only the highest-paying window that passes is kept (so heats / earlier rounds of the same event drop out).

Also required: dated --min-year or later, region NAC/EU or ONSITE (LAN), not Zero Build, window already ended.
Explicit exclude rules in tournament_classification_service (Performance Evaluation, Victory Cup) are still honoured
unless you pass --ignore-exclude-rules.

Dry run by default: prints every candidate with the numbers behind its verdict (scoring tiers, payout, field size).
--confirm tracks + syncs the PASS rows, hidden-from-live-loop and finalized WITHOUT dividends.

    python3 scripts/discover_finals.py                       # dry run, shows what passes
    python3 scripts/discover_finals.py --show-failed         # also show why others failed
    python3 scripts/discover_finals.py --grep "solo"         # filter by name/group/event id
    python3 scripts/discover_finals.py --confirm
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.integrations import osirion_client  # noqa: E402
from app.integrations.osirion_client import OsirionApiError  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.models.tournament import TournamentType  # noqa: E402
from app.services import osirion_service, tournament_classification_service  # noqa: E402


# ---------- checks on the tournament details (listing) ----------

def _score_location(window) -> dict:
    """The raw scoreLocation dict matching the leaderboard ids this AvailableWindow will actually query."""
    for sl in window.raw_event_window.get("scoreLocations", []):
        if (sl.get("leaderboardEventId") == window.leaderboard_event_id
                and sl.get("leaderboardEventWindowId") == window.leaderboard_event_window_id):
            return sl
    return {}


def cash_prize(sl: dict) -> Decimal:
    """Top real-money (ecomm, USD) payout in this score location. 0 if none."""
    top = Decimal("0")
    for table in sl.get("payoutTables") or []:
        for rank in table.get("ranks") or []:
            for p in rank.get("payouts") or []:
                if (p.get("rewardType") or "").lower() == "ecomm":
                    try:
                        q = Decimal(str(p.get("quantity") or 0))
                    except Exception:  # noqa: BLE001
                        q = Decimal("0")
                    top = max(top, q)
    return top


def scoring_summary(sl: dict) -> tuple[bool, bool, str]:
    """(has_kill_points, has_placement_points_beyond_win, human summary)."""
    kill = False
    place = False
    place_tiers = 0
    for rule in sl.get("scoringRules") or []:
        stat = (rule.get("trackedStat") or "").upper()
        tiers = rule.get("rewardTiers") or []
        if "ELIM" in stat:
            kill = kill or any((t.get("pointsEarned") or 0) > 0 for t in tiers)
        elif "PLACEMENT" in stat:
            place_tiers = max(place_tiers, len(tiers))
            # points for any place other than 1st (keyValue > 1), i.e. more than a bare win bonus
            place = place or any((t.get("keyValue") or 0) > 1 and (t.get("pointsEarned") or 0) > 0 for t in tiers)
    return kill, place, f"kill={'Y' if kill else 'N'} placement-tiers={place_tiers}{'(beyond win)' if place else '(win only)'}"


def is_reload(window) -> bool:
    text = f"{window.display_name} {window.event_group} {window.event_id} {window.raw_event_window.get('playlistId', '')}".lower()
    return "reload" in text or "_re_" in text or "rescup" in text


# ---------- check on the leaderboard (field size) ----------

def field_size(window) -> tuple[int | None, int | None, str]:
    """(entries, players, note). Costs 1 request (2 if the leaderboard is paged). None = could not tell."""
    lb, lw = window.leaderboard_event_id, window.leaderboard_event_window_id
    try:
        page0 = osirion_client.get_leaderboard_page(lb, lw, 0)
    except OsirionApiError as exc:
        return None, None, f"leaderboard error: {exc}"
    entries0 = page0.get("entries") or []
    total_pages = int(page0.get("totalPages") or 1)
    per_page = len(entries0)
    if total_pages <= 1:
        entries = entries0
    else:
        # More than one page => the field is larger than a page. Only fetch the last page if the total could
        # still be small (tiny page size); otherwise it is certainly a big open field.
        if per_page * (total_pages - 1) > 200:
            return per_page * (total_pages - 1), None, f"{total_pages} pages"
        try:
            last = osirion_client.get_leaderboard_page(lb, lw, total_pages - 1).get("entries") or []
        except OsirionApiError as exc:
            return None, None, f"leaderboard error: {exc}"
        entries = entries0 + last  # good enough: only used for a <=200 sanity bound
        return per_page * (total_pages - 1) + len(last), None, f"{total_pages} pages"
    players = sum(len(e.get("players") or []) or 1 for e in entries)
    return len(entries), players, ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--min-year", type=int, default=datetime.now().year)
    ap.add_argument("--regions", nargs="+", default=["NAC", "EU", "ONSITE"])
    ap.add_argument("--max-br", type=int, default=100, help="Max entries in a Battle Royale finals lobby (default 100).")
    ap.add_argument("--max-reload", type=int, default=40, help="Max entries in a Reload finals lobby (default 40).")
    ap.add_argument("--min-field", type=int, default=10, help="Min entries for a real finals field (default 10).")
    ap.add_argument("--min-cash", type=float, default=0.0, help="Min top cash prize in USD (default: any > 0).")
    ap.add_argument("--ignore-exclude-rules", action="store_true")
    ap.add_argument("--grep", default="")
    ap.add_argument("--show-failed", action="store_true")
    ap.add_argument("--attempts", type=int, default=6)
    ap.add_argument("--retry-wait", type=int, default=30)
    args = ap.parse_args()
    regions = {r.upper() for r in args.regions}
    now = datetime.now(timezone.utc)

    db = SessionLocal()
    db.expire_on_commit = False
    try:
        print("Fetching Osirion tournament details (incl. history) ...")
        windows = osirion_service.list_available_windows(include_historic_data=True)
        tracked = {(m.leaderboard_event_id, m.leaderboard_event_window_id) for m in db.query(OsirionTournamentMapping).all()}
        rules = tournament_classification_service.get_active_rules(db)

        by_event: dict[str, list] = {}
        for w in windows:
            by_event.setdefault(w.event_id, []).append(w)

        failed: list[tuple] = []
        cheap_pass: list[tuple] = []
        for event_id, group in by_event.items():
            best = None
            best_cash = Decimal("-1")
            reasons = []
            for w in group:
                when = w.begin_time or w.end_time
                if when is None or when.year < args.min_year:
                    continue
                hay = f"{w.display_name} {w.event_group} {w.event_id}".lower()
                if args.grep and args.grep.lower() not in hay:
                    continue
                if w.is_zero_build:
                    reasons.append((w, "zero build"))
                    continue
                if not (regions & {r.upper() for r in w.regions}):
                    reasons.append((w, f"region {w.regions}"))
                    continue
                end = w.end_time
                if end is not None and (end if end.tzinfo else end.replace(tzinfo=timezone.utc)) >= now:
                    reasons.append((w, "not ended yet"))
                    continue
                hit = None if args.ignore_exclude_rules else next(
                    (r for r in rules if r.pattern.lower() in w.classification_text.lower()), None)
                if hit is not None and hit.tournament_type is None:
                    reasons.append((w, f"excluded by rule '{hit.pattern}'"))
                    continue
                sl = _score_location(w)
                cash = cash_prize(sl)
                if cash <= 0 or float(cash) < args.min_cash:
                    reasons.append((w, "no cash prize"))
                    continue
                kill, place, summary = scoring_summary(sl)
                if not (kill and place):
                    reasons.append((w, f"scoring: {summary}"))
                    continue
                if cash > best_cash:
                    best, best_cash = (w, hit, cash, summary), cash
            if best is not None:
                cheap_pass.append(best)
            else:
                for w, why in reasons[:1]:
                    failed.append((w, why))

        print(f"{len(by_event)} events; {len(cheap_pass)} pass cash+scoring+scope; checking each one's lobby size "
              f"({len(cheap_pass)} leaderboard request(s)) ...")
        passed = []
        for n, (w, hit, cash, summary) in enumerate(sorted(cheap_pass, key=lambda t: t[0].begin_time or t[0].end_time), 1):
            if (w.leaderboard_event_id, w.leaderboard_event_window_id) in tracked:
                failed.append((w, "already tracked"))
                continue
            entries, players, note = field_size(w)
            cap = args.max_reload if is_reload(w) else args.max_br
            if entries is None:
                failed.append((w, f"lobby size unknown ({note})"))
            elif entries > cap:
                failed.append((w, f"field {entries} entries > {cap} cap ({'reload' if is_reload(w) else 'BR'}) {note}"))
            elif entries < args.min_field:
                failed.append((w, f"field only {entries} entries"))
            else:
                passed.append((w, hit, cash, summary, entries, players))

        def derive_type(w, hit, cash) -> TournamentType:
            if hit is not None and hit.tournament_type is not None:
                return hit.tournament_type
            if "ONSITE" in {r.upper() for r in w.regions}:
                return TournamentType.MAJOR
            if cash >= 50000:
                return TournamentType.MAJOR
            return TournamentType.CASH_CUP

        passed.sort(key=lambda t: t[0].begin_time or t[0].end_time)
        print(f"\nPASS ({len(passed)}):")
        for w, hit, cash, summary, entries, players in passed:
            ttype = derive_type(w, hit, cash)
            print(f"  {str((w.begin_time or w.end_time).date()):<11} {ttype.value:<20} ${float(cash):>10,.0f}  "
                  f"field={entries}{f'/{players}p' if players else ''}  {summary}  {w.display_name}  [{w.event_group}]")

        print(f"\nFAILED / SKIPPED: {len(failed)}")
        summary_counts: dict[str, int] = {}
        for _, why in failed:
            key = why.split(":")[0].split(" (")[0]
            key = "field too large" if why.startswith("field ") and "cap" in why else key
            summary_counts[key] = summary_counts.get(key, 0) + 1
        for k, v in sorted(summary_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {v:>4}  {k}")
        if args.show_failed:
            for w, why in sorted(failed, key=lambda t: t[0].begin_time or t[0].end_time or now):
                print(f"  {str((w.begin_time or w.end_time).date()) if (w.begin_time or w.end_time) else '?':<11} "
                      f"{w.display_name}  [{why}]")

        if not args.confirm:
            print("\nDry run only. Re-run with --confirm to track + sync the PASS rows (no dividends).")
            return

        for n, (w, hit, cash, summary, entries, players) in enumerate(passed, start=1):
            print(f"\n[{n}/{len(passed)}] {w.display_name!r} ...", flush=True)
            region = w.regions[0] if len(w.regions) == 1 else None
            mapping = osirion_service.track_tournament(
                db, name=w.display_name, tournament_type=derive_type(w, hit, cash), region=region,
                window=w, created_by_admin_id=None, is_historical_archive=True,
            )
            for attempt in range(1, args.attempts + 1):
                r = osirion_service.sync_tournament(db, mapping, skip_finalize=True)
                print(f"    attempt {attempt}: {r.entries_seen} entries, {r.matched} matched"
                      + (f", ERROR: {r.error}" if r.error else "") + (", finalized" if r.finalized else ""))
                if r.finalized or not r.error:
                    break
                time.sleep(args.retry_wait)
        print("\nDone. Next: list_tournaments.py --year 2026, deactivate_out_of_scope_players.py, merge_from_linker.py.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
