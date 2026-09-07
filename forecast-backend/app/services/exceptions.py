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


class NoLiquidityError(ServiceError):
    """Raised when a quick order can't be filled even synthetically (no
    resting book AND no fallback reference price exists yet -- i.e. the
    player has never traded and has no IPO price set)."""
