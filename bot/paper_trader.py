"""
Paper Trader — wraps the real Trader but simulates orders without hitting the exchange.
All trades are recorded to Firestore paper_trades collection.
"""
import logging
import time
from datetime import datetime

import pandas as pd

from config import settings
from data.exchange_client import ExchangeClient
from backtesting.runner import get_strategy
from bot.risk_manager import RiskManager
from bot.position_tracker import PositionTracker

logger = logging.getLogger(__name__)


class PaperTrader:
    """
    Simulated trading bot. Uses real market data but does NOT place real orders.
    Tracks a virtual balance and records paper trades to Firestore.
    """

    def __init__(
        self,
        strategy_name: str,
        symbol: str = None,
        position_size: float = None,
        timeframe: str = None,
        strategy_kwargs: dict = None,
        starting_balance: float = 10000.0,
        uid: str = None,
    ):
        self.strategy = get_strategy(strategy_name, **(strategy_kwargs or {}))
        self.strategy_name = strategy_name
        self.symbol = symbol or settings.DEFAULT_SYMBOL
        self.timeframe = timeframe or settings.DEFAULT_TIMEFRAME
        self.position_size_usd = position_size or settings.DEFAULT_POSITION_SIZE
        self.uid = uid  # Firestore user ID for saving paper trades

        # Virtual portfolio
        self.balance = starting_balance
        self.starting_balance = starting_balance
        self.positions = PositionTracker()
        self.risk = RiskManager()

        # State
        self.running = False
        self.cycle_count = 0
        self.trades_log = []  # in-memory trade log
        self.equity_history = []  # (timestamp, equity) for charting

        # Public exchange for data feed
        self._exchange = None

        logger.info(
            "PaperTrader initialized: %s on %s, virtual_balance=$%.2f",
            strategy_name, self.symbol, starting_balance,
        )

    def _get_exchange(self):
        if self._exchange is None:
            import ccxt
            self._exchange = ccxt.binance()  # default public data feed
        return self._exchange

    def _fetch_candles(self) -> pd.DataFrame:
        exchange = self._get_exchange()
        raw = exchange.fetch_ohlcv(
            self.symbol,
            timeframe=self.timeframe,
            limit=settings.CANDLE_HISTORY_LIMIT,
        )
        df = pd.DataFrame(
            raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df

    def _calculate_amount(self, price: float) -> float:
        if price <= 0:
            return 0
        return self.position_size_usd / price

    def run(self):
        """Start the paper trading loop."""
        self.running = True
        self.risk.update_equity(self.balance)
        logger.info("Starting paper trader: %s on %s", self.strategy.name, self.symbol)

        try:
            while self.running:
                self.cycle_count += 1
                try:
                    self._run_cycle()
                except Exception as e:
                    logger.error("Paper cycle %d error: %s", self.cycle_count, e, exc_info=True)
                time.sleep(settings.BOT_POLL_INTERVAL)
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            logger.info(
                "Paper trader stopped. Final balance: $%.2f (started: $%.2f, P&L: $%.2f)",
                self.balance, self.starting_balance, self.balance - self.starting_balance,
            )

    def stop(self):
        self.running = False

    def _run_cycle(self):
        from strategies.base_strategy import Signal

        try:
            df = self._fetch_candles()
            if df.empty or len(df) < 30:
                return
        except Exception as e:
            logger.error("Paper: failed to fetch candles: %s", e)
            return

        current_price = float(df.iloc[-1]["close"])
        now_iso = datetime.utcnow().isoformat() + "Z"

        # Record equity snapshot
        unrealized = self.positions.total_unrealized_pnl({self.symbol: current_price})
        equity = self.balance + unrealized
        self.equity_history.append({"timestamp": now_iso, "equity": round(equity, 2)})

        # Check SL/TP
        exits = self.positions.check_exits({self.symbol: current_price})
        for token_id, reason, exit_price in exits:
            pos = self.positions.positions.get(token_id)
            if pos:
                pnl = pos.unrealized_pnl(exit_price)
                self.balance += pnl
                self.positions.close_position(token_id, exit_price)
                self._record_paper_trade("SELL", exit_price, pos.size, pnl, f"paper_{reason}")

        # Get signal
        actual_in_position = self.symbol in self.positions.positions
        try:
            signal = self.strategy.get_signal(df, in_position=actual_in_position)
        except TypeError:
            signal = self.strategy.get_signal(df)

        if signal.signal == Signal.HOLD:
            return

        can_trade, _ = self.risk.can_trade(self.position_size_usd)
        if not can_trade:
            return

        if signal.signal in (Signal.BUY, Signal.BUY_MORE) and not actual_in_position:
            amount = self._calculate_amount(current_price)
            if amount <= 0 or self.position_size_usd > self.balance:
                return

            self.balance -= self.position_size_usd
            self.positions.open_position(
                token_id=self.symbol,
                side="BUY",
                entry_price=current_price,
                size=amount,
                stop_loss=current_price * (1 - settings.STOP_LOSS_PCT / 100),
                take_profit=current_price * (1 + settings.TAKE_PROFIT_PCT / 100),
                strategy=self.strategy_name,
            )
            self.risk.position_opened()
            self._record_paper_trade("BUY", current_price, amount, None, signal.reason)

        elif signal.signal == Signal.SELL and actual_in_position:
            pos = self.positions.positions.get(self.symbol)
            if pos:
                pnl = pos.unrealized_pnl(current_price)
                self.balance += (pos.size * current_price)
                self.positions.close_position(self.symbol, current_price)
                self.risk.position_closed(pnl)
                self._record_paper_trade("SELL", current_price, pos.size, pnl, signal.reason)

    def _record_paper_trade(self, side, price, size, pnl, reason):
        trade = {
            "side": side,
            "symbol": self.symbol,
            "price": round(price, 4),
            "size": round(size, 8),
            "pnl": round(pnl, 4) if pnl is not None else None,
            "strategy": self.strategy_name,
            "reason": reason,
            "balance_after": round(self.balance, 2),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "paper": True,
        }
        self.trades_log.append(trade)

        # Save to Firestore if uid available
        if self.uid:
            try:
                from services.firestore_service import save_paper_trade
                save_paper_trade(self.uid, trade)
            except Exception as e:
                logger.warning("Failed to save paper trade to Firestore: %s", e)

    def get_status(self):
        """Return current paper trading status."""
        return {
            "strategy": self.strategy_name,
            "symbol": self.symbol,
            "balance": round(self.balance, 2),
            "starting_balance": self.starting_balance,
            "pnl": round(self.balance - self.starting_balance, 2),
            "pnl_pct": round(((self.balance / self.starting_balance) - 1) * 100, 2),
            "cycles": self.cycle_count,
            "positions": self.positions.get_open_count(),
            "total_trades": len(self.trades_log),
            "running": self.running,
            "paper": True,
        }
