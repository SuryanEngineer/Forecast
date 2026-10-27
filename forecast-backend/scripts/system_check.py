#!/usr/bin/env python3
"""
Forecast SYSTEM CHECK -- exercises every major component end-to-end against a THROWAWAY SQLite database (it never
touches your real Supabase/Postgres data, .env, or Redis) and prints PASS/FAIL for each check.

    cd forecast-backend
    python3 scripts/system_check.py            # full run (~20-40 s; includes two short sleeps for dividend timing)
    python3 scripts/system_check.py --keep     # keep the temp database file for inspection

Covers: registration / validation / usernames, login + lockout, emailed reset codes (wrong code, reuse, token
revocation), email verification + change, profile (name cooldown, tags, password change, delete), session heartbeats,
trading (limit / quick / fees / ledger reconciliation / share conservation), TOURNAMENT -> DIVIDEND payouts (record
date, conservation, no double pay, stuck-payout sweeper, fewer-holders rounding guard), treasury accrual, seasons
(SP maths, ranks, finalize, history), lifetime stats identities, daily snapshots, leaderboards, analytics report, and a
bot tick. Exit code is non-zero if anything fails.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

parser = argparse.ArgumentParser()
parser.add_argument("--keep", action="store_true")
ARGS = parser.parse_args()

# ---- Isolated environment: MUST be set before any `app` import --------------------------------------------------
_TMP = tempfile.mkdtemp(prefix="forecast_check_")
_DB_FILE = os.path.join(_TMP, "check.db")
os.environ.update({
    "FORECAST_ENV_FILE": os.path.join(_TMP, "does-not-exist.env"),
    "DATABASE_URL": f"sqlite:///{_DB_FILE}",
    "REDIS_ENABLED": "false",
    "DEMO_MODE": "false",
    "BOT_TRADING_ENABLED": "false",
    "OSIRION_SYNC_ENABLED": "false",
    "EMAIL_PROVIDER": "console",
    "EMAIL_CODE_MIN_RESEND_SECONDS": "0",
    "EMAIL_CODE_MAX_PER_HOUR": "100",
    "JWT_SECRET_KEY": "system-check-secret",
})
sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
import app.models  # noqa: E402,F401
from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models.account import PortfolioSnapshot, SeasonEntry, UserSession  # noqa: E402
from app.models.dividend import DividendLineItem, DividendPayout, DividendPayoutStatus  # noqa: E402
from app.models.order import OrderSide  # noqa: E402
from app.models.player import Position  # noqa: E402
from app.models.tournament import Tournament, TournamentStatus, TournamentType  # noqa: E402
from app.models.treasury import TreasuryHolding  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.wallet import LedgerEntry, LedgerEntryType, Wallet  # noqa: E402
from app.engine.dividend_calculator import compute_dividend_distribution  # noqa: E402
from app.services import (  # noqa: E402
    account_service, analytics_service, bot_trading_service, book_registry, economic_params_service, email_service,
    house_account, leaderboard_service, maintenance_service, order_service, player_service, portfolio_service,
    season_service, stats_service, tournament_service, treasury_service, wallet_service,
)

# ---- tiny harness ------------------------------------------------------------------------------------------------
RESULTS: list[tuple[str, bool, str]] = []
_section = ""


def section(name: str) -> None:
    global _section
    _section = name
    print(f"\n== {name} ==")


def check(label: str, cond: bool, detail: str = "") -> bool:
    RESULTS.append((f"{_section}: {label}", bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  -- {detail}" if detail and not cond else ""))
    return bool(cond)


def guarded(fn):
    """Run a section; an unexpected exception becomes a FAIL (with traceback) instead of aborting the whole run."""
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except Exception as exc:  # noqa: BLE001
            check(f"{fn.__name__} ran without crashing", False, f"{type(exc).__name__}: {exc}")
            traceback.print_exc()
    return wrapper


OUTBOX: list[dict] = []


def _capture(to_email, subject, text_body, html_body=None):
    OUTBOX.append({"to": to_email, "subject": subject, "text": text_body, "html": html_body})
    return True


email_service.send_email = _capture  # nothing is ever really sent


def last_code(to: str) -> str | None:
    for m in reversed(OUTBOX):
        if m["to"] == to:
            found = re.search(r"\b(\d{6})\b", m["subject"]) or re.search(r"\b(\d{6})\b", m["text"])
            if found:
                return found.group(1)
    return None


client = TestClient(app)  # (no `with`: skips the background loops in lifespan)
PW = "Sup3rSecret!"


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def register(email: str, name: str, password: str = PW, terms: bool = True):
    return client.post("/api/v1/auth/register", json={"email": email, "password": password, "display_name": name, "accept_terms": terms})


# =====================================================================================================================
@guarded
def check_pure_logic() -> None:
    section("Pure logic")
    # Dividend maths: conservation incl. awkward rounding.
    per, pays, fee = compute_dividend_distribution(Decimal("1000.01"), Decimal("1000"), [("a", Decimal("333")), ("b", Decimal("667"))], Decimal("0.05"))
    check("dividend payouts + fee == pool exactly (largest-remainder rounding)", sum(a for _, a in pays) + fee == Decimal("1000.01"), f"{sum(a for _, a in pays)} + {fee}")
    # Holders hold LESS than shares_outstanding: must not over-pay.
    per2, pays2, fee2 = compute_dividend_distribution(Decimal("1000.00"), Decimal("1000"), [("a", Decimal("10"))], Decimal("0"))
    check("holders owning only 10/1000 shares receive exactly 10 x per-share (no over-pay)", pays2[0][1] == Decimal("10.00"), str(pays2))
    # Season maths
    check("SP never negative", season_service.points_for_return(-20.0) == 0)
    check("+10% return = 500 SP = Gold I", season_service.points_for_return(10.0) == 500 and season_service.rank_for_points(500) == "Gold I")
    check("80% return = Unreal", season_service.rank_for_points(season_service.points_for_return(80.0)) == "Unreal")
    check("rank steps are ordered", [r for r, _ in season_service.RANKS][0] == "Bronze I" and [r for r, _ in season_service.RANKS][-1] == "Unreal")
    # Names / validation
    db = SessionLocal()
    try:
        ok = lambda n: _raises(lambda: account_service.validate_display_name(db, n)) is None  # noqa: E731
        check("good usernames accepted", ok("jakelopez04") and ok("sweatybanana") and ok("Grape_Fan"))
        check("too short / bad chars / reserved rejected", not ok("ab") and not ok("bad name!") and not ok("admin"))
        check("profanity (incl. leetspeak) rejected", not ok("fuuuck_you") and not ok("sh1thead") and not ok("DickPro"))
        check("innocent look-alikes accepted (grape, peacock)", ok("grapejuice") and ok("peacock77"))
    finally:
        db.close()
    check("weak passwords rejected", _raises(lambda: account_service.validate_password("short1")) is not None
          and _raises(lambda: account_service.validate_password("allletters")) is not None
          and _raises(lambda: account_service.validate_password("Sup3rSecret!")) is None)


def _raises(fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        return exc
    return None


# =====================================================================================================================
@guarded
def check_auth_flows() -> None:
    section("Registration & login")
    r = register("alice@forecastcheck.dev", "alice_a", terms=False)
    check("registration requires accepting terms", r.status_code == 400, r.text)
    r = register("alice@forecastcheck.dev", "alice_a", password="short")
    check("short password rejected", r.status_code in (400, 422), r.text)
    r = register("alice@forecastcheck.dev", "alice_a")
    check("register OK", r.status_code == 201, r.text)
    token_a = r.json().get("access_token", "")
    check("duplicate email rejected (case-insensitive)", register("ALICE@forecastcheck.dev", "other_name").status_code == 409)
    check("duplicate username rejected (case-insensitive)", register("x@forecastcheck.dev", "ALICE_A").status_code == 400)
    check("verification email was sent at signup", last_code("alice@forecastcheck.dev") is not None)

    me = client.get("/api/v1/auth/me", headers=auth(token_a)).json()
    check("/auth/me returns profile fields", me.get("display_name") == "alice_a" and me.get("email_verified") is False, str(me))

    w = client.get("/api/v1/wallet/me", headers=auth(token_a)).json()
    start = economic_params_service.DEFAULTS["wallet.starting_balance"][0]
    check("new user got the starting balance", Decimal(str(w["cash_balance"])) == Decimal(start), str(w))

    check("login works (email is case-insensitive)", client.post("/api/v1/auth/login", json={"email": "ALICE@forecastcheck.dev", "password": PW}).status_code == 200)
    bad = client.post("/api/v1/auth/login", json={"email": "alice@forecastcheck.dev", "password": "wrong-pass1"})
    nouser = client.post("/api/v1/auth/login", json={"email": "ghost@forecastcheck.dev", "password": "wrong-pass1"})
    check("wrong password and unknown email give the SAME error", bad.status_code == 401 and nouser.status_code == 401 and bad.json() == nouser.json())

    # lockout
    register("lock@forecastcheck.dev", "lock_me")
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        client.post("/api/v1/auth/login", json={"email": "lock@forecastcheck.dev", "password": "nope-nope1"})
    r = client.post("/api/v1/auth/login", json={"email": "lock@forecastcheck.dev", "password": PW})
    check(f"account locks after {settings.LOGIN_MAX_FAILED_ATTEMPTS} failures (even with the right password)", r.status_code == 429, r.text)

    section("Email verification")
    code = last_code("alice@forecastcheck.dev")
    r = client.post("/api/v1/auth/email/verify", json={"code": "000000" if code != "000000" else "111111"}, headers=auth(token_a))
    check("wrong verification code rejected", r.status_code == 400)
    r = client.post("/api/v1/auth/email/verify", json={"code": code}, headers=auth(token_a))
    check("correct verification code accepted", r.status_code == 200, r.text)
    check("email now verified", client.get("/api/v1/auth/me", headers=auth(token_a)).json()["email_verified"] is True)

    section("Forgot password (emailed code)")
    n_before = len(OUTBOX)
    r = client.post("/api/v1/auth/password-reset/request", json={"email": "alice@forecastcheck.dev"})
    r2 = client.post("/api/v1/auth/password-reset/request", json={"email": "nobody@forecastcheck.dev"})
    check("request returns the same message for real and unknown emails", r.status_code == 200 and r.json() == r2.json())
    check("exactly one email was sent (only for the real account)", len(OUTBOX) == n_before + 1 and OUTBOX[-1]["to"] == "alice@forecastcheck.dev")
    mail = OUTBOX[-1]
    check("email is multipart: has plain text + HTML body and a no-reply footer", bool(mail["html"]) and "no-reply" in mail["text"].lower())
    code = last_code("alice@forecastcheck.dev")
    check("code is 6 digits", bool(code) and len(code) == 6)
    r = client.post("/api/v1/auth/password-reset/confirm", json={"email": "alice@forecastcheck.dev", "code": "123456" if code != "123456" else "654321", "new_password": "NewPass123"})
    check("wrong code rejected", r.status_code == 400)
    r = client.post("/api/v1/auth/password-reset/confirm", json={"email": "alice@forecastcheck.dev", "code": code, "new_password": "weak"})
    check("weak new password rejected (code not burned)", r.status_code in (400, 422))
    time.sleep(1.1)  # token iat has 1-second resolution
    r = client.post("/api/v1/auth/password-reset/confirm", json={"email": "alice@forecastcheck.dev", "code": code, "new_password": "NewPass123"})
    check("correct code resets the password", r.status_code == 200, r.text)
    check("old password no longer works", client.post("/api/v1/auth/login", json={"email": "alice@forecastcheck.dev", "password": PW}).status_code == 401)
    r = client.post("/api/v1/auth/login", json={"email": "alice@forecastcheck.dev", "password": "NewPass123"})
    check("new password works", r.status_code == 200)
    check("tokens issued before the reset are revoked", client.get("/api/v1/auth/me", headers=auth(token_a)).status_code == 401)
    r = client.post("/api/v1/auth/password-reset/confirm", json={"email": "alice@forecastcheck.dev", "code": code, "new_password": "Another123"})
    check("a used code can't be reused", r.status_code == 400)
    # attempt limit
    client.post("/api/v1/auth/password-reset/request", json={"email": "alice@forecastcheck.dev"})
    good = last_code("alice@forecastcheck.dev")
    for i in range(settings.EMAIL_CODE_MAX_ATTEMPTS):
        client.post("/api/v1/auth/password-reset/confirm", json={"email": "alice@forecastcheck.dev", "code": f"{i:06d}" if f"{i:06d}" != good else "999999", "new_password": "Another123"})
    r = client.post("/api/v1/auth/password-reset/confirm", json={"email": "alice@forecastcheck.dev", "code": good, "new_password": "Another123"})
    check(f"code burns after {settings.EMAIL_CODE_MAX_ATTEMPTS} wrong guesses (brute-force protection)", r.status_code == 400)


@guarded
def check_profile_and_sessions() -> None:
    section("Profile / settings")
    token = client.post("/api/v1/auth/login", json={"email": "alice@forecastcheck.dev", "password": "NewPass123"}).json()["access_token"]
    h = auth(token)
    r = client.get("/api/v1/account/profile", headers=h)
    check("profile loads", r.status_code == 200 and r.json()["display_name"] == "alice_a", r.text)
    r = client.post("/api/v1/account/display-name", json={"display_name": "fuck_off"}, headers=h)
    check("inappropriate username refused", r.status_code == 400)
    r = client.post("/api/v1/account/display-name", json={"display_name": "alice_new"}, headers=h)
    check("username change works", r.status_code == 200 and r.json()["display_name"] == "alice_new", r.text)
    r = client.post("/api/v1/account/display-name", json={"display_name": "alice_new2"}, headers=h)
    check("second change blocked by cooldown", r.status_code == 400 and "again" in r.text.lower(), r.text)
    r = client.post("/api/v1/account/tag", json={"tag": "fcst", "tag_color": "#00C8FF"}, headers=h)
    check("tag saved (uppercased)", r.status_code == 200 and r.json()["tag"] == "FCST", r.text)
    r = client.post("/api/v1/account/tag", json={"tag": "x", "tag_color": "#00C8FF"}, headers=h)
    check("1-character tag refused", r.status_code == 400)
    r = client.post("/api/v1/account/tag", json={"tag": "ABC", "tag_color": "#123456"}, headers=h)
    check("off-palette tag colour refused", r.status_code == 400)

    r = client.post("/api/v1/account/change-password", json={"current_password": "wrong-pass1", "new_password": "Brand New 1"}, headers=h)
    check("change password requires the CURRENT password", r.status_code == 400)
    time.sleep(1.1)
    r = client.post("/api/v1/account/change-password", json={"current_password": "NewPass123", "new_password": "Brand New 1"}, headers=h)
    check("change password works and returns a fresh token", r.status_code == 200 and "access_token" in r.json(), r.text)
    fresh = r.json().get("access_token", "")
    check("old token revoked, fresh token valid", client.get("/api/v1/auth/me", headers=h).status_code == 401 and client.get("/api/v1/auth/me", headers=auth(fresh)).status_code == 200)

    # email change
    h = auth(fresh)
    r = client.post("/api/v1/account/email/request-change", json={"new_email": "alice2@forecastcheck.dev", "password": "Brand New 1"}, headers=h)
    check("email change code requested", r.status_code == 200, r.text)
    code = last_code("alice2@forecastcheck.dev")
    r = client.post("/api/v1/account/email/confirm-change", json={"code": code}, headers=h)
    check("email change confirmed with code sent to NEW address", r.status_code == 200 and r.json()["email"] == "alice2@forecastcheck.dev", r.text)

    section("Sessions / analytics tracking")
    r = client.post("/api/v1/auth/heartbeat", headers=h)
    check("heartbeat accepted", r.status_code == 200)
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == "alice2@forecastcheck.dev").one()
        n = db.query(UserSession).filter(UserSession.user_id == u.id).count()
        check("login/register/heartbeat created session rows", n >= 1, f"sessions={n}")
        check("last_login_at / login_count recorded", u.last_login_at is not None and (u.login_count or 0) >= 2, f"count={u.login_count}")
    finally:
        db.close()
    r = client.get("/api/v1/account/sessions", headers=h)
    check("recent sessions endpoint works", r.status_code == 200 and len(r.json()) >= 1)


# =====================================================================================================================
@guarded
def check_trading_and_dividends() -> dict:
    section("Trading")
    ctx: dict = {}
    db = SessionLocal()
    try:
        book_registry.reset_book_cache()
        house = house_account.get_or_create_house_user(db)
        db.commit()  # SQLite allows one writer: never hold an open write transaction while calling the API

        def mk(email: str, name: str):
            r = register(email, name)
            return db.query(User).filter(User.email == email).one()

        alice, bob, carl = mk("t_alice@forecastcheck.dev", "t_alice"), mk("t_bob@forecastcheck.dev", "t_bob"), mk("t_carl@forecastcheck.dev", "t_carl")
        ctx.update(alice=alice.id, bob=bob.id, carl=carl.id)
        player = player_service.create_player(db, gamertag="CheckPro", total_shares_outstanding=1000, ipo_price=Decimal("10.0000"), power_rating=70)
        db.commit()
        ctx["player"] = player.id

        a0 = wallet_service.get_or_create_wallet(db, alice.id).cash_balance
        o = order_service.place_quick_order(db, alice.id, player.id, OrderSide.BUY, 10)
        db.commit()
        check("quick buy fills", o.status.value == "filled", o.status.value)
        pos = db.query(Position).filter(Position.user_id == alice.id, Position.player_id == player.id).one()
        check("buyer holds 10 shares", pos.quantity == 10)
        a1 = wallet_service.get_or_create_wallet(db, alice.id).cash_balance
        check("buyer's cash dropped (price + fee)", a1 < a0, f"{a0} -> {a1}")
        fees = db.query(LedgerEntry).join(Wallet, Wallet.id == LedgerEntry.wallet_id).filter(Wallet.user_id == alice.id, LedgerEntry.entry_type == LedgerEntryType.FEE).count()
        check("a transaction fee was charged and logged", fees >= 1)

        total = db.query(Position).filter(Position.player_id == player.id).with_entities(Position.quantity).all()
        check("share conservation: positions sum to total shares outstanding", sum(q for (q,) in total) == 1000, str(sum(q for (q,) in total)))

        # ledger reconciliation for test users: running balance == sum of signed entries
        for label, uid in (("alice", alice.id), ("bob", bob.id)):
            wal = wallet_service.get_or_create_wallet(db, uid)
            s = sum((e.amount for e in db.query(LedgerEntry).filter(LedgerEntry.wallet_id == wal.id).all()), Decimal("0"))
            check(f"{label}: wallet cash == sum of ledger entries", s == wal.cash_balance, f"ledger={s} cash={wal.cash_balance}")
        ctx["alice_before_dividend"] = wallet_service.get_or_create_wallet(db, alice.id).cash_balance
    finally:
        db.close()

    section("Tournament -> dividends")
    db = SessionLocal()
    try:
        time.sleep(1.2)
        start = datetime.now(timezone.utc)  # RECORD DATE: Alice already holds 10; Bob does not yet.
        time.sleep(1.2)
        order_service.place_quick_order(db, ctx["bob"], ctx["player"], OrderSide.BUY, 5)  # Bob buys AFTER the start
        db.commit()
        t = tournament_service.create_tournament(db, name="System Check Cash Cup", tournament_type=TournamentType.CASH_CUP, prize_pool=Decimal("10000.00"), start_time=start)
        db.commit()
        tournament_service.upsert_placement_result(db, t.id, ctx["player"], placement=1, prize_won=Decimal("1000.00"))
        db.commit()
        payouts = tournament_service.finalize_tournament(db, t.id)
        db.commit()
        check("finalize created one payout", len(payouts) == 1)
        db.expire_all()
        p = db.query(DividendPayout).filter(DividendPayout.tournament_id == t.id).one()
        check("payout reached COMPLETED automatically (no worker/Redis needed)", p.status == DividendPayoutStatus.COMPLETED, p.status.value)
        trn = db.get(Tournament, t.id)
        check("tournament moved to FINALIZED", trn.status == TournamentStatus.FINALIZED, trn.status.value)

        items = db.query(DividendLineItem).filter(DividendLineItem.payout_id == p.id).all()
        by_user = {i.user_id: i for i in items}
        per_share = (p.total_pool_amount - p.platform_fee_amount) / Decimal(p.shares_outstanding_snapshot)
        a = by_user.get(ctx["alice"])
        check("holder at record date (Alice, 10 shares) was paid exactly 10 x per-share", a is not None and a.amount_paid == (per_share * 10).quantize(Decimal("0.01")), f"{a.amount_paid if a else None} vs {(per_share*10)}")
        check("buyer AFTER the start (Bob) earned nothing from this tournament", ctx["bob"] not in by_user)
        check("conservation: line items + platform fee == pool", sum((i.amount_paid for i in items), Decimal("0")) + p.platform_fee_amount == p.total_pool_amount, f"{sum(i.amount_paid for i in items)} + {p.platform_fee_amount} vs {p.total_pool_amount}")
        check("every payout line has a wallet ledger entry", all(i.ledger_entry_id is not None for i in items))
        after = wallet_service.get_or_create_wallet(db, ctx["alice"]).cash_balance
        check("Alice's wallet increased by exactly her dividend", after - ctx["alice_before_dividend"] == a.amount_paid, f"{after - ctx['alice_before_dividend']} vs {a.amount_paid}")

        before = wallet_service.get_or_create_wallet(db, ctx["alice"]).cash_balance
        from app.services import dividend_service
        dividend_service.process_payout(db, p.id)
        db.commit()
        check("re-processing a COMPLETED payout pays nobody twice", wallet_service.get_or_create_wallet(db, ctx["alice"]).cash_balance == before)

        # Stuck-payout sweeper (simulates REDIS enabled + no worker, or a crash)
        t2 = tournament_service.create_tournament(db, name="System Check Cash Cup 2", tournament_type=TournamentType.CASH_CUP, prize_pool=Decimal("5000.00"), start_time=datetime.now(timezone.utc) - timedelta(days=1))
        db.commit()
        pl2 = player_service.create_player(db, gamertag="CheckPro2", total_shares_outstanding=500, ipo_price=Decimal("8.0000"))
        db.commit()
        pr2 = DividendPayout(id=uuid.uuid4(), tournament_id=t2.id, player_id=pl2.id, total_pool_amount=Decimal("500.00"), shares_outstanding_snapshot=500, status=DividendPayoutStatus.PENDING)
        db.add(pr2)
        db.commit()
        n = maintenance_service.sweep_pending_payouts(db)
        db.expire_all()
        check("maintenance sweeper pays a payout stuck in PENDING", n >= 1 and db.get(DividendPayout, pr2.id).status == DividendPayoutStatus.COMPLETED)
        check("...and finalizes its tournament", db.get(Tournament, t2.id).status == TournamentStatus.FINALIZED)
    finally:
        db.close()
    return ctx


@guarded
def check_treasury() -> None:
    section("Treasury")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == "t_carl@forecastcheck.dev").one()
        h = treasury_service.purchase(db, u.id, Decimal("1000.00"))
        db.commit()
        nw = portfolio_service.compute_net_worths(db, [u.id])[u.id]
        check("net worth counts treasury holdings", nw["treasury"] >= Decimal("1000.00"), str(nw))
        h = db.get(TreasuryHolding, h.id)
        h.last_accrued_at = datetime.now(timezone.utc) - timedelta(days=3, hours=1)
        db.commit()
        n = treasury_service.accrue_due_holdings(db)
        db.commit()
        h = db.get(TreasuryHolding, h.id)
        check("catch-up accrual credited ~3 days of interest without any cron", n >= 1 and h.accrued_interest > 0, f"accrued={h.accrued_interest}")
        n2 = treasury_service.accrue_due_holdings(db)
        db.commit()
        check("running it again immediately accrues nothing more (idempotent)", n2 == 0, str(n2))
    finally:
        db.close()


@guarded
def check_seasons_stats(ctx: dict) -> None:
    section("Seasons / leaderboards")
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        s = season_service.create_season(db, "Check Season", now - timedelta(days=1), now + timedelta(days=30), activate=True)
        db.commit()
        check("season activated with entries for everyone", db.query(SeasonEntry).filter(SeasonEntry.season_id == s.id).count() >= 3)
        rows = season_service.season_standings(db, s)
        check("everyone starts the season at 0 SP, Bronze I", all(r["season_points"] == 0 and r["rank_tier"] == "Bronze I" for r in rows if abs(r["return_pct"]) < 1e-9) and len(rows) >= 3)

        # give Carl a gain: admin-style deposit raises net worth => positive return
        wallet_service.deposit(db, ctx["carl"], Decimal("15000.00"), memo="check: gain")
        db.commit()
        portfolio_service.clear_cache()
        rows = {r["user_id"]: r for r in season_service.season_standings(db, s)}
        db.commit()
        c = rows[ctx["carl"]]
        check("a gain earns Seasonal Points", c["season_points"] > 0 and c["return_pct"] > 0, str(c))
        wallet_service.withdraw(db, ctx["carl"], Decimal("30000.00"), memo="check: loss")
        db.commit()
        portfolio_service.clear_cache()
        rows = {r["user_id"]: r for r in season_service.season_standings(db, s)}
        check("losing money drops SP back to 0 (never negative)", rows[ctx["carl"]]["season_points"] == 0 and rows[ctx["carl"]]["return_pct"] < 0)

        db.commit()
        r = client.get("/api/v1/leaderboard/seasonal")
        check("GET /leaderboard/seasonal works", r.status_code == 200 and r.json()["season"]["name"] == "Check Season" and len(r.json()["entries"]) >= 3, r.text[:200])
        r = client.get("/api/v1/leaderboard")
        check("GET /leaderboard (all-time) works", r.status_code == 200 and len(r.json()) >= 3)
        board = leaderboard_service.compute_leaderboard(db, 50)
        check("all-time board sorted by net worth", all(board[i]["portfolio_value"] >= board[i + 1]["portfolio_value"] for i in range(len(board) - 1)))
        check("House account is excluded from leaderboards", all(b["display_name"] != "House Liquidity Account" for b in board))

        n = stats_service.snapshot_all(db)
        stats_service.snapshot_all(db)
        db.commit()
        check("daily snapshots are one row per user per day (upsert)", db.query(PortfolioSnapshot).count() == n, f"rows={db.query(PortfolioSnapshot).count()} users={n}")

        # fabricate yesterday for Carl to exercise best/worst day
        yday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        snap = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == ctx["carl"]).one()
        db.add(PortfolioSnapshot(id=uuid.uuid4(), user_id=ctx["carl"], day=yday, net_worth=snap.net_worth + Decimal("5000"), cash=snap.cash, holdings_value=snap.holdings_value))
        db.commit()

        section("Lifetime stats")
        carl = db.get(User, ctx["carl"])
        st = stats_service.user_stats(db, carl)
        check("stats: total change = net worth - contributed capital", abs(st["total_change"] - (st["net_worth"] - st["contributed_capital"])) < 0.01)
        check("stats: trading earnings identity (change - dividends - interest + fees)", abs(st["trading_earnings"] - (st["total_change"] - st["dividend_earnings"] - st["interest_earnings"] + st["fees_paid"])) < 0.01)
        check("stats: worst day detected from snapshots", st["worst_day"] is not None and st["worst_day"]["change"] < 0, str(st["worst_day"]))
        alice = db.get(User, ctx["alice"])
        sa = stats_service.user_stats(db, alice)
        check("stats: Alice shows 1 buy trade, a biggest trade, and a dividend", sa["total_trades"] >= 1 and sa["biggest_trade"] is not None and sa["dividend_earnings"] > 0, f"trades={sa['total_trades']} div={sa['dividend_earnings']}")
        check("stats: fees paid recorded", sa["fees_paid"] > 0)
        db.commit()
        r = client.post("/api/v1/auth/login", json={"email": "t_alice@forecastcheck.dev", "password": PW})
        r = client.get("/api/v1/stats/me", headers=auth(r.json()["access_token"]))
        check("GET /stats/me works", r.status_code == 200 and "net_worth" in r.json(), r.text[:200])

        # Account activity feed (Portfolio page "Activity")
        hdr = auth(client.post("/api/v1/auth/login", json={"email": "t_alice@forecastcheck.dev", "password": PW}).json()["access_token"])
        r = client.get("/api/v1/wallet/activity?limit=100", headers=hdr)
        feed = r.json() if r.status_code == 200 else {"items": []}
        types = [i["type"] for i in feed["items"]]
        check("activity feed loads", r.status_code == 200 and feed.get("total", 0) >= 3, r.text[:200])
        check("activity feed has the starting deposit, a buy, a fee and the dividend", all(t in types for t in ("deposit", "buy", "fee", "dividend")), str(types))
        buy = next((i for i in feed["items"] if i["type"] == "buy"), None)
        check("buy row names the player with quantity and price", buy is not None and buy["gamertag"] and buy["quantity"] == 10 and buy["price"] is not None, str(buy))
        div = next((i for i in feed["items"] if i["type"] == "dividend"), None)
        check("dividend row names the player and tournament", div is not None and div["gamertag"] and "System Check" in div["detail"], str(div))
        check("hold/release bookkeeping rows are hidden", not any(t in ("order_hold", "order_release") for t in types))
        ats = [i["at"] for i in feed["items"]]
        check("activity is newest first", ats == sorted(ats, reverse=True))
        r2 = client.get("/api/v1/wallet/activity?kind=dividends", headers=hdr).json()
        check("filter: dividends only", r2["items"] and all(i["type"] == "dividend" for i in r2["items"]))
        r3 = client.get("/api/v1/wallet/activity?limit=2&offset=0", headers=hdr).json()
        check("pagination: next_offset set when more rows exist", len(r3["items"]) == 2 and r3["next_offset"] == 2)

        section("Season rollover")
        n_final = season_service.finalize_season(db, s)
        db.commit()
        check("finalize stores final points/rank/position", n_final >= 3 and db.query(SeasonEntry).filter(SeasonEntry.season_id == s.id, SeasonEntry.final_rank.isnot(None)).count() == n_final)
        check("season is closed after finalize", season_service.get_active_season(db) is None)
        hist = season_service.user_season_history(db, ctx["alice"])
        check("history shows the finished season", len(hist) == 1 and hist[0]["name"] == "Check Season")
        actions = None
        s2 = season_service.create_season(db, "Next Season", now - timedelta(hours=1), now + timedelta(days=60))
        db.commit()
        actions = season_service.run_rollover(db)
        db.commit()
        check("rollover auto-activates the scheduled season whose window has begun", any("activated" in a for a in actions) and season_service.get_active_season(db).name == "Next Season", str(actions))
        db.query(SeasonEntry).count()
        nrows = season_service.season_standings(db, season_service.get_active_season(db))
        check("new season: everyone back to 0 SP", all(r["season_points"] == 0 for r in nrows if abs(r["return_pct"]) < 1e-6))
    finally:
        db.close()


@guarded
def check_analytics_and_delete() -> None:
    section("Analytics report")
    db = SessionLocal()
    try:
        rows = analytics_service.user_table(db)
        check("user table lists real users only (no House, no bots)", len(rows) >= 4 and all("system.forecast" not in r["email"] for r in rows), str(len(rows)))
        k = analytics_service.kpis(db, rows)
        check("KPIs computed", k["total_users"] == len(rows) and "active_24h" in k and k["signups_24h"] >= 1, str({x: k[x] for x in ('total_users', 'signups_24h', 'active_24h')}))
        check("trade counts reach the report", any(r["trades"] > 0 for r in rows))
        db.rollback()
    finally:
        db.close()

    section("Account deletion")
    db = SessionLocal()
    try:
        r = register("del@forecastcheck.dev", "delete_me")
        tok = r.json()["access_token"]
        r = client.post("/api/v1/account/delete", json={"password": PW, "confirm": "nope"}, headers=auth(tok))
        check("delete needs the DELETE confirmation", r.status_code == 400)
        r = client.post("/api/v1/account/delete", json={"password": "wrong-pass1", "confirm": "DELETE"}, headers=auth(tok))
        check("delete needs the right password", r.status_code == 400)
        r = client.post("/api/v1/account/delete", json={"password": PW, "confirm": "DELETE"}, headers=auth(tok))
        check("account deleted", r.status_code == 200, r.text)
        check("deleted account can't log in", client.post("/api/v1/auth/login", json={"email": "del@forecastcheck.dev", "password": PW}).status_code in (401, 403))
        check("deleted token rejected", client.get("/api/v1/auth/me", headers=auth(tok)).status_code == 401)
        check("username freed for reuse? (deleted names are anonymised)", register("del2@forecastcheck.dev", "delete_me").status_code == 201)
    finally:
        db.close()


@guarded
def check_bots() -> None:
    section("Bots")
    import random
    db = SessionLocal()
    try:
        economic_params_service.set_param(db, "bots.population_size", Decimal("12"))
        db.commit()
        res = bot_trading_service.run_bot_tick(db, random.Random(7))
        db.commit()
        from app.models.bot import BotProfile
        n = db.query(BotProfile).count()
        check("bot tick ran and created the bot population", n >= 12, f"bots={n} result={res}")
        names = [u.display_name for u in db.query(User).filter(User.id.in_(db.query(BotProfile.user_id))).all()]
        check("bot usernames look human (no 'Bot #' names, all unique)", not any("Bot #" in x for x in names) and len(set(n.lower() for n in names)) == len(names), str(names[:6]))
        valid = all(account_service.NAME_RE.match(x) for x in names)
        check("bot usernames satisfy the site's username rules", valid, str([x for x in names if not account_service.NAME_RE.match(x)][:5]))
        from app.services import portfolio_service
        portfolio_service.clear_cache()  # net worths are memoised for a few seconds; earlier checks filled the cache
        board = leaderboard_service.compute_leaderboard(db, 100)
        check("leaderboard includes bots", len(board) > 12)
    finally:
        db.close()


def main() -> int:
    print(f"System check using throwaway database: {_DB_FILE}")
    Base.metadata.create_all(bind=engine)
    check_pure_logic()
    check_auth_flows()
    check_profile_and_sessions()
    ctx = check_trading_and_dividends() or {}
    check_treasury()
    if ctx:
        check_seasons_stats(ctx)
    check_analytics_and_delete()
    check_bots()

    failed = [(l, d) for l, ok, d in RESULTS if not ok]
    print("\n" + "=" * 70)
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    for label, detail in failed:
        print(f"  FAILED: {label}" + (f"  ({detail})" if detail else ""))
    if not ARGS.keep:
        engine.dispose()
        try:
            os.remove(_DB_FILE)
            os.rmdir(_TMP)
        except OSError:
            pass
    else:
        print(f"Database kept at {_DB_FILE}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
