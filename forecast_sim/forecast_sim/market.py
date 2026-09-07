"""
Order book, Bank, and the matching engine.

Design notes / assumptions (the spec leaves some mechanics underspecified,
these are the choices made to keep the simulator well-defined):

- Limit orders escrow immediately on placement (cash for buys, shares for
  sells) so a user can never spend/sell more than they have. Any unused
  escrow (e.g. a buy fills at a better price than the limit) is refunded.
- Placing a limit order attempts to cross the book immediately
  (standard continuous double auction / price-time priority) before
  resting the remainder.
- Quick Buy / Quick Sell match against the *opposite* resting book first
  (as specified), then fall back to the Bank for any remaining quantity.
- Bank Quick-Buy price = highest active buy order * (1 + spread). If there
  is no active buy order, we fall back to the last trade price, and if
  there has never been a trade, the player's baseline price.
- Bank Quick-Sell price (Bank buying from the user) = lowest active sell
  order * (1 - spread), with the same fallback chain. This keeps the
  Bank's buy/sell prices symmetric around the market rather than only
  being defined for one side, since the spec says Bank pricing should
  "use the current market liquidity rules" for Quick Sell without fully
  specifying it.
- The Bank can always buy shares from a user (infinite cash sink), but can
  only sell shares it actually holds in inventory (Quick Buy fails for any
  quantity beyond Bank inventory).
"""

import heapq
from .models import Order, Trade


class OrderBook:
    """One order book (buy side + sell side) for a single player."""

    def __init__(self, player_id):
        self.player_id = player_id
        # max-heap for buys: store (-price, timestamp, order)
        self._buy_heap = []
        # min-heap for sells: store (price, timestamp, order)
        self._sell_heap = []

    def add_buy(self, order: Order):
        heapq.heappush(self._buy_heap, (-order.price, order.timestamp, order.order_id, order))

    def add_sell(self, order: Order):
        heapq.heappush(self._sell_heap, (order.price, order.timestamp, order.order_id, order))

    def _clean_buy(self):
        while self._buy_heap and self._buy_heap[0][3].quantity <= 0:
            heapq.heappop(self._buy_heap)

    def _clean_sell(self):
        while self._sell_heap and self._sell_heap[0][3].quantity <= 0:
            heapq.heappop(self._sell_heap)

    def best_buy(self) -> Order | None:
        self._clean_buy()
        return self._buy_heap[0][3] if self._buy_heap else None

    def best_sell(self) -> Order | None:
        self._clean_sell()
        return self._sell_heap[0][3] if self._sell_heap else None

    def active_buy_orders(self):
        self._clean_buy()
        return [o for _, _, _, o in self._buy_heap if o.quantity > 0]

    def active_sell_orders(self):
        self._clean_sell()
        return [o for _, _, _, o in self._sell_heap if o.quantity > 0]

    def depth(self):
        return len(self.active_buy_orders()), len(self.active_sell_orders())


class Bank:
    """Infinite-cash liquidity provider. Tracks share inventory per player."""

    def __init__(self, spread: float):
        self.spread = spread
        self.inventory = {}   # player_id -> shares held by the Bank
        # Money paid to the Bank leaves the economy; money paid out enters it.
        # We track these purely as *metrics*, not as a constraint (Bank cash
        # itself is explicitly not tracked / infinite per the spec).
        self.cash_absorbed = 0.0
        self.cash_injected = 0.0

    def set_initial_inventory(self, player_id, shares):
        self.inventory[player_id] = self.inventory.get(player_id, 0) + shares

    def quick_buy_price(self, book: OrderBook, fallback_price: float) -> float:
        best_buy = book.best_buy()
        base = best_buy.price if best_buy is not None else fallback_price
        return base * (1 + self.spread)

    def quick_sell_price(self, book: OrderBook, fallback_price: float) -> float:
        best_sell = book.best_sell()
        base = best_sell.price if best_sell is not None else fallback_price
        return base * (1 - self.spread)


class Market:
    """Owns all order books + the Bank, and executes trades."""

    def __init__(self, players, bank_spread: float, baseline_price: float,
                 transaction_fee_rate: float = 0.0):
        self.books = {p.player_id: OrderBook(p.player_id) for p in players}
        self.players_by_id = {p.player_id: p for p in players}
        self.bank = Bank(bank_spread)
        self.baseline_price = baseline_price
        self.trade_log = []
        self._clock = 0
        self.current_round = 0
        # ----- Money sinks (spec: "Transaction Fee ... control inflation") -----
        # Charged to the TAKER (the side whose order is executing
        # immediately -- Quick Buy/Sell, or the crossing portion of a new
        # limit order) on every fill; the resting/maker side is completely
        # unaffected. Removed permanently from the economy, tracked here
        # for reconciliation. `auction_fees_removed` is populated by
        # auction.py (a separate, one-time sink at t=0).
        self.transaction_fee_rate = transaction_fee_rate
        self.transaction_fees_removed = 0.0
        self.auction_fees_removed = 0.0

    @property
    def total_fees_removed(self) -> float:
        return self.transaction_fees_removed + self.auction_fees_removed

    def advance_round(self) -> int:
        self.current_round += 1
        return self.current_round

    def tick(self) -> int:
        self._clock += 1
        return self._clock

    # ------------------------------------------------------------------
    # Price helpers
    # ------------------------------------------------------------------
    def current_price(self, player_id) -> float:
        """Best available estimate of a player's current price:
        last trade price, else mid of best bid/ask, else baseline."""
        player = self.players_by_id[player_id]
        book = self.books[player_id]
        bb = book.best_buy()
        bs = book.best_sell()
        if player.last_trade_price is not None and player.last_trade_price > 0:
            return player.last_trade_price
        if bb and bs:
            return (bb.price + bs.price) / 2
        if bb:
            return bb.price
        if bs:
            return bs.price
        return self.baseline_price

    def _record_trade(self, player_id, buyer_id, seller_id, qty, price):
        t = Trade.new(player_id, buyer_id, seller_id, qty, price, self._clock)
        self.trade_log.append(t)
        self.players_by_id[player_id].last_trade_price = price
        return t

    # ------------------------------------------------------------------
    # Limit orders
    # ------------------------------------------------------------------
    def submit_limit_buy(self, user, player_id, quantity, price, users_by_id):
        """User places a resting/crossing buy limit order. Cash is escrowed
        immediately (including the taker transaction fee this order would
        owe if it fills at its own limit price); unused escrow refunded
        once the order is filled/rests."""
        escrowed_unit_cost = price * (1 + self.transaction_fee_rate)
        cost = quantity * escrowed_unit_cost
        if user.cash < cost or quantity <= 0:
            return None
        user.cash -= cost  # escrow (base price + fee)
        ts = self.tick()
        order = Order.new(user.user_id, player_id, "buy", quantity, price, ts, self.current_round)
        remaining = self._match_incoming_buy(order, users_by_id, escrowed_unit_cost=escrowed_unit_cost)
        if remaining > 0:
            order.quantity = remaining
            self.books[player_id].add_buy(order)
        return order

    def submit_limit_sell(self, user, player_id, quantity, price, users_by_id):
        have = user.shares_of(player_id)
        if have < quantity or quantity <= 0:
            return None
        user.holdings[player_id] = have - quantity  # escrow shares
        ts = self.tick()
        order = Order.new(user.user_id, player_id, "sell", quantity, price, ts, self.current_round)
        remaining = self._match_incoming_sell(order, users_by_id)
        if remaining > 0:
            order.quantity = remaining
            self.books[player_id].add_sell(order)
        return order

    def _match_incoming_buy(self, incoming: Order, users_by_id, escrowed_unit_cost):
        """Cross incoming buy against resting sells. Returns unfilled qty.
        The incoming buyer is the taker: pays the transaction fee on top
        of each fill's base cost (already reserved in escrow); the resting
        seller receives the fill price in full, unaffected."""
        book = self.books[incoming.player_id]
        remaining = incoming.quantity
        spent = 0.0  # base cost + fee actually charged, for escrow refund math
        while remaining > 0:
            best_sell = book.best_sell()
            if best_sell is None or best_sell.price > incoming.price:
                break
            fill_qty = min(remaining, best_sell.quantity)
            fill_price = best_sell.price
            base_cost = fill_qty * fill_price
            fee = base_cost * self.transaction_fee_rate
            seller = users_by_id[best_sell.user_id]
            buyer = users_by_id[incoming.user_id]
            seller.cash += base_cost
            buyer.holdings[incoming.player_id] = buyer.shares_of(incoming.player_id) + fill_qty
            best_sell.quantity -= fill_qty
            remaining -= fill_qty
            spent += base_cost + fee
            self.transaction_fees_removed += fee
            self._record_trade(incoming.player_id, buyer.user_id, seller.user_id, fill_qty, fill_price)
            buyer.record(action="buy_fill", player_id=incoming.player_id, qty=fill_qty,
                         price=fill_price, counterparty=seller.user_id, fee=fee)
            seller.record(action="sell_fill", player_id=incoming.player_id, qty=fill_qty,
                          price=fill_price, counterparty=buyer.user_id)
        # refund unused escrow: escrowed at escrowed_unit_cost (price+fee)
        # for the full qty, but the filled portion may have cost less.
        filled_qty = incoming.quantity - remaining
        refund = filled_qty * escrowed_unit_cost - spent
        if refund > 0:
            users_by_id[incoming.user_id].cash += refund
        return remaining

    def _match_incoming_sell(self, incoming: Order, users_by_id):
        """Cross incoming sell against resting buys. The incoming seller is
        the taker: the transaction fee is deducted from their proceeds; the
        resting buyer's escrowed cash is unaffected (they still pay/get
        exactly their limit price)."""
        book = self.books[incoming.player_id]
        remaining = incoming.quantity
        while remaining > 0:
            best_buy = book.best_buy()
            if best_buy is None or best_buy.price < incoming.price:
                break
            fill_qty = min(remaining, best_buy.quantity)
            fill_price = best_buy.price
            proceeds = fill_qty * fill_price
            fee = proceeds * self.transaction_fee_rate
            buyer = users_by_id[best_buy.user_id]
            seller = users_by_id[incoming.user_id]
            seller.cash += proceeds - fee
            self.transaction_fees_removed += fee
            buyer.holdings[incoming.player_id] = buyer.shares_of(incoming.player_id) + fill_qty
            best_buy.quantity -= fill_qty
            remaining -= fill_qty
            self._record_trade(incoming.player_id, buyer.user_id, seller.user_id, fill_qty, fill_price)
            buyer.record(action="buy_fill", player_id=incoming.player_id, qty=fill_qty,
                         price=fill_price, counterparty=seller.user_id)
            seller.record(action="sell_fill", player_id=incoming.player_id, qty=fill_qty,
                          price=fill_price, counterparty=buyer.user_id, fee=fee)
        return remaining

    # ------------------------------------------------------------------
    # Quick Buy / Quick Sell
    # ------------------------------------------------------------------
    def quick_buy(self, user, player_id, quantity, users_by_id):
        """Step 1: fill lowest sell orders. Step 2: buy remainder from Bank.
        Step 3: fail for any quantity still unmet. The buyer is always the
        taker here and pays the transaction fee on top of the fill price;
        counterparties (resting sellers, or the Bank) receive/keep exactly
        the fill price, unaffected."""
        if quantity <= 0:
            return 0
        book = self.books[player_id]
        remaining = quantity
        filled_total = 0
        fee_rate = self.transaction_fee_rate

        # Step 1: fill against resting sell orders (cheapest first)
        while remaining > 0:
            best_sell = book.best_sell()
            if best_sell is None:
                break
            unit_cost = best_sell.price * (1 + fee_rate)
            fill_qty = min(remaining, best_sell.quantity)
            cost = fill_qty * unit_cost
            if user.cash < cost:
                # partial afford: fill as much as cash (incl. fee) allows
                affordable_qty = int(user.cash // unit_cost) if unit_cost > 0 else 0
                if affordable_qty <= 0:
                    break
                fill_qty = min(fill_qty, affordable_qty)
                cost = fill_qty * unit_cost
            base_cost = fill_qty * best_sell.price
            fee = cost - base_cost
            seller = users_by_id[best_sell.user_id]
            user.cash -= cost
            seller.cash += base_cost
            self.transaction_fees_removed += fee
            user.holdings[player_id] = user.shares_of(player_id) + fill_qty
            best_sell.quantity -= fill_qty
            remaining -= fill_qty
            filled_total += fill_qty
            self._record_trade(player_id, user.user_id, seller.user_id, fill_qty, best_sell.price)
            if fill_qty == 0:
                break

        # Step 2: remainder from Bank
        if remaining > 0:
            bank_inv = self.bank.inventory.get(player_id, 0)
            if bank_inv > 0:
                fallback = self.players_by_id[player_id].last_trade_price or self.baseline_price
                price = self.bank.quick_buy_price(book, fallback)
                unit_cost = price * (1 + fee_rate)
                buyable = min(remaining, bank_inv)
                affordable_qty = int(user.cash // unit_cost) if unit_cost > 0 else 0
                buyable = min(buyable, affordable_qty)
                if buyable > 0:
                    base_cost = buyable * price
                    cost = buyable * unit_cost
                    fee = cost - base_cost
                    user.cash -= cost
                    self.transaction_fees_removed += fee
                    user.holdings[player_id] = user.shares_of(player_id) + buyable
                    self.bank.inventory[player_id] -= buyable
                    self.bank.cash_absorbed += base_cost
                    remaining -= buyable
                    filled_total += buyable
                    self._record_trade(player_id, user.user_id, -1, buyable, price)
                    user.record(action="quick_buy_bank", player_id=player_id, qty=buyable, price=price, fee=fee)

        # Step 3: any remaining quantity simply fails (no error, just unmet)
        return filled_total

    def quick_sell(self, user, player_id, quantity, users_by_id):
        """Step 1: fill highest active buy orders. Step 2: sell remainder to
        Bank. The seller is always the taker here and pays the transaction
        fee out of their proceeds; counterparties (resting buyers, or the
        Bank) pay/spend exactly the fill price, unaffected."""
        have = user.shares_of(player_id)
        quantity = min(quantity, have)
        if quantity <= 0:
            return 0
        book = self.books[player_id]
        remaining = quantity
        filled_total = 0
        fee_rate = self.transaction_fee_rate

        # Step 1: fill against resting buy orders (highest first)
        while remaining > 0:
            best_buy = book.best_buy()
            if best_buy is None:
                break
            fill_qty = min(remaining, best_buy.quantity)
            gross_proceeds = fill_qty * best_buy.price
            fee = gross_proceeds * fee_rate
            buyer = users_by_id[best_buy.user_id]
            # NOTE: the buyer's cash for this resting order was already
            # escrowed in full (base + fee) when the limit order was placed
            # (see submit_limit_buy), so we must NOT debit buyer.cash again
            # here -- only credit the seller (net of fee) and transfer shares.
            user.cash += gross_proceeds - fee
            self.transaction_fees_removed += fee
            user.holdings[player_id] = user.shares_of(player_id) - fill_qty
            buyer.holdings[player_id] = buyer.shares_of(player_id) + fill_qty
            best_buy.quantity -= fill_qty
            remaining -= fill_qty
            filled_total += fill_qty
            self._record_trade(player_id, buyer.user_id, user.user_id, fill_qty, best_buy.price)

        # Step 2: remainder to Bank (Bank has infinite cash to absorb shares)
        if remaining > 0:
            fallback = self.players_by_id[player_id].last_trade_price or self.baseline_price
            price = self.bank.quick_sell_price(book, fallback)
            gross_proceeds = remaining * price
            fee = gross_proceeds * fee_rate
            user.cash += gross_proceeds - fee
            self.transaction_fees_removed += fee
            user.holdings[player_id] = user.shares_of(player_id) - remaining
            self.bank.inventory[player_id] = self.bank.inventory.get(player_id, 0) + remaining
            self.bank.cash_injected += gross_proceeds
            self._record_trade(player_id, -1, user.user_id, remaining, price)
            user.record(action="quick_sell_bank", player_id=player_id, qty=remaining, price=price, fee=fee)
            filled_total += remaining
            remaining = 0

        return filled_total

    def available_liquidity(self, player_id) -> int:
        """Shares currently visibly available to buy right now: Bank
        inventory plus everything resting on the sell side of the book.
        Used to stop a single large buy from demanding far more than the
        market can actually supply in one shot."""
        bank_qty = self.bank.inventory.get(player_id, 0)
        resting_qty = sum(o.quantity for o in self.books[player_id].active_sell_orders())
        return bank_qty + resting_qty

    def total_escrowed_buy_cash(self) -> float:
        """Cash currently tied up in open (unfilled) resting buy orders,
        INCLUDING the transaction fee reserved alongside each order's base
        cost (see submit_limit_buy) -- that fee portion still belongs to
        the user until/unless the order actually fills. This cash left
        user.cash at order placement but still belongs to the user
        economically -- it's reserved, not spent or destroyed. Needed so
        'total money supply' isn't understated by resting limit orders
        that haven't been hit yet."""
        total = 0.0
        unit_mult = 1 + self.transaction_fee_rate
        for book in self.books.values():
            for o in book.active_buy_orders():
                total += o.quantity * o.price * unit_mult
        return total

    def escrowed_cash_by_user(self) -> dict:
        """user_id -> cash currently tied up in that user's own open buy
        orders (base cost + reserved transaction fee). Needed for accurate
        per-user net worth / ROI -- without this, a user with several
        stale unfilled limit orders looks like their money vanished when
        it's actually just parked, waiting to either fill or expire (see
        expire_stale_orders)."""
        out = {}
        unit_mult = 1 + self.transaction_fee_rate
        for book in self.books.values():
            for o in book.active_buy_orders():
                out[o.user_id] = out.get(o.user_id, 0.0) + o.quantity * o.price * unit_mult
        return out

    def expire_stale_orders(self, max_age_rounds: int, users_by_id: dict) -> int:
        """Cancels (and refunds escrow for) any resting order older than
        `max_age_rounds` trading rounds. Real traders don't leave an
        order sitting untouched for months when the market's moved on --
        without this, cash/shares can get permanently stuck in orders
        that will now never fill, which both misrepresents individual
        users' actual liquidity and can choke off real trading activity
        over a long run. Returns the number of orders cancelled."""
        cancelled = 0
        unit_mult = 1 + self.transaction_fee_rate
        for book in self.books.values():
            for o in book.active_buy_orders():
                if self.current_round - o.placed_round >= max_age_rounds:
                    refund = o.quantity * o.price * unit_mult
                    users_by_id[o.user_id].cash += refund
                    o.quantity = 0
                    cancelled += 1
            for o in book.active_sell_orders():
                if self.current_round - o.placed_round >= max_age_rounds:
                    user = users_by_id[o.user_id]
                    user.holdings[o.player_id] = user.shares_of(o.player_id) + o.quantity
                    o.quantity = 0
                    cancelled += 1
        return cancelled

    # ------------------------------------------------------------------
    # Liquidity / spread metrics
    # ------------------------------------------------------------------
    def bid_ask_spread(self, player_id):
        book = self.books[player_id]
        bb, bs = book.best_buy(), book.best_sell()
        if bb and bs and bb.price > 0:
            return (bs.price - bb.price) / bb.price
        return None
