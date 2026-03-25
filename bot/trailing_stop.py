"""
Trailing Stop — dynamic stop-loss that follows price movement.
Can be attached to any position to maximize profits.
"""
import logging

logger = logging.getLogger(__name__)


class TrailingStop:
    """
    Trailing stop-loss manager. Adjusts the stop price as the market
    moves in the trade's favor.

    Modes:
        - percentage: Trail by a fixed percentage from highest price
        - atr: Trail by ATR multiplier (requires ATR value)
        - amount: Trail by a fixed USD amount
    """

    def __init__(
        self,
        mode: str = "percentage",
        trail_pct: float = 2.0,
        trail_amount: float = 0.0,
        atr_multiplier: float = 2.0,
        activation_pct: float = 0.0,
    ):
        self.mode = mode
        self.trail_pct = trail_pct / 100.0  # Convert percent to decimal
        self.trail_amount = trail_amount
        self.atr_multiplier = atr_multiplier
        self.activation_pct = activation_pct / 100.0  # Only start trailing after this % profit

        # State per symbol
        self._highest: dict[str, float] = {}
        self._lowest: dict[str, float] = {}
        self._activated: dict[str, bool] = {}
        self._stop_prices: dict[str, float] = {}

    def update(self, symbol: str, current_price: float, side: str = "BUY",
               entry_price: float = 0.0, atr: float = 0.0) -> float | None:
        """
        Update the trailing stop for a symbol.

        Returns:
            The current trailing stop price, or None if not yet activated.
        """
        if side == "BUY":
            return self._update_long(symbol, current_price, entry_price, atr)
        else:
            return self._update_short(symbol, current_price, entry_price, atr)

    def _update_long(self, symbol, price, entry_price, atr):
        # Track highest price
        if symbol not in self._highest or price > self._highest[symbol]:
            self._highest[symbol] = price

        highest = self._highest[symbol]

        # Check activation threshold
        if self.activation_pct > 0 and entry_price > 0:
            profit_pct = (price - entry_price) / entry_price
            if profit_pct < self.activation_pct:
                self._activated[symbol] = False
                return None
        self._activated[symbol] = True

        # Calculate stop price
        if self.mode == "percentage":
            stop = highest * (1 - self.trail_pct)
        elif self.mode == "atr" and atr > 0:
            stop = highest - (atr * self.atr_multiplier)
        elif self.mode == "amount":
            stop = highest - self.trail_amount
        else:
            stop = highest * (1 - self.trail_pct)

        # Only ratchet up, never down
        current_stop = self._stop_prices.get(symbol, 0)
        if stop > current_stop:
            self._stop_prices[symbol] = stop

        return self._stop_prices[symbol]

    def _update_short(self, symbol, price, entry_price, atr):
        # Track lowest price
        if symbol not in self._lowest or price < self._lowest[symbol]:
            self._lowest[symbol] = price

        lowest = self._lowest[symbol]

        # Check activation
        if self.activation_pct > 0 and entry_price > 0:
            profit_pct = (entry_price - price) / entry_price
            if profit_pct < self.activation_pct:
                self._activated[symbol] = False
                return None
        self._activated[symbol] = True

        if self.mode == "percentage":
            stop = lowest * (1 + self.trail_pct)
        elif self.mode == "atr" and atr > 0:
            stop = lowest + (atr * self.atr_multiplier)
        elif self.mode == "amount":
            stop = lowest + self.trail_amount
        else:
            stop = lowest * (1 + self.trail_pct)

        current_stop = self._stop_prices.get(symbol, float("inf"))
        if stop < current_stop:
            self._stop_prices[symbol] = stop

        return self._stop_prices[symbol]

    def should_exit(self, symbol: str, current_price: float, side: str = "BUY") -> bool:
        """Check if the trailing stop has been hit."""
        if symbol not in self._stop_prices or not self._activated.get(symbol, False):
            return False

        stop = self._stop_prices[symbol]
        if side == "BUY":
            return current_price <= stop
        else:
            return current_price >= stop

    def get_stop_price(self, symbol: str) -> float | None:
        return self._stop_prices.get(symbol)

    def reset(self, symbol: str):
        """Clear trailing stop data for a symbol."""
        self._highest.pop(symbol, None)
        self._lowest.pop(symbol, None)
        self._activated.pop(symbol, None)
        self._stop_prices.pop(symbol, None)

    def get_status(self, symbol: str) -> dict:
        return {
            "symbol": symbol,
            "mode": self.mode,
            "trail_pct": round(self.trail_pct * 100, 2),
            "activated": self._activated.get(symbol, False),
            "stop_price": self._stop_prices.get(symbol),
            "highest_price": self._highest.get(symbol),
            "lowest_price": self._lowest.get(symbol),
        }
