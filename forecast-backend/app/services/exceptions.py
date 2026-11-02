from decimal import ROUND_HALF_UP, Decimal


def usd(amount) -> str:
    """Dollars for people to read: always rounded to the cent ('$1,234.57'), however many decimals the math carried."""
    return f"${Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,}"


class ServiceError(Exception):
    """Base class for errors the API layer should turn into 4xx responses."""


class InsufficientFundsError(ServiceError):
    pass


class InsufficientSharesError(ServiceError):
    pass


class OrderNotFoundError(ServiceError):
    pass


class OrderNotCancellableError(ServiceError):
    pass


class PlayerNotFoundError(ServiceError):
    pass


class PriceOutOfBandError(ServiceError):
    """A limit price outside the allowed band around the stock's fair (dividend-based) price."""


class SelfTradeError(ServiceError):
    """An order that would trade against the same user's own resting order."""


class NotPrimaryError(ServiceError):
    """This server instance is not the one allowed to match orders right now (see lease_service)."""


class NoLiquidityError(ServiceError):
    """Raised when a quick order can't be filled even synthetically (no
    resting book AND no fallback reference price exists yet -- i.e. the
    player has never traded and has no IPO price set)."""


class HouseCapacityError(NoLiquidityError):
    """The House cannot take the other side of a quick order right now (not enough House cash to buy that many shares,
    or not enough House shares left to sell that many)."""
