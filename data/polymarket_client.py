"""
Polymarket CLOB API client wrapper.
Handles connection, authentication, order placement, and cancellation.
LIMIT ORDERS ONLY — they are free on Polymarket.
"""
import logging
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from config.accounts import AccountConfig
from config import settings

logger = logging.getLogger(__name__)


class PolymarketClient:
    """Wrapper around py-clob-client for Polymarket CLOB API."""

    def __init__(self, account: AccountConfig):
        self.account = account
        self.client = ClobClient(
            host=settings.POLYMARKET_HOST,
            key=account.private_key,
            chain_id=account.chain_id,
            funder=account.funder_address,
            signature_type=settings.SIGNATURE_TYPE,
        )
        # Derive or create API credentials (one-time setup)
        self.client.set_api_creds(self.client.create_or_derive_api_creds())
        logger.info("Polymarket client initialized for account: %s", account.name)

    # ── Market data ──────────────────────────────────────────────────

    def get_markets(self, next_cursor: str = "") -> dict:
        """Fetch available markets."""
        return self.client.get_markets(next_cursor=next_cursor)

    def get_market(self, condition_id: str) -> dict:
        """Fetch a specific market by condition ID."""
        return self.client.get_market(condition_id=condition_id)

    def get_orderbook(self, token_id: str) -> dict:
        """Get the order book for a specific token."""
        return self.client.get_order_book(token_id=token_id)

    def get_midpoint(self, token_id: str) -> float:
        """Get the midpoint price for a token."""
        book = self.get_orderbook(token_id)
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        if not bids or not asks:
            return 0.0
        best_bid = float(bids[0]["price"])
        best_ask = float(asks[0]["price"])
        return round((best_bid + best_ask) / 2, settings.PRICE_DECIMALS)

    def get_spread(self, token_id: str) -> dict:
        """Get bid/ask/spread for a token."""
        book = self.get_orderbook(token_id)
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        if not bids or not asks:
            return {"bid": 0.0, "ask": 0.0, "spread": 0.0}
        best_bid = float(bids[0]["price"])
        best_ask = float(asks[0]["price"])
        return {
            "bid": best_bid,
            "ask": best_ask,
            "spread": round(best_ask - best_bid, settings.PRICE_DECIMALS),
        }

    # ── Order management (LIMIT ONLY) ───────────────────────────────

    def place_limit_order(
        self, token_id: str, side: str, price: float, size: float
    ) -> dict:
        """
        Place a limit order (GTC). Limit orders are FREE on Polymarket.
        
        Args:
            token_id: The market token ID
            side: "BUY" or "SELL"
            price: Price between 0.01 and 0.99
            size: Size in USD
        Returns:
            Order response from Polymarket
        """
        if price < 0.01 or price > 0.99:
            raise ValueError(f"Price must be 0.01-0.99, got {price}")
        if size <= 0:
            raise ValueError(f"Size must be positive, got {size}")

        order_side = BUY if side.upper() == "BUY" else SELL
        order_args = OrderArgs(
            price=price,
            size=size,
            side=order_side,
            token_id=token_id,
        )
        signed_order = self.client.create_order(order_args)
        response = self.client.post_order(signed_order, OrderType.GTC)
        logger.info(
            "Placed %s limit order: %s @ $%.2f x %.2f",
            side, token_id[:8], price, size,
        )
        return response

    def cancel_order(self, order_id: str) -> dict:
        """Cancel a specific order by ID."""
        response = self.client.cancel(order_id=order_id)
        logger.info("Cancelled order: %s", order_id)
        return response

    def cancel_all_orders(self, token_id: str, market_id: str = None) -> int:
        """
        Cancel all open orders for a token. 
        Always cancel before placing new orders to avoid duplicates.
        Returns count of cancelled orders.
        """
        open_orders = self.get_open_orders(token_id, market_id)
        cancelled = 0
        for order in open_orders:
            try:
                self.cancel_order(order["id"])
                cancelled += 1
            except Exception as e:
                logger.warning("Failed to cancel order %s: %s", order["id"], e)
        logger.info("Cancelled %d orders for token %s", cancelled, token_id[:8])
        return cancelled

    def get_open_orders(self, token_id: str = None, market_id: str = None) -> list:
        """Get all open orders, optionally filtered by token/market."""
        kwargs = {}
        if market_id:
            kwargs["market"] = market_id
        if token_id:
            kwargs["asset_id"] = token_id
        return self.client.get_orders(**kwargs)

    # ── Position info ────────────────────────────────────────────────

    def get_positions(self) -> list:
        """Get all current positions."""
        return self.client.get_balances()

    def get_trades(self, market_id: str = None) -> list:
        """Get trade history."""
        kwargs = {}
        if market_id:
            kwargs["market"] = market_id
        return self.client.get_trades(**kwargs)
