"""
Unified exchange client using ccxt.
Supports 100+ exchanges: Binance, Bybit, OKX, Kraken, etc.
Uses LIMIT ORDERS for lower fees.
"""
import logging
import ccxt

from config import settings

logger = logging.getLogger(__name__)


class ExchangeClient:
    """Wrapper around ccxt for unified exchange access."""

    def __init__(
        self,
        exchange_id: str,
        api_key: str,
        api_secret: str,
        password: str = None,
        sandbox: bool = False,
    ):
        """
        Initialize exchange connection.

        Args:
            exchange_id: Exchange name (binance, bybit, okx, kraken, etc.)
            api_key: API key from exchange
            api_secret: API secret from exchange
            password: Passphrase (required by some exchanges like OKX, Kucoin)
            sandbox: Use testnet/sandbox if True (recommended for testing)
        """
        exchange_class = getattr(ccxt, exchange_id, None)
        if exchange_class is None:
            raise ValueError(
                f"Exchange '{exchange_id}' not supported. "
                f"See https://github.com/ccxt/ccxt#supported-cryptocurrency-exchange-markets"
            )

        config = {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": "spot",
                "adjustForTimeDifference": True,
                "recvWindow": 10000,
            },
        }
        if password:
            config["password"] = password

        self.exchange = exchange_class(config)

        if sandbox:
            self.exchange.set_sandbox_mode(True)
            logger.info("SANDBOX mode enabled for %s", exchange_id)

        # Sync local clock with exchange server time to prevent -1021 timestamp errors
        try:
            self.exchange.load_time_difference()
        except Exception as e:
            logger.warning("Could not load time difference: %s", e)

        self.exchange_id = exchange_id
        logger.info("Exchange client initialized: %s", exchange_id)

    # ── Market data ──────────────────────────────────────────────────

    def get_ticker(self, symbol: str) -> dict:
        """Get current ticker for a symbol (e.g. 'BTC/USDT')."""
        return self.exchange.fetch_ticker(symbol)

    def get_price(self, symbol: str) -> float:
        """Get the last traded price for a symbol."""
        ticker = self.get_ticker(symbol)
        return float(ticker.get("last", 0))

    def get_bid_ask(self, symbol: str) -> dict:
        """Get best bid/ask/spread."""
        ticker = self.get_ticker(symbol)
        bid = float(ticker.get("bid", 0))
        ask = float(ticker.get("ask", 0))
        return {"bid": bid, "ask": ask, "spread": ask - bid}

    def get_orderbook(self, symbol: str, limit: int = 20) -> dict:
        """Get order book."""
        return self.exchange.fetch_order_book(symbol, limit=limit)

    def get_ohlcv(
        self, symbol: str, timeframe: str = None, limit: int = None
    ) -> list:
        """Fetch OHLCV candles."""
        timeframe = timeframe or settings.DEFAULT_TIMEFRAME
        limit = limit or settings.CANDLE_HISTORY_LIMIT
        return self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    # ── Order management (LIMIT ORDERS for lower fees) ───────────────

    def place_limit_order(
        self, symbol: str, side: str, price: float, amount: float
    ) -> dict:
        """
        Place a limit order.

        Args:
            symbol: Trading pair (e.g. 'BTC/USDT')
            side: 'buy' or 'sell'
            price: Limit price
            amount: Amount in base currency (e.g. BTC amount)
        Returns:
            Order response dict with 'id', 'status', etc.
        """
        if amount <= 0:
            raise ValueError(f"Amount must be positive, got {amount}")
        if price <= 0:
            raise ValueError(f"Price must be positive, got {price}")

        order = self.exchange.create_limit_order(
            symbol=symbol,
            side=side.lower(),
            amount=amount,
            price=price,
        )
        logger.info(
            "Placed %s limit order: %s %.6f @ $%.4f (id=%s)",
            side, symbol, amount, price, order.get("id"),
        )
        return order

    def place_market_order(
        self, symbol: str, side: str, amount: float
    ) -> dict:
        """
        Place a market order (use sparingly — higher fees).

        Args:
            symbol: Trading pair
            side: 'buy' or 'sell'
            amount: Amount in base currency
        """
        order = self.exchange.create_market_order(
            symbol=symbol,
            side=side.lower(),
            amount=amount,
        )
        logger.info(
            "Placed %s market order: %s %.6f (id=%s)",
            side, symbol, amount, order.get("id"),
        )
        return order

    def cancel_order(self, order_id: str, symbol: str) -> dict:
        """Cancel a specific order."""
        result = self.exchange.cancel_order(order_id, symbol)
        logger.info("Cancelled order %s on %s", order_id, symbol)
        return result

    def cancel_all_orders(self, symbol: str = None) -> int:
        """Cancel all open orders for a symbol (or all symbols)."""
        open_orders = self.get_open_orders(symbol)
        cancelled = 0
        for order in open_orders:
            try:
                self.cancel_order(order["id"], order.get("symbol", symbol))
                cancelled += 1
            except Exception as e:
                logger.warning("Failed to cancel order %s: %s", order["id"], e)
        return cancelled

    def get_open_orders(self, symbol: str = None) -> list:
        """Get all open orders."""
        if symbol:
            return self.exchange.fetch_open_orders(symbol)
        return self.exchange.fetch_open_orders()

    def get_order(self, order_id: str, symbol: str) -> dict:
        """Get a specific order by ID."""
        return self.exchange.fetch_order(order_id, symbol)

    # ── Account / balance ────────────────────────────────────────────

    def get_balance(self) -> dict:
        """Get account balances."""
        return self.exchange.fetch_balance()

    def get_free_balance(self, currency: str = "USDT") -> float:
        """Get free (available) balance for a currency."""
        balance = self.get_balance()
        return float(balance.get("free", {}).get(currency, 0))

    def get_positions(self) -> list:
        """Get open positions (for futures/margin)."""
        try:
            return self.exchange.fetch_positions()
        except Exception:
            return []

    def get_my_trades(self, symbol: str, limit: int = 50) -> list:
        """Get recent trade history."""
        return self.exchange.fetch_my_trades(symbol, limit=limit)

    # ── Utilities ────────────────────────────────────────────────────

    def get_markets(self) -> list:
        """Get all available markets."""
        return self.exchange.load_markets()

    def get_min_order_amount(self, symbol: str) -> float:
        """Get minimum order amount for a symbol."""
        markets = self.exchange.load_markets()
        if symbol in markets:
            limits = markets[symbol].get("limits", {}).get("amount", {})
            return float(limits.get("min", 0))
        return 0

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        """Round amount to exchange precision."""
        return float(self.exchange.amount_to_precision(symbol, amount))

    def price_to_precision(self, symbol: str, price: float) -> float:
        """Round price to exchange precision."""
        return float(self.exchange.price_to_precision(symbol, price))
