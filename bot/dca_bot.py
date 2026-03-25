"""
DCA Bot — Dollar Cost Averaging bot that buys at regular intervals.
Supports fixed-interval and dip-buying modes.
"""
import logging
import time
from datetime import datetime

import pandas as pd

from config import settings
from data.exchange_client import ExchangeClient
from config.accounts import get_account

logger = logging.getLogger(__name__)


class DCABot:
    """
    Dollar Cost Averaging bot. Buys a fixed USD amount at regular intervals,
    optionally buying more on dips.

    Modes:
        - fixed: Buy every N seconds regardless of price
        - dip: Only buy when price drops X% from last purchase
        - hybrid: Fixed interval + extra on dips
    """

    def __init__(
        self,
        symbol: str = "BTC/USDT",
        amount_per_buy: float = 10.0,
        interval_seconds: int = 3600,
        mode: str = "fixed",
        dip_pct: float = 5.0,
        max_buys: int = 0,
        account_name: str = "default",
        uid: str = None,
        paper: bool = False,
    ):
        self.symbol = symbol
        self.amount_per_buy = amount_per_buy
        self.interval = interval_seconds
        self.mode = mode
        self.dip_pct = dip_pct / 100.0
        self.max_buys = max_buys  # 0 = unlimited
        self.uid = uid
        self.paper = paper

        # Exchange client (real or paper)
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
        self.buy_count = 0
        self.total_invested = 0.0
        self.total_coins = 0.0
        self.avg_price = 0.0
        self.last_buy_price = 0.0
        self.trades = []
        self.cycle_count = 0

        logger.info(
            "DCA Bot init: %s, $%.2f every %ds, mode=%s",
            symbol, amount_per_buy, interval_seconds, mode,
        )

    def run(self):
        self.running = True
        logger.info("DCA Bot started: %s", self.symbol)
        try:
            while self.running:
                self.cycle_count += 1
                try:
                    self._run_cycle()
                except Exception as e:
                    logger.error("DCA cycle error: %s", e)
                time.sleep(self.interval)
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            logger.info("DCA Bot stopped. Total invested: $%.2f", self.total_invested)

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
        if self.max_buys > 0 and self.buy_count >= self.max_buys:
            logger.info("DCA: Max buys reached (%d)", self.max_buys)
            self.running = False
            return

        current_price = self._get_price()
        if current_price <= 0:
            return

        should_buy = False

        if self.mode == "fixed":
            should_buy = True
        elif self.mode == "dip":
            if self.last_buy_price == 0:
                should_buy = True
            elif current_price <= self.last_buy_price * (1 - self.dip_pct):
                should_buy = True
        elif self.mode == "hybrid":
            should_buy = True
            # Buy extra on dip
            if self.last_buy_price > 0 and current_price <= self.last_buy_price * (1 - self.dip_pct):
                self._execute_buy(current_price, extra=True)

        if should_buy:
            self._execute_buy(current_price)

    def _execute_buy(self, price: float, extra: bool = False):
        amount = self.amount_per_buy / price

        if not self.paper and self.client:
            try:
                precise_amount = self.client.amount_to_precision(self.symbol, amount)
                order = self.client.exchange.create_market_buy_order(self.symbol, precise_amount)
                logger.info("DCA BUY: %s %.6f @ $%.4f", self.symbol, precise_amount, price)
            except Exception as e:
                logger.error("DCA order failed: %s", e)
                return

        # Update stats
        self.buy_count += 1
        self.total_invested += self.amount_per_buy
        self.total_coins += amount
        self.avg_price = self.total_invested / self.total_coins if self.total_coins > 0 else 0
        self.last_buy_price = price

        trade = {
            "side": "BUY",
            "symbol": self.symbol,
            "price": round(price, 4),
            "amount": round(amount, 8),
            "invested": round(self.amount_per_buy, 2),
            "total_invested": round(self.total_invested, 2),
            "avg_price": round(self.avg_price, 4),
            "extra_dip_buy": extra,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "paper": self.paper,
        }
        self.trades.append(trade)

        if self.uid:
            try:
                from services.firestore_service import save_doc
                save_doc(self.uid, "dca_trades", trade)
            except Exception as e:
                logger.warning("DCA Firestore save failed: %s", e)

    def get_status(self):
        current_price = 0
        try:
            current_price = self._get_price()
        except Exception:
            pass

        current_value = self.total_coins * current_price if current_price > 0 else 0
        unrealized_pnl = current_value - self.total_invested

        return {
            "symbol": self.symbol,
            "mode": self.mode,
            "amount_per_buy": self.amount_per_buy,
            "interval": self.interval,
            "buy_count": self.buy_count,
            "total_invested": round(self.total_invested, 2),
            "total_coins": round(self.total_coins, 8),
            "avg_price": round(self.avg_price, 4),
            "current_price": round(current_price, 4),
            "current_value": round(current_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "running": self.running,
            "paper": self.paper,
            "type": "dca",
        }
