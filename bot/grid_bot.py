"""
Grid Trading Bot — places buy and sell orders at pre-defined price levels.
Profits from range-bound markets by catching oscillations in the grid.
"""
import logging
import time
from datetime import datetime

from config import settings
from data.exchange_client import ExchangeClient
from config.accounts import get_account

logger = logging.getLogger(__name__)


class GridBot:
    """
    Grid Trading Bot. Creates a grid of buy/sell orders across a price range.

    How it works:
    1. Define upper and lower price bounds
    2. Divide into N grid levels
    3. Place buy orders below current price, sell orders above
    4. When a buy fills, place a sell one level up. When a sell fills, place a buy one level down.
    """

    def __init__(
        self,
        symbol: str = "BTC/USDT",
        lower_price: float = 90000,
        upper_price: float = 110000,
        grid_count: int = 10,
        total_investment: float = 1000.0,
        account_name: str = "default",
        uid: str = None,
        paper: bool = False,
    ):
        self.symbol = symbol
        self.lower_price = lower_price
        self.upper_price = upper_price
        self.grid_count = grid_count
        self.total_investment = total_investment
        self.uid = uid
        self.paper = paper

        # Calculate grid levels
        step = (upper_price - lower_price) / grid_count
        self.grid_levels = [round(lower_price + i * step, 2) for i in range(grid_count + 1)]
        self.amount_per_grid = total_investment / grid_count

        # Exchange
        if not paper:
            account = get_account(account_name)
            self.client = ExchangeClient(
                exchange_id=account.exchange_id,
                api_key=account.api_key,
                api_secret=account.api_secret,
                password=account.password or None,
                sandbox=account.sandbox,
            )
        else:
            self.client = None

        # State
        self.running = False
        self.cycle_count = 0
        self.active_orders = {}  # level -> order_info
        self.filled_buys = 0
        self.filled_sells = 0
        self.realized_pnl = 0.0
        self.trades = []

        logger.info(
            "Grid Bot init: %s, range=$%.2f-$%.2f, %d levels, $%.2f total",
            symbol, lower_price, upper_price, grid_count, total_investment,
        )

    def run(self):
        self.running = True
        logger.info("Grid Bot started: %s", self.symbol)
        try:
            while self.running:
                self.cycle_count += 1
                try:
                    self._run_cycle()
                except Exception as e:
                    logger.error("Grid cycle error: %s", e)
                time.sleep(10)  # Check every 10 seconds
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False

    def stop(self):
        self.running = False

    def _get_price(self) -> float:
        if self.client:
            return self.client.get_price(self.symbol)
        else:
            import ccxt
            ex = ccxt.binance()
            ticker = ex.fetch_ticker(self.symbol)
            return float(ticker.get("last", 0))

    def _run_cycle(self):
        current_price = self._get_price()
        if current_price <= 0:
            return

        # Check each grid level
        for i, level in enumerate(self.grid_levels[:-1]):
            upper = self.grid_levels[i + 1]
            level_key = f"L{i}"

            if level_key in self.active_orders:
                order = self.active_orders[level_key]
                # Check if price crossed through our level
                if order["side"] == "BUY" and current_price <= level:
                    # Buy filled
                    self._fill_order(level_key, "BUY", level, current_price)
                elif order["side"] == "SELL" and current_price >= upper:
                    # Sell filled
                    self._fill_order(level_key, "SELL", upper, current_price)
            else:
                # Place initial orders
                if current_price > level and current_price <= upper:
                    # Current price is in this grid — place buy below, sell above
                    self.active_orders[level_key] = {"side": "BUY", "price": level}
                elif current_price > upper:
                    # Price above this level — already filled, place sell
                    self.active_orders[level_key] = {"side": "SELL", "price": upper}
                elif current_price <= level:
                    # Price below — place buy
                    self.active_orders[level_key] = {"side": "BUY", "price": level}

    def _fill_order(self, level_key, side, fill_price, current_price):
        amount = self.amount_per_grid / fill_price

        if side == "BUY":
            self.filled_buys += 1
            # Place sell order one level up
            level_idx = int(level_key.replace("L", ""))
            if level_idx + 1 < len(self.grid_levels):
                self.active_orders[level_key] = {
                    "side": "SELL",
                    "price": self.grid_levels[level_idx + 1],
                    "buy_price": fill_price,
                }

            if not self.paper and self.client:
                try:
                    precise = self.client.amount_to_precision(self.symbol, amount)
                    self.client.exchange.create_market_buy_order(self.symbol, precise)
                except Exception as e:
                    logger.error("Grid buy failed: %s", e)

        elif side == "SELL":
            self.filled_sells += 1
            buy_price = self.active_orders.get(level_key, {}).get("buy_price", fill_price)
            pnl = (fill_price - buy_price) * amount
            self.realized_pnl += pnl

            # Place buy order one level down
            level_idx = int(level_key.replace("L", ""))
            self.active_orders[level_key] = {
                "side": "BUY",
                "price": self.grid_levels[level_idx],
            }

            if not self.paper and self.client:
                try:
                    precise = self.client.amount_to_precision(self.symbol, amount)
                    self.client.exchange.create_market_sell_order(self.symbol, precise)
                except Exception as e:
                    logger.error("Grid sell failed: %s", e)

        trade = {
            "side": side,
            "symbol": self.symbol,
            "price": round(fill_price, 4),
            "amount": round(amount, 8),
            "level": level_key,
            "pnl": round(pnl, 4) if side == "SELL" else None,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "paper": self.paper,
        }
        self.trades.append(trade)

        if self.uid:
            try:
                from services.firestore_service import save_doc
                save_doc(self.uid, "grid_trades", trade)
            except Exception:
                pass

        logger.info(
            "Grid %s: %s @ $%.2f (level %s%s)",
            side, self.symbol, fill_price, level_key,
            f", pnl=${pnl:.2f}" if side == "SELL" else "",
        )

    def get_status(self):
        current_price = 0
        try:
            current_price = self._get_price()
        except Exception:
            pass

        return {
            "symbol": self.symbol,
            "lower_price": self.lower_price,
            "upper_price": self.upper_price,
            "grid_count": self.grid_count,
            "total_investment": self.total_investment,
            "filled_buys": self.filled_buys,
            "filled_sells": self.filled_sells,
            "realized_pnl": round(self.realized_pnl, 2),
            "active_levels": len(self.active_orders),
            "current_price": round(current_price, 2),
            "running": self.running,
            "paper": self.paper,
            "type": "grid",
        }
