"""
In-app notifications (see app/models/notification.py).

Producers call the small `*_` helpers here from the places the events actually happen (order settlement, order
cancellation, dividend payout, the tournament sync, the maintenance sweep). Everything is best-effort: a notification
must never be able to break a trade, a payout or a sync, so each insert runs in its own savepoint and any failure is
logged and swallowed.

Real users only: bots and the House never get notifications (their activity would be thousands of rows a day).

How "read" works (the app does the other half, see NotificationCenter.tsx):
  * a notification is created unread;
  * a user who is on the site gets a pop-up for it and the app marks it read right away (POST /notifications/read);
  * a user who is away leaves it unread -> red dot -> opening the panel reads everything at once.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.bot import BotProfile
from app.models.notification import Notification
from app.models.user import User
from app.services.house_account import HOUSE_ACCOUNT_EMAIL

logger = logging.getLogger("forecast.notifications")

# Tournament start / end notices older than this are never sent (so a fresh deploy does not announce last week's events).
EVENT_RECENCY = timedelta(hours=6)
RETENTION_DAYS = 45
MAX_PER_USER = 300


_TRAILING_DATE = re.compile(r"\s*[—–-]\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\s*$", re.IGNORECASE)


def _label(name: str | None) -> str:
    """A tournament's name for message text: without the trailing UTC date the tracker appends ("... — Nov 15, 2026"), which can
    read as a different day than the viewer's local date."""
    return _TRAILING_DATE.sub("", name or "").strip()


def _usd(amount) -> str:
    return f"${Decimal(str(amount)):,.2f}"


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def real_user_ids(db: Session, user_ids) -> set[uuid.UUID]:
    """The subset of `user_ids` that are real, active people (not bots, not the House)."""
    ids = {uuid.UUID(str(u)) for u in user_ids}
    if not ids:
        return set()
    bots = {r[0] for r in db.query(BotProfile.user_id).filter(BotProfile.user_id.in_(ids)).all()}
    house = {r[0] for r in db.query(User.id).filter(User.id.in_(ids), User.email == HOUSE_ACCOUNT_EMAIL).all()}
    active = {r[0] for r in db.query(User.id).filter(User.id.in_(ids), User.is_active.is_(True)).all()}
    return (ids - bots - house) & active


def notify(
    db: Session,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    body: str,
    data: dict | None = None,
    ref_key: str | None = None,
    read: bool = False,
    created_at: datetime | None = None,
) -> bool:
    """Adds one notification (caller must already know `user_id` is a real user). `read=True` creates it already read
    (used for things the user just did themselves). `created_at` back-dates it (a retroactive dividend shows as of the day
    it was earned). Returns False if it was a duplicate (`ref_key`) or failed."""
    try:
        with db.begin_nested():
            if ref_key is not None and (
                db.query(Notification.id).filter(Notification.user_id == user_id, Notification.ref_key == ref_key).first()
            ):
                return False
            extra = {"created_at": created_at} if created_at is not None else {}
            db.add(
                Notification(
                    id=uuid.uuid4(), user_id=user_id, kind=kind, title=title[:200], body=body, data=data,
                    ref_key=ref_key, read_at=datetime.now(timezone.utc) if read else None, **extra,
                )
            )
            db.flush()
        return True
    except IntegrityError:
        return False
    except Exception:  # noqa: BLE001 -- a notification must never break the thing that triggered it
        logger.exception("Could not create %s notification for %s", kind, user_id)
        return False


# ---------------------------------------------------------------- trades / orders


def trade_filled(db: Session, user_id: uuid.UUID, order_id: uuid.UUID, side: str, player: object, quantity: int, notional: Decimal) -> None:
    """One order's fills from one execution, summed: 'Bought 25 shares of X for $1,234.56'."""
    name = getattr(player, "gamertag", "a player")
    buy = side == "buy"
    avg = (notional / quantity) if quantity else Decimal("0")
    notify(
        db, user_id, "trade", "Buy" if buy else "Sell",
        f"{'Bought' if buy else 'Sold'} {_plural(quantity, 'share')} of {name} for {_usd(notional)}",
        data={"side": side, "player_id": str(player.id), "player_name": name, "quantity": quantity,
              "total": float(notional), "avg_price": float(avg)},
        ref_key=None,   # one order can fill in several executions: each one is its own notification
    )


def order_cancelled(db: Session, order: object, reason: str, by_user: bool) -> None:
    """A resting limit order came off the book. `by_user` cancellations are logged already read (no pop-up, no dot):
    the user just did it themselves."""
    try:
        from app.models.player import Player

        player = db.get(Player, order.player_id)
        name = player.gamertag if player is not None else "a player"
        left = max(0, order.quantity - order.filled_quantity)
        side = order.side.value if hasattr(order.side, "value") else str(order.side)
        price = _usd(order.limit_price) if order.limit_price is not None else "market"
        notify(
            db, order.user_id, "order_cancelled", "Order cancelled",
            f"Your {side} order for {_plural(left, 'share')} of {name} at {price} was cancelled: {reason}.",
            data={"side": side, "player_id": str(order.player_id), "player_name": name, "quantity": left,
                  "limit_price": float(order.limit_price) if order.limit_price is not None else None, "reason": reason},
            ref_key=f"cancel:{order.id}", read=by_user,
        )
    except Exception:  # noqa: BLE001
        logger.exception("order_cancelled notification failed")


# ---------------------------------------------------------------- dividends


def dividends_paid(db: Session, tournament_id: uuid.UUID) -> int:
    """After a tournament's last payout completes: one notification per user, summing what they were paid across every
    player they held ('+$1,234.00 in dividends from <tournament>')."""
    from app.models.dividend import DividendLineItem, DividendPayout
    from app.models.player import Player
    from app.models.tournament import Tournament

    tournament = db.get(Tournament, tournament_id)
    if tournament is None:
        return 0
    rows = (
        db.query(DividendLineItem.user_id, DividendLineItem.amount_paid, Player.gamertag)
        .join(DividendPayout, DividendPayout.id == DividendLineItem.payout_id)
        .join(Player, Player.id == DividendPayout.player_id)
        .filter(DividendPayout.tournament_id == tournament_id, DividendLineItem.amount_paid > 0)
        .all()
    )
    per_user: dict[uuid.UUID, dict] = {}
    for uid, amount, tag in rows:
        g = per_user.setdefault(uid, {"total": Decimal("0"), "players": []})
        g["total"] += Decimal(str(amount))
        if tag not in g["players"]:
            g["players"].append(tag)
    real = real_user_ids(db, per_user.keys())
    sent = 0
    # Dated to when the money was earned (the tournament's finish), not when the job ran: a retroactive payout for an
    # event a week ago appears a week ago. Only back-dated when clearly in the past and still inside the retention window
    # (anything older would be pruned at once, so it is stamped now instead).
    from app.services import dividend_service

    when = dividend_service.tournament_finished_at(db, tournament)
    age = datetime.now(timezone.utc) - when
    dated = when if timedelta(minutes=10) < age < timedelta(days=RETENTION_DAYS) else None
    for uid, g in per_user.items():
        if uid not in real:
            continue
        players = g["players"]
        who = ", ".join(players[:3]) + (f" +{len(players) - 3} more" if len(players) > 3 else "")
        if notify(
            db, uid, "dividend", f"Dividends paid: +{_usd(g['total'])}",
            f"{_label(tournament.name)} paid you {_usd(g['total'])} for {who}.",
            data={"tournament_id": str(tournament_id), "tournament_name": _label(tournament.name),
                  "amount": float(g["total"]), "players": players[:8]},
            ref_key=f"dividend:{tournament_id}", created_at=dated,
        ):
            sent += 1
    return sent


# ---------------------------------------------------------------- tournaments / game wins


def _holders_of(db: Session, player_ids) -> dict[uuid.UUID, set[uuid.UUID]]:
    """{real user_id: {player_ids they currently hold}} for the given players."""
    from app.models.player import Position

    pids = list(player_ids)
    if not pids:
        return {}
    held: dict[uuid.UUID, set[uuid.UUID]] = {}
    for uid, pid in db.query(Position.user_id, Position.player_id).filter(Position.player_id.in_(pids), Position.quantity > 0).all():
        held.setdefault(uid, set()).add(pid)
    real = real_user_ids(db, held.keys())
    return {u: p for u, p in held.items() if u in real}


def game_win(db: Session, tournament: object, player: object, wins: int, total_wins: int) -> int:
    """A player a user holds just won a game. Notifies every real holder (once per player per win count)."""
    holders = _holders_of(db, [player.id])
    sent = 0
    name = player.gamertag
    for uid in holders:
        if notify(
            db, uid, "game_win", f"{name} won a game",
            f"{name} just won a game in {_label(tournament.name)}" + (f" ({_plural(total_wins, 'win')} so far)." if total_wins > 1 else "."),
            data={"tournament_id": str(tournament.id), "tournament_name": _label(tournament.name), "player_id": str(player.id),
                  "player_name": name, "wins": total_wins},
            ref_key=f"win:{tournament.id}:{player.id}:{total_wins}",
        ):
            sent += 1
    return sent


def scan_tournament_events(db: Session) -> dict[str, int]:
    """Run every minute by the maintenance pass: tells users when a tournament featuring a player they hold has just
    started or ended. Only events from the last few hours are announced."""
    from app.models.player import Position
    from app.models.tournament import PlacementResult, Tournament, TournamentEntrant, TournamentStatus

    now = datetime.now(timezone.utc)
    since = now - EVENT_RECENCY

    def aware(dt):
        return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    started = ended = 0
    tournaments = (
        db.query(Tournament)
        .filter(Tournament.is_historical_archive.is_(False))
        .filter(
            ((Tournament.start_time <= now) & (Tournament.start_time >= since))
            | ((Tournament.end_time <= now) & (Tournament.end_time >= since))
            | ((Tournament.status == TournamentStatus.FINALIZED) & (Tournament.updated_at >= since))
        )
        .all()
    )
    for t in tournaments:
        start, end = aware(t.start_time), aware(t.end_time)
        is_start = start is not None and since <= start <= now
        # Over = its end time just passed (or, with no end time on file, it was just finalized). A cup finalized late
        # (e.g. a retroactive payout for an old event) is not announced as "just ended".
        is_end = (end is not None and since <= end <= now) or (
            end is None and t.status == TournamentStatus.FINALIZED and aware(t.updated_at) >= since
        )
        if not (is_start or is_end):
            continue
        pids = {r[0] for r in db.query(PlacementResult.player_id).filter(PlacementResult.tournament_id == t.id).all()}
        pids |= {r[0] for r in db.query(TournamentEntrant.player_id).filter(TournamentEntrant.tournament_id == t.id).all()}
        holders = _holders_of(db, pids)
        for uid, held in holders.items():
            names = _player_names(db, held)
            who = ", ".join(names[:3]) + (f" +{len(names) - 3} more" if len(names) > 3 else "")
            if is_start and notify(
                db, uid, "tournament_start", f"{_label(t.name)} has started",
                f"{_label(t.name)} is live now. You own shares of {who}.",
                data={"tournament_id": str(t.id), "tournament_name": _label(t.name), "players": names[:8]},
                ref_key=f"tstart:{t.id}",
            ):
                started += 1
            if is_end and notify(
                db, uid, "tournament_end", f"{_label(t.name)} has ended",
                f"{_label(t.name)} is over. You own shares of {who}; dividends are paid once results are final.",
                data={"tournament_id": str(t.id), "tournament_name": _label(t.name), "players": names[:8]},
                ref_key=f"tend:{t.id}",
            ):
                ended += 1
    return {"started": started, "ended": ended}


def _player_names(db: Session, player_ids) -> list[str]:
    from app.models.player import Player

    return sorted(r[0] for r in db.query(Player.gamertag).filter(Player.id.in_(list(player_ids))).all())


# ---------------------------------------------------------------- reading / housekeeping


def serialize(n: Notification) -> dict:
    return {
        "id": str(n.id), "kind": n.kind, "title": n.title, "body": n.body, "data": n.data or {},
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "read": n.read_at is not None,
    }


_LAST_PRUNE = 0.0


def prune(db: Session) -> int:
    """Drops notifications past retention and trims each user to their newest MAX_PER_USER (at most every 30 minutes)."""
    import time

    global _LAST_PRUNE
    if time.monotonic() - _LAST_PRUNE < 1800:
        return 0
    _LAST_PRUNE = time.monotonic()
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    n = db.query(Notification).filter(Notification.created_at < cutoff).delete(synchronize_session=False)
    heavy = [u for (u,) in db.query(Notification.user_id).group_by(Notification.user_id).having(func.count(Notification.id) > MAX_PER_USER + 50).all()]
    for uid in heavy:
        keep = [i for (i,) in db.query(Notification.id).filter(Notification.user_id == uid).order_by(Notification.created_at.desc()).limit(MAX_PER_USER).all()]
        n += db.query(Notification).filter(Notification.user_id == uid, Notification.id.notin_(keep)).delete(synchronize_session=False)
    return n
