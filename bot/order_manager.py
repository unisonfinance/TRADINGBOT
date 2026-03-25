"""
Order Manager — handles limit order lifecycle on crypto exchanges via ccxt.
Cancels existing orders before placing new ones to avoid duplicates.
Uses LIMIT ORDERS for lower fees.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime

from data.exchange_client import ExchangeClient

logger = logging.getLogger(__name__)


@dataclass
class ManagedOrder:
    """Tracks a managed order."""
    order_id: str
    symbol: str
    side: str
    price: float
    amount: float
    cost: float = 0.0  # price * amount (USD value)
    status: str = "open"  # open, filled, cancelled
    placed_at: str = ""
    filled_at: str = ""


class OrderManager:
    """
    Manages limit orders on a crypto exchange.
    
    Rules:
    - Cancel existing orders before placing new ones (avoid duplicates)
    - Use limit orders for lower fees
    - Track order status and auto-cleanup stale orders
    """

    def __init__(self, client: ExchangeClient):
        self.client = client
        self.active_orders: dict[str, ManagedOrder] = {}

    def place_order(
        self, symbol: str, side: str, price: float, amount: float,
        use_market: bool = False,
    ) -> ManagedOrder | None:
        """
        Place an order after cancelling existing orders for this symbol.

        Args:
            symbol: Trading pair (e.g. 'BTC/USDT')
            side: 'buy' or 'sell'
            price: Limit price (ignored when use_market=True)
            amount: Amount in base currency
            use_market: If True, place a market order for instant fill
        Returns:
            ManagedOrder if successful, None if failed
        """
        # Cancel existing orders for this symbol first
        self.cancel_symbol_orders(symbol)

        try:
            # Round to exchange precision
            amount = self.client.amount_to_precision(symbol, amount)

            if use_market:
                response = self.client.place_market_order(
                    symbol=symbol,
                    side=side,
                    amount=amount,
                )
                fill_price = float(response.get("average", response.get("price", price)) or price)
            else:
                price = self.client.price_to_precision(symbol, price)
                response = self.client.place_limit_order(
                    symbol=symbol,
                    side=side,
                    price=price,
                    amount=amount,
                )
                fill_price = price

            order_id = response.get("id", "unknown")
            status = response.get("status", "open")
            order = ManagedOrder(
                order_id=order_id,
                symbol=symbol,
                side=side.upper(),
                price=fill_price,
                amount=amount,
                cost=fill_price * amount,
                status="filled" if status == "closed" else "open",
                placed_at=datetime.utcnow().isoformat(),
                filled_at=datetime.utcnow().isoformat() if status == "closed" else "",
            )
            self.active_orders[order_id] = order
            logger.info(
                "Order placed: %s %s %.6f @ $%.4f ($%.2f)",
                side.upper(), symbol, amount, price, price * amount,
            )
            return order

        except Exception as e:
            logger.error("Failed to place order: %s", e)
            return None

    def cancel_symbol_orders(self, symbol: str) -> int:
        """Cancel all active orders for a specific symbol."""
        cancelled = 0
        try:
            cancelled = self.client.cancel_all_orders(symbol)
        except Exception as e:
            logger.warning("Error cancelling orders for %s: %s", symbol, e)

        # Clean up local tracking
        to_remove = [
            oid for oid, o in self.active_orders.items()
            if o.symbol == symbol
        ]
        for oid in to_remove:
            self.active_orders[oid].status = "cancelled"
            del self.active_orders[oid]

        return cancelled

    def cancel_all(self) -> int:
        """Cancel ALL active orders across all symbols."""
        symbols = set(o.symbol for o in self.active_orders.values())
        total = 0
        for sym in symbols:
            total += self.cancel_symbol_orders(sym)
        logger.info("Cancelled all orders: %d total", total)
        return total

    def check_fills(self) -> list[ManagedOrder]:
        """
        Check which orders have been filled.
        Returns list of newly filled orders.
        """
        filled = []
        for order_id, order in list(self.active_orders.items()):
            try:
                exchange_order = self.client.get_order(order_id, order.symbol)
                status = exchange_order.get("status", "")

                if status == "closed":
                    order.status = "filled"
                    order.filled_at = datetime.utcnow().isoformat()
                    # Update with actual fill price if available
                    avg_price = exchange_order.get("average", order.price)
                    if avg_price:
                        order.price = float(avg_price)
                    filled.append(order)
                    del self.active_orders[order_id]
                    logger.info(
                        "Order filled: %s %s %.6f @ $%.4f",
                        order.side, order.symbol, order.amount, order.price,
                    )
                elif status == "canceled" or status == "cancelled":
                    del self.active_orders[order_id]
                    logger.info("Order was cancelled externally: %s", order_id)

            except Exception as e:
                logger.warning("Error checking order %s: %s", order_id, e)

        return filled

    def get_active_count(self) -> int:
        return len(self.active_orders)

    def status(self) -> list[dict]:
        return [
            {
                "order_id": o.order_id,
                "symbol": o.symbol,
                "side": o.side,
                "price": o.price,
                "amount": o.amount,
                "cost": o.cost,
                "placed_at": o.placed_at,
            }
            for o in self.active_orders.values()
        ]
