"""
Import every model module here so that (a) `Base.metadata` knows about all
tables when Alembic autogenerates migrations, and (b) app code can do
`from app.models import User, Wallet, ...` from one place.
"""
from app.models.user import User, UserRole  # noqa: F401
from app.models.wallet import Wallet, LedgerEntry, LedgerEntryType  # noqa: F401
from app.models.player import Player, Position, PriceSnapshot  # noqa: F401
from app.models.order import Order, Trade, OrderSide, OrderKind, OrderStatus  # noqa: F401
from app.models.tournament import Tournament, PlacementResult, TournamentType, TournamentStatus, ResultSource, TournamentEntrant  # noqa: F401
from app.models.dividend import DividendPayout, DividendLineItem, DividendPayoutStatus  # noqa: F401
from app.models.treasury import TreasuryInstrument, TreasuryHolding, TreasuryAccrualLog, TreasuryHoldingStatus  # noqa: F401
from app.models.audit import AuditLog, ActorType  # noqa: F401
from app.models.economic_params import PlatformParameter, DividendPlacementCurveEntry  # noqa: F401
from app.models.auction import AuctionRound, AuctionParticipant, AuctionBid, AuctionRoundStatus  # noqa: F401
from app.models.bot import BotProfile  # noqa: F401
from app.models.password_reset import PasswordResetToken  # noqa: F401
from app.models.osirion import OsirionTournamentMapping, OsirionPlayerMapping  # noqa: F401
from app.models.tournament_classification import TournamentClassificationRule, RegionMultiplier  # noqa: F401
