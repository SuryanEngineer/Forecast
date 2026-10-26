"""
Account/profile rules: display-name & tag validation, name-change cooldown, password policy, email change,
account deletion (anonymisation). Raises AccountError with a user-safe message for anything the user can fix.
"""
from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.account import EmailCode, UserSession
from app.models.order import Order, OrderStatus
from app.models.user import User

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{2,19}$")
TAG_RE = re.compile(r"^[A-Za-z0-9]{2,5}$")
NAME_CHANGE_COOLDOWN_DAYS = 7
TAG_COLORS = [
    "#00C8FF", "#9B6FFF", "#FF5C8A", "#FFB020", "#34D399", "#F97316",
    "#60A5FA", "#E879F9", "#FACC15", "#A3E635", "#F87171", "#FFFFFF",
]
RESERVED = {"admin", "administrator", "forecast", "support", "staff", "moderator", "mod", "system", "house", "official", "root", "null", "owner"}
# Deliberately compact moderation list (matched after de-leeting and stripping separators). Extend freely.
_BLOCKED = [  # matched as substrings of the de-leeted name
    "fuck", "shit", "bitch", "cunt", "pussy", "whore", "slut", "asshole", "nigg", "fagg", "retard", "rapist",
    "hitler", "pedo", "molest", "porn", "tranny", "wetback", "nazi",
]
_WEAK = {  # matched only as a whole word/token (avoids "grape", "peacock", "analyst", "raccoon"...)
    "dick", "cock", "cum", "anal", "rape", "kkk", "isis", "coon", "kike", "spic", "chink", "penis", "vagina",
    "bastard", "terrorist", "suicide",
}
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "@": "a", "$": "s", "!": "i"})


class AccountError(ValueError):
    pass


def _normalize_for_filter(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower().translate(_LEET))


def is_inappropriate(text: str) -> bool:
    norm = _normalize_for_filter(text)
    collapsed = re.sub(r"(.)\1+", r"\1", norm)
    for bad in _BLOCKED:
        if bad in norm or re.sub(r"(.)\1+", r"\1", bad) in collapsed:
            return True
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)  # camelCase -> words
    tokens = [t for t in re.split(r"[^a-z]+", spaced.lower().translate(_LEET)) if t]
    return any(t in _WEAK for t in tokens)


def validate_display_name(db: Session, name: str, exclude_user_id: uuid.UUID | None = None) -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise AccountError("Usernames are 3-20 characters: letters, numbers, underscores, dots or hyphens, starting with a letter or number.")
    if name.lower() in RESERVED or is_inappropriate(name):
        raise AccountError("That username isn't allowed. Inappropriate names result in account deletion.")
    q = db.query(User.id).filter(func.lower(User.display_name) == name.lower())
    if exclude_user_id is not None:
        q = q.filter(User.id != exclude_user_id)
    if q.first() is not None:
        raise AccountError("That username is already taken.")
    return name


def validate_tag(tag: str | None, color: str | None) -> tuple[str | None, str | None]:
    if not tag:
        return None, None
    tag = tag.strip()
    if not TAG_RE.match(tag):
        raise AccountError("Tags are 2-5 letters or numbers.")
    if tag.lower() in RESERVED or is_inappropriate(tag):
        raise AccountError("That tag isn't allowed.")
    color = (color or TAG_COLORS[0]).upper()
    if color not in TAG_COLORS:
        raise AccountError("Pick one of the available tag colors.")
    return tag.upper(), color


def validate_password(password: str, email: str | None = None) -> None:
    if len(password) < 8:
        raise AccountError("Password must be at least 8 characters.")
    if len(password) > 128:
        raise AccountError("Password is too long (max 128 characters).")
    if not (re.search(r"[A-Za-z]", password) and re.search(r"[0-9]", password)):
        raise AccountError("Password must contain at least one letter and one number.")
    if email and password.lower() == email.lower():
        raise AccountError("Password can't be the same as your email.")
    if password.lower() in {"password1", "password123", "12345678a", "qwerty123", "iloveyou1"}:
        raise AccountError("That password is too common.")


def name_change_available_at(user: User) -> datetime | None:
    if user.display_name_changed_at is None:
        return None
    changed = user.display_name_changed_at
    if changed.tzinfo is None:
        changed = changed.replace(tzinfo=timezone.utc)
    nxt = changed + timedelta(days=NAME_CHANGE_COOLDOWN_DAYS)
    return nxt if nxt > datetime.now(timezone.utc) else None


def change_display_name(db: Session, user: User, new_name: str) -> None:
    new_name = validate_display_name(db, new_name, exclude_user_id=user.id)
    if new_name == user.display_name:
        raise AccountError("That's already your username.")
    wait = name_change_available_at(user)
    if wait is not None:
        raise AccountError(f"You can change your username again on {wait.strftime('%b %d, %Y')}.")
    user.display_name = new_name
    user.display_name_changed_at = datetime.now(timezone.utc)
    db.flush()


def set_tag(db: Session, user: User, tag: str | None, color: str | None) -> None:
    user.tag, user.tag_color = validate_tag(tag, color)
    db.flush()


def email_in_use(db: Session, email: str, exclude_user_id: uuid.UUID | None = None) -> bool:
    q = db.query(User.id).filter(func.lower(User.email) == email.lower())
    if exclude_user_id is not None:
        q = q.filter(User.id != exclude_user_id)
    return q.first() is not None


def delete_account(db: Session, user: User) -> None:
    """Anonymise + deactivate. Open orders are cancelled (funds/shares released). Held shares and trade history stay
    (market integrity / dividend ledger), but the account can't log in, vanishes from leaderboards, and its personal
    data is scrubbed."""
    from app.services import order_service  # local import: avoid import cycle

    for order in db.query(Order).filter(Order.user_id == user.id, Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED])).all():
        try:
            order_service.cancel_order(db, user.id, order.id)
        except Exception:
            pass
    suffix = secrets.token_hex(4)
    user.is_active = False
    user.email = f"deleted-{user.id.hex[:12]}@deleted.invalid"
    user.display_name = f"Deleted-{suffix}"
    user.password_hash = hash_password(secrets.token_urlsafe(24))
    user.tag = None
    user.tag_color = None
    db.query(EmailCode).filter(EmailCode.user_id == user.id).delete()
    db.query(UserSession).filter(UserSession.user_id == user.id).update({"ip_address": None, "user_agent": None})
    db.flush()
