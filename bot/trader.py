"""
Trader — the main trading loop that ties everything together.
Fetches live data from exchange, runs strategy, checks risk, places orders.
Works with any exchange supported by ccxt (Binance, Bybit, OKX, Kraken, etc.)
"""
import logging
import time
from datetime import datetime

import pandas as pd

from config import settings
from config.accounts import AccountConfig, get_account
from data.exchange_client import ExchangeClient
from data.storage import DataStorage
from strategies.base_strategy import BaseStrategy, Signal
from backtesting.runner import get_strategy
from bot.risk_manager import RiskManager
from bot.order_manager import OrderManager
from bot.position_tracker import PositionTracker

logger = logging.getLogger(__name__)


class Trader:
    """
    Main trading bot. Runs a strategy on a crypto exchange in a loop.
    
    Flow per cycle:
    1. Fetch latest OHLCV candles from exchange
    2. Run strategy to get signal
    3. Check risk limits
    4. Check for order fills
    5. Check stop-loss / take-profit on open positions
    6. Place new orders if signal is actionable
    7. Log everything
    8. Sleep until next cycle
    """

    def __init__(
        self,
        strategy_name: str,
        symbol: str = None,
        account_name: str = "default",
        position_size: float = None,
    ):
        # Account & client
        self.account = get_account(account_name)
        self.client = ExchangeClient(
            exchange_id=self.account.exchange_id,
            api_key=self.account.api_key,
            api_secret=self.account.api_secret,
            password=self.account.password or None,
            sandbox=self.account.sandbox,
        )

        # Strategy
        self.strategy = get_strategy(strategy_name)
        self.strategy_name = strategy_name

        # Market
        self.symbol = symbol or settings.DEFAULT_SYMBOL

        # Position size in USD — we convert to base currency amount per trade
        self.position_size_usd = position_size or settings.DEFAULT_POSITION_SIZE

        # Components
        self.risk = RiskManager()
        self.orders = OrderManager(self.client)
        self.positions = PositionTracker()
        self.storage = DataStorage()

        # State
        self.running = False
        self.cycle_count = 0

        logger.info(
            "Trader initialized: strategy=%s, symbol=%s, size=$%.2f, "
            "exchange=%s, account=%s",
            strategy_name, self.symbol, self.position_size_usd,
            self.account.exchange_id, account_name,
        )

    def run(self):
        """Start the main trading loop."""
        self.running = True
        logger.info(
            "Starting trader: %s on %s (%s)",
            self.strategy.name, self.symbol, self.account.exchange_id,
        )

        # Set initial equity from exchange balance
        try:
            balance = self.client.get_free_balance(settings.QUOTE_CURRENCY)
            self.risk.update_equity(balance)
            logger.info("Starting balance: $%.2f %s", balance, settings.QUOTE_CURRENCY)
        except Exception as e:
            logger.warning("Could not fetch starting balance: %s", e)

        try:
            while self.running:
                self.cycle_count += 1
                try:
                    self._run_cycle()
                except Exception as e:
                    logger.error("Error in cycle %d: %s", self.cycle_count, e, exc_info=True)

                time.sleep(settings.BOT_POLL_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Trader stopped by user")
        finally:
            self._shutdown()

    def stop(self):
        """Stop the trading loop gracefully."""
        self.running = False

    def _fetch_candles(self) -> pd.DataFrame:
        """Fetch OHLCV candles from the exchange."""
        raw = self.client.get_ohlcv(
            self.symbol,
            timeframe=settings.DEFAULT_TIMEFRAME,
            limit=settings.CANDLE_HISTORY_LIMIT,
        )
        df = pd.DataFrame(
            raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df

    def _calculate_amount(self, price: float) -> float:
        """Convert USD position size to base currency amount."""
        if price <= 0:
            return 0
        amount = self.position_size_usd / price
        return self.client.amount_to_precision(self.symbol, amount)

    def _run_cycle(self):
        """Single iteration of the trading loop."""
        logger.debug("Cycle %d starting", self.cycle_count)

        # 1. Fetch live candles from exchange
        try:
            df = self._fetch_candles()
            if df.empty or len(df) < 30:
                logger.warning("Insufficient candle data (%d bars)", len(df))
                return
        except Exception as e:
            logger.error("Failed to fetch candles: %s", e)
            return

        current_price = float(df.iloc[-1]["close"])

        # 2. Check for filled orders
        filled = self.orders.check_fills()
        for order in filled:
            if order.side == "BUY":
                self.positions.open_position(
                    token_id=self.symbol,
                    side="BUY",
                    entry_price=order.price,
                    size=order.amount,
                    stop_loss=order.price * (1 - settings.STOP_LOSS_PCT / 100),
                    take_profit=order.price * (1 + settings.TAKE_PROFIT_PCT / 100),
                    strategy=self.strategy_name,
                )
                self.risk.position_opened()
            elif order.side == "SELL":
                pnl = self.positions.close_position(self.symbol, order.price)
                self.risk.position_closed(pnl)
                self.storage.record_trade(
                    strategy=self.strategy_name,
                    account=self.account.name,
                    token_id=self.symbol,
                    side="SELL",
                    price=order.price,
                    size=order.amount,
                    order_id=order.order_id,
                    notes=f"pnl={pnl:.4f}",
                )

        # 3. Check stop-loss / take-profit
        exits = self.positions.check_exits({self.symbol: current_price})
        for token_id, reason, exit_price in exits:
            logger.info("Exit triggered: %s %s @ $%.4f", reason, token_id, exit_price)
            amount = self._calculate_amount(exit_price)
            if amount > 0:
                self.orders.place_order(
                    symbol=self.symbol,
                    side="sell",
                    price=self.client.price_to_precision(self.symbol, exit_price),
                    amount=amount,
                )

        # 4. Get strategy signal
        try:
            signal = self.strategy.get_signal(df)
        except Exception as e:
            logger.error("Strategy error: %s", e)
            return

        # 5. Act on signal
        if signal.signal == Signal.HOLD:
            logger.debug("Signal: HOLD (reason: %s)", signal.reason)
            return

        # 6. Check risk before trading
        can_trade, risk_reason = self.risk.can_trade(self.position_size_usd)
        if not can_trade:
            logger.warning("Risk blocked: %s", risk_reason)
            return

        if signal.signal == Signal.BUY and self.symbol not in self.positions.positions:
            amount = self._calculate_amount(current_price)
            if amount <= 0:
                logger.warning("Calculated amount is 0 — position size too small")
                return

            logger.info(
                "Signal: BUY %s %.6f @ $%.4f ($%.2f) | confidence=%.2f | %s",
                self.symbol, amount, current_price, self.position_size_usd,
                signal.confidence, signal.reason,
            )
            order_price = self.client.price_to_precision(self.symbol, current_price)
            self.orders.place_order(
                symbol=self.symbol,
                side="buy",
                price=order_price,
                amount=amount,
            )
            self.storage.record_trade(
                strategy=self.strategy_name,
                account=self.account.name,
                token_id=self.symbol,
                side="BUY",
                price=current_price,
                size=amount,
                notes=signal.reason,
            )

        elif signal.signal == Signal.SELL and self.symbol in self.positions.positions:
            pos = self.positions.positions[self.symbol]
            amount = self.client.amount_to_precision(self.symbol, pos.size)

            logger.info(
                "Signal: SELL %s %.6f @ $%.4f | confidence=%.2f | %s",
                self.symbol, amount, current_price,
                signal.confidence, signal.reason,
            )
            order_price = self.client.price_to_precision(self.symbol, current_price)
            self.orders.place_order(
                symbol=self.symbol,
                side="sell",
                price=order_price,
                amount=amount,
            )

        # 7. Log cycle status
        if self.cycle_count % 10 == 0:
            risk_status = self.risk.status()
            logger.info(
                "Cycle %d | %s $%.2f | Positions: %d | Daily P&L: $%.2f | DD: %.1f%%",
                self.cycle_count,
                self.symbol,
                current_price,
                self.positions.get_open_count(),
                risk_status["daily_pnl"],
                risk_status["drawdown_pct"] * 100,
            )

    def _shutdown(self):
        """Clean shutdown — cancel all pending orders."""
        logger.info("Shutting down trader...")
        try:
            self.orders.cancel_all()
        except Exception as e:
            logger.error("Error during shutdown: %s", e)
        logger.info("Trader stopped. Total cycles: %d", self.cycle_count)
