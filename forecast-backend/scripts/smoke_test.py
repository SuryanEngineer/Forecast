#!/usr/bin/env python3
"""
End-to-end smoke test: exercises the whole system once through the
service layer (deposit -> IPO a player -> place orders that match ->
quick buy -> tournament results -> dividend payout -> treasury
purchase/accrual/redemption) against a REAL database, and asserts the
money and share math comes out exactly right at every step.

Run this after you've completed the setup in README_SETUP.md (dependencies
installed, DATABASE_URL pointing at a real reachable Postgres). It creates
its own tables via `Base.metadata.create_all` for convenience -- that's
fine for this throwaway smoke-test run, but real usage should go through
Alembic migrations (`alembic upgrade head`) instead, so schema changes are
tracked properly.

    cd forecast-backend
    python3 scripts/smoke_test.py

This talks to the database you configured, it is NOT a mock. Point it at
a scratch/dev database, not anything you care about -- it creates test
users and leaves its data behind.
"""
from __future__ import annotations

import sys
import uuid
from decimal import Decimal

sys.path.insert(0, ".")

from app.db.base import Base  # noqa: E402
from app.db.session import engine, SessionLocal  # noqa: E402
import app.models  # noqa: E402,F401  (populates Base.metadata)

from app.models.auction import AuctionBid  # noqa: E402
from app.models.order import OrderSide, Trade  # noqa: E402
from app.models.player import Position  # noqa: E402
from app.models.tournament import TournamentType  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.services import (  # noqa: E402
    auction_service,
    book_registry,
    dividend_service,
    economic_params_service,
    house_account,
    order_service,
    player_service,
    position_service,
    tournament_service,
    treasury_service,
    wallet_service,
)
from app.core.security import hash_password  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
_results: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    _results.append((label, condition, detail))
    print(f"[{PASS if condition else FAIL}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def make_user(db, email: str) -> User:
    user = User(id=uuid.uuid4(), email=email, password_hash=hash_password("password123"), display_name=email, role=UserRole.USER, is_active=True)
    db.add(user)
    db.flush()
    wallet_service.get_or_create_wallet(db, user.id)
    return user


def main() -> None:
    print("Creating tables (Base.metadata.create_all) ...")
    Base.metadata.create_all(bind=engine)
    book_registry.reset_book_cache()

    db = SessionLocal()
    try:
        run_id = uuid.uuid4().hex[:8]

        # --- Registration starting-balance flow ---
        # This block mirrors exactly what app/api/v1/auth.py:register() does
        # (this smoke test talks to the service layer directly, not HTTP,
        # so it can't exercise the route itself -- but the plumbing it
        # depends on, economic_params_service.get_param +
        # wallet_service.deposit, is proven here).
        starting_balance_user = make_user(db, f"newuser-{run_id}@test.local")
        db.commit()
        starting_balance = economic_params_service.get_param(db, "wallet.starting_balance")
        wallet_service.deposit(db, starting_balance_user.id, starting_balance, memo="Starting balance")
        db.commit()
        starting_balance_wallet = wallet_service.get_or_create_wallet(db, starting_balance_user.id)
        check(
            "New user starting balance defaults to $1,000,000 (matches the economy simulation's per-user starting capital)",
            starting_balance_wallet.cash_balance == Decimal("1000000.0000"),
            f"cash={starting_balance_wallet.cash_balance}",
        )

        alice = make_user(db, f"alice-{run_id}@test.local")
        bob = make_user(db, f"bob-{run_id}@test.local")
        db.commit()

        wallet_service.deposit(db, alice.id, Decimal("1000.00"), memo="smoke test seed")
        wallet_service.deposit(db, bob.id, Decimal("1000.00"), memo="smoke test seed")
        db.commit()

        alice_wallet = wallet_service.get_or_create_wallet(db, alice.id)
        check("Alice deposit reflected in cash balance", alice_wallet.cash_balance == Decimal("1000.0000"))

        player = player_service.create_player(db, gamertag=f"TestPro{run_id}", total_shares_outstanding=1000, ipo_price=Decimal("10.0000"))
        db.commit()
        check("Player created with correct share count", player.total_shares_outstanding == 1000)

        # Alice buys 10 shares via a limit order that crosses nothing yet (rests)
        alice_buy = order_service.place_limit_order(db, alice.id, player.id, OrderSide.BUY, Decimal("9.50"), 10)
        db.commit()
        check("Alice's resting buy order is OPEN", alice_buy.status.value == "open")

        alice_wallet = wallet_service.get_or_create_wallet(db, alice.id)
        # Hold includes fee headroom (price * qty * (1 + transaction_fee_pct))
        # since we don't yet know if Alice will end up taker or maker --
        # see app/services/order_service.py. Default fee is 0.25%, so
        # 9.50 * 10 * 1.0025 = 95.2375.
        check(
            "Alice's cash is held (not spent) for the resting order, including fee headroom",
            alice_wallet.held_balance == Decimal("95.2375") and alice_wallet.cash_balance == Decimal("1000.0000"),
            f"held={alice_wallet.held_balance} cash={alice_wallet.cash_balance}",
        )

        # Bob sells 10 shares at 9.50 -- but Bob has no shares yet! Give Bob
        # shares first via a quick buy from the house's seeded bot liquidity.
        bob_quick_buy = order_service.place_quick_order(db, bob.id, player.id, OrderSide.BUY, 10)
        db.commit()
        check("Bob's quick buy fully filled", bob_quick_buy.status.value == "filled", bob_quick_buy.status.value)

        # Snapshot the House's cash balance right before the trade that
        # actually owes a transaction fee, so the fee check below is a
        # clean before/after delta -- not an absolute value that would
        # also have to account for the House's role as synthetic
        # counterparty (and its own fee revenue) in Bob's quick buy above.
        house_user = house_account.get_or_create_house_user(db)
        house_cash_before_fee_trade = wallet_service.get_or_create_wallet(db, house_user.id).cash_balance

        # Now Bob sells 10 shares with a limit order at 9.50, which should cross Alice's resting bid.
        bob_sell = order_service.place_limit_order(db, bob.id, player.id, OrderSide.SELL, Decimal("9.50"), 10)
        db.commit()
        check("Bob's sell order matched Alice's resting bid and filled", bob_sell.status.value == "filled", bob_sell.status.value)

        alice_wallet = wallet_service.get_or_create_wallet(db, alice.id)
        check(
            "Alice's hold fully released after her buy order filled (no phantom held cash)",
            alice_wallet.held_balance == Decimal("0.0000"),
            f"held={alice_wallet.held_balance}",
        )
        check(
            "Alice paid exactly 10 * 9.50 = 95.00, not her worse-case hold "
            "(she was the maker in this fill, so she owes no transaction fee)",
            alice_wallet.cash_balance == Decimal("905.0000"),
            f"cash={alice_wallet.cash_balance}",
        )

        # --- Transaction fee flow ---
        # Bob's limit sell was the TAKER in that fill (it's the order that
        # arrived and crossed Alice's resting bid), so Bob -- not Alice --
        # owes the 0.25% transaction fee, credited to the House account.
        # fee = floor_to_cent(95.00 * 0.0025) = floor(0.2375) = 0.23
        house_wallet = wallet_service.get_or_create_wallet(db, house_user.id)
        check(
            "House account received exactly the 0.23 transaction fee from Bob's taker fill",
            house_wallet.cash_balance - house_cash_before_fee_trade == Decimal("0.23"),
            f"house cash before={house_cash_before_fee_trade} after={house_wallet.cash_balance}",
        )

        # --- Tournament + dividend flow ---
        tournament = tournament_service.create_tournament(
            db, name=f"Smoke Test Cash Cup {run_id}", tournament_type=TournamentType.CASH_CUP, prize_pool=Decimal("10000.00")
        )
        db.commit()
        tournament_service.upsert_placement_result(db, tournament.id, player.id, placement=1, prize_won=Decimal("1000.00"))
        db.commit()
        payouts = tournament_service.finalize_tournament(db, tournament.id)
        db.commit()
        check("Finalizing the tournament created exactly one dividend payout", len(payouts) == 1, str(len(payouts)))

        # Process the payout synchronously here (in real usage this runs in
        # the RQ background worker -- see README_SETUP.md).
        processed = dividend_service.process_payout(db, payouts[0].id)
        db.commit()
        check("Dividend payout completed", processed.status.value == "completed", processed.status.value)

        alice_wallet = wallet_service.get_or_create_wallet(db, alice.id)
        bob_wallet = wallet_service.get_or_create_wallet(db, bob.id)
        # Alice holds 10 shares (bought from Bob), Bob holds 0 (sold to Alice) + house holds the rest.
        # per_share = 1000.00 / 1000 shares = 1.00/share -> Alice should get 10 * 1.00 = 10.00
        check(
            "Alice received her dividend for the 10 shares she holds",
            alice_wallet.cash_balance == Decimal("915.0000"),
            f"cash={alice_wallet.cash_balance}",
        )

        # --- Fixed tournament dividend pool flow ---
        # Proves Cash Cup / FNCS / Global Championship tournaments pay out
        # of the FIXED synthetic pool (see economic_params_service.py)
        # instead of a real-world prize pool, when the admin hasn't
        # entered an exact prize_won for that placement. Default cash cup
        # pool is $300,000; placement 1 on the default curve is 20% -> $60,000.
        fixed_pool_player = player_service.create_player(
            db, gamertag=f"FixedPoolPro{run_id}", total_shares_outstanding=100, ipo_price=Decimal("5.0000")
        )
        db.commit()
        order_service.place_quick_order(db, alice.id, fixed_pool_player.id, OrderSide.BUY, 10)
        db.commit()
        fixed_pool_tournament = tournament_service.create_tournament(
            db, name=f"Fixed Pool Cash Cup {run_id}", tournament_type=TournamentType.CASH_CUP
        )
        db.commit()
        # No prize_won and no tournament prize_pool entered -- must fall
        # back to the fixed cash_cup_pool admin parameter, not $0.
        tournament_service.upsert_placement_result(db, fixed_pool_tournament.id, fixed_pool_player.id, placement=1)
        db.commit()
        fixed_pool_payouts = tournament_service.finalize_tournament(db, fixed_pool_tournament.id)
        db.commit()
        check(
            "Cash Cup with no admin-entered prize money still creates a payout "
            "against the fixed $300,000 pool (20% curve share = $60,000)",
            fixed_pool_payouts[0].total_pool_amount == Decimal("60000.00"),
            f"pool={fixed_pool_payouts[0].total_pool_amount}",
        )

        # --- Auction/IPO flow ---
        # Two fresh bidders on a fresh 100-share player, with bid amounts
        # chosen specifically so they do NOT divide evenly (this exercises
        # the largest-remainder rounding, not just the easy case) and so
        # one bidder (carol) ends up winning the remainder share and being
        # capped at her exact bid rather than her nominal proportional cost.
        #   total demand = 33333 + 16667 = 50000, shares = 100 -> clearing price = 500.0000
        #   carol: 33333/50000*100 = 66.666 shares -> floor 66, remainder 0.666 (wins the 1 leftover share -> 67)
        #   dave:  16667/50000*100 = 33.334 shares -> floor 33, remainder 0.334 (67 + 33 = 100, conserved exactly)
        #   carol's exact cost at 67 shares = 67*500 = 33500, which EXCEEDS her 33333 bid -> capped at 33333, released $0
        #   dave's exact cost at 33 shares = 33*500 = 16500, within his bid -> charged 16500, released 16667-16500=167
        carol = make_user(db, f"carol-{run_id}@test.local")
        dave = make_user(db, f"dave-{run_id}@test.local")
        db.commit()
        wallet_service.deposit(db, carol.id, Decimal("50000.00"), memo="smoke test seed")
        wallet_service.deposit(db, dave.id, Decimal("50000.00"), memo="smoke test seed")
        db.commit()

        auction_player = player_service.create_player(
            db, gamertag=f"AuctionPro{run_id}", total_shares_outstanding=100, ipo_price=Decimal("1.0000")
        )
        db.commit()

        house_cash_before_auction = wallet_service.get_or_create_wallet(db, house_account.get_or_create_house_user(db).id).cash_balance

        round_ = auction_service.open_round(db)
        db.commit()
        check("Auction round opens in OPEN status", round_.status.value == "open", round_.status.value)

        auction_service.join_round(db, round_.id, carol.id)
        auction_service.join_round(db, round_.id, dave.id)
        db.commit()
        carol_wallet = wallet_service.get_or_create_wallet(db, carol.id)
        check(
            "Carol's cash dropped by exactly the $10,000 auction entry fee after joining",
            carol_wallet.cash_balance == Decimal("40000.0000"),
            f"cash={carol_wallet.cash_balance}",
        )

        auction_service.place_bid(db, round_.id, carol.id, auction_player.id, Decimal("33333"))
        auction_service.place_bid(db, round_.id, dave.id, auction_player.id, Decimal("16667"))
        db.commit()
        carol_wallet = wallet_service.get_or_create_wallet(db, carol.id)
        check(
            "Carol's bid is held (not spent) after placing it",
            carol_wallet.held_balance == Decimal("33333.0000") and carol_wallet.cash_balance == Decimal("40000.0000"),
            f"held={carol_wallet.held_balance} cash={carol_wallet.cash_balance}",
        )

        finalized_round = auction_service.finalize_round(db, round_.id)
        db.commit()
        check("Auction round is FINALIZED after finalize_round", finalized_round.status.value == "finalized", finalized_round.status.value)

        carol_bid = (
            db.query(AuctionBid)
            .filter(AuctionBid.auction_round_id == round_.id, AuctionBid.user_id == carol.id)
            .one()
        )
        dave_bid = (
            db.query(AuctionBid)
            .filter(AuctionBid.auction_round_id == round_.id, AuctionBid.user_id == dave.id)
            .one()
        )
        check(
            "Shares allocated conserve exactly to the player's 100 total shares (67 + 33)",
            carol_bid.shares_won == 67 and dave_bid.shares_won == 33,
            f"carol={carol_bid.shares_won} dave={dave_bid.shares_won}",
        )
        check(
            "Carol (remainder-share winner) is capped at her exact bid, not her nominal 67*500=33500 cost",
            carol_bid.amount_charged == Decimal("33333.0000"),
            f"carol charged={carol_bid.amount_charged}",
        )
        check(
            "Dave is charged his exact proportional cost (33 shares * 500.00 clearing price)",
            dave_bid.amount_charged == Decimal("16500.0000"),
            f"dave charged={dave_bid.amount_charged}",
        )

        carol_wallet = wallet_service.get_or_create_wallet(db, carol.id)
        dave_wallet = wallet_service.get_or_create_wallet(db, dave.id)
        check(
            "Carol's final cash = 50000 deposit - 10000 entry fee - 33333 auction charge = 6667.00, hold fully cleared",
            carol_wallet.cash_balance == Decimal("6667.0000") and carol_wallet.held_balance == Decimal("0.0000"),
            f"cash={carol_wallet.cash_balance} held={carol_wallet.held_balance}",
        )
        check(
            "Dave's final cash = 50000 - 10000 entry fee - 16500 auction charge = 23500.00 (167 leftover hold released)",
            dave_wallet.cash_balance == Decimal("23500.0000") and dave_wallet.held_balance == Decimal("0.0000"),
            f"cash={dave_wallet.cash_balance} held={dave_wallet.held_balance}",
        )

        carol_position = (
            db.query(Position)
            .filter(Position.user_id == carol.id, Position.player_id == auction_player.id)
            .one()
        )
        house_position_after = position_service.get_or_create_position(db, house_account.get_or_create_house_user(db).id, auction_player.id)
        check(
            "Carol actually holds her 67 won shares, and the House's inventory for this player is fully depleted (0 left)",
            carol_position.quantity == 67 and house_position_after.quantity == 0,
            f"carol shares={carol_position.quantity} house shares={house_position_after.quantity}",
        )

        db.refresh(auction_player)
        check(
            "Player's reference price updated to the $500.00 auction clearing price",
            auction_player.ipo_price == Decimal("500.0000"),
            f"ipo_price={auction_player.ipo_price}",
        )

        house_wallet_after_auction = wallet_service.get_or_create_wallet(db, house_account.get_or_create_house_user(db).id)
        # House gained: 2 x $10,000 entry fees + $33,333 + $16,500 auction proceeds = $69,833
        check(
            "House account received exactly the entry fees plus auction proceeds",
            house_wallet_after_auction.cash_balance - house_cash_before_auction == Decimal("69833.0000"),
            f"delta={house_wallet_after_auction.cash_balance - house_cash_before_auction}",
        )

        raised_on_finalized_join = False
        try:
            auction_service.join_round(db, round_.id, alice.id)
        except Exception:
            raised_on_finalized_join = True
            db.rollback()
        check("Joining a finalized (no longer OPEN) auction round correctly raises an error", raised_on_finalized_join)

        # --- Economic parameter tuning flow ---
        # Proves the admin-tunable parameters in `platform_parameters`
        # (see economic_params_service.py) actually flow through to the
        # engine, not just the hardcoded module defaults.
        thin_player = player_service.create_player(
            db, gamertag=f"ThinLiquidityPro{run_id}", total_shares_outstanding=1000, ipo_price=Decimal("20.0000")
        )
        db.commit()
        # No bot quotes posted for this player -- its book is completely
        # empty, so a quick buy is 100% synthetic and isolates the
        # market-impact-coefficient parameter cleanly.

        order_service.place_quick_order(db, bob.id, thin_player.id, OrderSide.BUY, 10)
        db.commit()
        low_impact_price = (
            db.query(Trade).filter(Trade.player_id == thin_player.id).order_by(Trade.executed_at.desc()).first().price
        )
        check(
            "Synthetic quick-buy price is above the IPO reference price (buy pressure)",
            low_impact_price > Decimal("20.0000"),
            f"price={low_impact_price}",
        )

        economic_params_service.set_param(db, "quick_trade.market_impact_coefficient", Decimal("2.0"))
        db.commit()

        order_service.place_quick_order(db, bob.id, thin_player.id, OrderSide.BUY, 10)
        db.commit()
        high_impact_price = (
            db.query(Trade).filter(Trade.player_id == thin_player.id).order_by(Trade.executed_at.desc()).first().price
        )
        check(
            "Raising quick_trade.market_impact_coefficient via the admin-tunable "
            "parameter (not a code change) increases slippage on the very next order",
            high_impact_price > low_impact_price,
            f"low={low_impact_price} high={high_impact_price}",
        )

        # --- Treasury flow ---
        holding = treasury_service.purchase(db, bob.id, Decimal("100.00"))
        db.commit()
        accrued_count = treasury_service.accrue_all_active_holdings(db, days_elapsed=Decimal("365"))
        db.commit()
        check("Treasury accrual ran for at least one holding", accrued_count >= 1, str(accrued_count))

        redeemed = treasury_service.redeem(db, bob.id, holding.id)
        db.commit()
        check(
            "Redeeming after 365 days at the default 1% APY (matching the validated "
            "economy simulation's ~1%/year cash treasury yield) returns principal + 1%",
            Decimal("100.9") < (redeemed.principal_amount + redeemed.accrued_interest) < Decimal("101.1"),
            f"total={redeemed.principal_amount + redeemed.accrued_interest}",
        )

        print(f"\nAll {len(_results)} checks passed.")
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"\nSMOKE TEST FAILED: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"\nSMOKE TEST ERRORED (likely a setup problem -- is your DATABASE_URL reachable?): {exc}")
        raise
