"""
Wallet operations. Every function here mutates a Wallet + appends exactly
one LedgerEntry in the same call, and calls `db.flush()` (not `commit()`)
-- committing is the caller's job, so that (for example) a trade fill can
debit the buyer, credit the seller, and update both positions in one
single atomic transaction. If any part of that raises, the whole thing
rolls back and no partial money movement is left behind.

Convention used everywhere in this file: `amount` parameters are always
positive Decimals; the sign of the ledger entry is decided internally by
`entry_type`, never by the caller passing a negative number. This avoids
an entire class of sign-flip bugs.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.wallet import LedgerEntry, LedgerEntryType, Wallet
from app.services.exceptions import InsufficientFundsError


def get_or_create_wallet(db: Session, user_id: uuid.UUID) -> Wallet:
    wallet = db.query(Wallet).filter(Wallet.user_id == user_id).with_for_update().one_or_none()
    if wallet is None:
        wallet = Wallet(user_id=user_id, cash_balance=Decimal("0"), held_balance=Decimal("0"))
        db.add(wallet)
        db.flush()
    return wallet


def _write_ledger_entry(
    db: Session,
    wallet: Wallet,
    entry_type: LedgerEntryType,
    signed_amount: Decimal,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    memo: str | None = None,
) -> LedgerEntry:
    entry = LedgerEntry(
        wallet_id=wallet.id,
        entry_type=entry_type,
        amount=signed_amount,
        balance_after=wallet.cash_balance,
        reference_type=reference_type,
        reference_id=reference_id,
        memo=memo,
    )
    db.add(entry)
    db.flush()
    return entry


def deposit(db: Session, user_id: uuid.UUID, amount: Decimal, memo: str | None = None) -> Wallet:
    if amount <= 0:
        raise ValueError("deposit amount must be positive")
    wallet = get_or_create_wallet(db, user_id)
    wallet.cash_balance += amount
    db.flush()
    _write_ledger_entry(db, wallet, LedgerEntryType.DEPOSIT, amount, memo=memo)
    return wallet


def withdraw(db: Session, user_id: uuid.UUID, amount: Decimal, memo: str | None = None) -> Wallet:
    if amount <= 0:
        raise ValueError("withdrawal amount must be positive")
    wallet = get_or_create_wallet(db, user_id)
    if wallet.available_balance < amount:
        raise InsufficientFundsError(
            f"available balance {wallet.available_balance} is less than requested withdrawal {amount}"
        )
    wallet.cash_balance -= amount
    db.flush()
    _write_ledger_entry(db, wallet, LedgerEntryType.WITHDRAWAL, -amount, memo=memo)
    return wallet


def hold_funds(db: Session, user_id: uuid.UUID, amount: Decimal, reference_type: str, reference_id: uuid.UUID) -> Wallet:
    """Reserve `amount` of the user's cash against a newly-placed limit buy
    order. Does NOT change cash_balance -- only held_balance -- so the
    ledger entry records a zero-sum-on-cash event (amount=0 signed change
    to spendable cash, but we still log it for the audit trail)."""
    if amount <= 0:
        raise ValueError("hold amount must be positive")
    wallet = get_or_create_wallet(db, user_id)
    if wallet.available_balance < amount:
        raise InsufficientFundsError(
            f"available balance {wallet.available_balance} is less than requested hold {amount}"
        )
    wallet.held_balance += amount
    db.flush()
    _write_ledger_entry(
        db, wallet, LedgerEntryType.ORDER_HOLD, Decimal("0"), reference_type=reference_type, reference_id=reference_id
    )
    return wallet


def release_hold(db: Session, user_id: uuid.UUID, amount: Decimal, reference_type: str, reference_id: uuid.UUID) -> Wallet:
    if amount <= 0:
        raise ValueError("release amount must be positive")
    wallet = get_or_create_wallet(db, user_id)
    # Defensive clamp: never let a rounding bug push held_balance negative.
    release_amount = min(amount, wallet.held_balance)
    wallet.held_balance -= release_amount
    db.flush()
    _write_ledger_entry(
        db, wallet, LedgerEntryType.ORDER_RELEASE, Decimal("0"), reference_type=reference_type, reference_id=reference_id
    )
    return wallet


def debit_for_trade(
    db: Session,
    user_id: uuid.UUID,
    amount: Decimal,
    trade_id: uuid.UUID,
    held_release_amount: Decimal | None = None,
) -> Wallet:
    """
    Buyer pays `amount` (= fill_price * fill_quantity) for a fill.

    `held_release_amount` is a SEPARATE number from `amount` and matters
    whenever the buyer is settling against a pre-existing hold placed at
    order-entry time (a LIMIT buy order holds `limit_price * quantity`,
    not the eventual fill price): pass `held_release_amount =
    order.limit_price * fill_quantity` so the *entire* worst-case
    reservation for these shares is released, not just the actual amount
    spent -- otherwise, any time a limit buy fills at a better price than
    its limit (price improvement), a sliver of cash would stay
    permanently and incorrectly stuck in `held_balance`.

    Pass `held_release_amount=None` (the default) for quick/market orders,
    which never place a hold in the first place -- only `cash_balance` is
    touched, `held_balance` is left alone.
    """
    if amount <= 0:
        raise ValueError("trade debit amount must be positive")
    wallet = get_or_create_wallet(db, user_id)
    wallet.cash_balance -= amount
    if held_release_amount is not None:
        wallet.held_balance = max(Decimal("0"), wallet.held_balance - held_release_amount)
    db.flush()
    _write_ledger_entry(
        db, wallet, LedgerEntryType.TRADE_DEBIT, -amount, reference_type="trade", reference_id=trade_id
    )
    return wallet


def credit_for_trade(db: Session, user_id: uuid.UUID, amount: Decimal, trade_id: uuid.UUID) -> Wallet:
    """Seller receives proceeds of a fill."""
    if amount <= 0:
        raise ValueError("trade credit amount must be positive")
    wallet = get_or_create_wallet(db, user_id)
    wallet.cash_balance += amount
    db.flush()
    _write_ledger_entry(
        db, wallet, LedgerEntryType.TRADE_CREDIT, amount, reference_type="trade", reference_id=trade_id
    )
    return wallet


def credit_dividend(db: Session, user_id: uuid.UUID, amount: Decimal, payout_id: uuid.UUID) -> LedgerEntry:
    if amount <= 0:
        raise ValueError("dividend amount must be positive")
    wallet = get_or_create_wallet(db, user_id)
    wallet.cash_balance += amount
    db.flush()
    return _write_ledger_entry(
        db, wallet, LedgerEntryType.DIVIDEND_CREDIT, amount, reference_type="dividend_payout", reference_id=payout_id
    )


def debit_for_treasury_purchase(db: Session, user_id: uuid.UUID, amount: Decimal, holding_id: uuid.UUID) -> Wallet:
    if amount <= 0:
        raise ValueError("treasury purchase amount must be positive")
    wallet = get_or_create_wallet(db, user_id)
    if wallet.available_balance < amount:
        raise InsufficientFundsError(
            f"available balance {wallet.available_balance} is less than requested treasury purchase {amount}"
        )
    wallet.cash_balance -= amount
    db.flush()
    _write_ledger_entry(
        db, wallet, LedgerEntryType.TREASURY_BUY, -amount, reference_type="treasury_holding", reference_id=holding_id
    )
    return wallet


def charge_fee(db: Session, user_id: uuid.UUID, amount: Decimal, reference_id: uuid.UUID, memo: str | None = None) -> Wallet:
    """Debit the taker's wallet for the transaction fee on a trade fill
    (see app/services/order_service.py). This is a SEPARATE debit from
    the trade notional itself (TRADE_DEBIT/TRADE_CREDIT) -- it's the
    platform's cut, not part of what the counterparty is owed. Paired
    with `receive_fee_revenue` on the House account so every dollar
    charged is accounted for somewhere (fees are a sink for real users,
    not money vanishing from the ledger).

    Also used for the auction entry fee (see app/services/auction_service.py)
    -- unlike the trade-fee call site (which always has fee-inclusive hold
    headroom already reserved, see order_service.py), that caller has no
    pre-existing hold, so the `available_balance` check here is what keeps
    a too-poor user from getting a raw DB constraint error instead of a
    clean InsufficientFundsError."""
    if amount <= 0:
        raise ValueError("fee amount must be positive")
    wallet = get_or_create_wallet(db, user_id)
    if wallet.available_balance < amount:
        raise InsufficientFundsError(
            f"available balance {wallet.available_balance} is less than fee {amount}"
        )
    wallet.cash_balance -= amount
    db.flush()
    _write_ledger_entry(
        db, wallet, LedgerEntryType.FEE, -amount, reference_type="trade_fee", reference_id=reference_id, memo=memo
    )
    return wallet


def receive_fee_revenue(db: Session, house_user_id: uuid.UUID, amount: Decimal, reference_id: uuid.UUID, memo: str | None = None) -> Wallet:
    """Credit the House account with fee revenue collected via `charge_fee`.
    Kept as its own function (rather than reusing `deposit`) so it shows
    up in the ledger tagged as FEE revenue, not an external deposit."""
    if amount <= 0:
        raise ValueError("fee amount must be positive")
    wallet = get_or_create_wallet(db, house_user_id)
    wallet.cash_balance += amount
    db.flush()
    _write_ledger_entry(
        db, wallet, LedgerEntryType.FEE, amount, reference_type="trade_fee", reference_id=reference_id, memo=memo
    )
    return wallet


def credit_for_treasury_redemption(db: Session, user_id: uuid.UUID, amount: Decimal, holding_id: uuid.UUID) -> Wallet:
    if amount <= 0:
        raise ValueError("treasury redemption amount must be positive")
    wallet = get_or_create_wallet(db, user_id)
    wallet.cash_balance += amount
    db.flush()
    _write_ledger_entry(
        db, wallet, LedgerEntryType.TREASURY_REDEEM, amount, reference_type="treasury_holding", reference_id=holding_id
    )
    return wallet
