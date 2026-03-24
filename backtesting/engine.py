"""
Backtest engine — runs a strategy against historical OHLCV data
and simulates trades to produce performance metrics.
"""
import logging
from dataclasses import dataclass, field

import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal
from backtesting.metrics import calculate_metrics, BacktestMetrics
from config import settings

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """A single simulated trade."""
    entry_idx: int
    entry_price: float
    entry_time: str
    side: str  # "BUY" or "SELL"
    exit_idx: int = 0
    exit_price: float = 0.0
    exit_time: str = ""
    pnl: float = 0.0
    exit_reason: str = ""


@dataclass
class BacktestResult:
    """Complete backtest result."""
    strategy_name: str
    trades: list[dict] = field(default_factory=list)
    metrics: BacktestMetrics = None
    signals_df: pd.DataFrame = None


class BacktestEngine:
    """
    Simulates trading on historical data.
    
    Assumptions:
    - Limit orders fill at the signal price (no slippage for Polymarket limit orders)
    - Position size is fixed per trade
    - Only one position open at a time
    """

    def __init__(
        self,
        position_size: float = None,
        stop_loss_pct: float = None,
        take_profit_pct: float = None,
    ):
        self.position_size = position_size or settings.DEFAULT_POSITION_SIZE
        self.stop_loss_pct = stop_loss_pct or settings.STOP_LOSS_PCT
        self.take_profit_pct = take_profit_pct or settings.TAKE_PROFIT_PCT

    def run(self, strategy: BaseStrategy, df: pd.DataFrame) -> BacktestResult:
        """
        Run backtest of a strategy on OHLCV data.
        
        Args:
            strategy: A BaseStrategy subclass instance
            df: OHLCV DataFrame
        Returns:
            BacktestResult with trades and metrics
        """
        logger.info("Starting backtest: %s on %d candles", strategy.name, len(df))

        # Generate signals for all bars
        signals_df = strategy.generate_signals(df)

        trades = []
        open_trade: BacktestTrade = None

        for i in range(len(signals_df)):
            row = signals_df.iloc[i]
            signal = row["signal"]
            price = row["close"]
            timestamp = str(row["timestamp"])

            # Check stop-loss / take-profit on open trade
            if open_trade is not None:
                if open_trade.side == "BUY":
                    # Stop-loss
                    sl_price = open_trade.entry_price * (1 - self.stop_loss_pct / 100)
                    if row["low"] <= sl_price:
                        pnl = (sl_price - open_trade.entry_price) * self.position_size
                        open_trade.exit_idx = i
                        open_trade.exit_price = sl_price
                        open_trade.exit_time = timestamp
                        open_trade.pnl = pnl
                        open_trade.exit_reason = "stop_loss"
                        trades.append(open_trade)
                        open_trade = None
                        continue

                    # Take-profit
                    tp_price = open_trade.entry_price * (1 + self.take_profit_pct / 100)
                    if row["high"] >= tp_price:
                        pnl = (tp_price - open_trade.entry_price) * self.position_size
                        open_trade.exit_idx = i
                        open_trade.exit_price = tp_price
                        open_trade.exit_time = timestamp
                        open_trade.pnl = pnl
                        open_trade.exit_reason = "take_profit"
                        trades.append(open_trade)
                        open_trade = None
                        continue

                elif open_trade.side == "SELL":
                    sl_price = open_trade.entry_price * (1 + self.stop_loss_pct / 100)
                    if row["high"] >= sl_price:
                        pnl = (open_trade.entry_price - sl_price) * self.position_size
                        open_trade.exit_idx = i
                        open_trade.exit_price = sl_price
                        open_trade.exit_time = timestamp
                        open_trade.pnl = pnl
                        open_trade.exit_reason = "stop_loss"
                        trades.append(open_trade)
                        open_trade = None
                        continue

                    tp_price = open_trade.entry_price * (1 - self.take_profit_pct / 100)
                    if row["low"] <= tp_price:
                        pnl = (open_trade.entry_price - tp_price) * self.position_size
                        open_trade.exit_idx = i
                        open_trade.exit_price = tp_price
                        open_trade.exit_time = timestamp
                        open_trade.pnl = pnl
                        open_trade.exit_reason = "take_profit"
                        trades.append(open_trade)
                        open_trade = None
                        continue

            # Process signals
            if signal == Signal.BUY and open_trade is None:
                open_trade = BacktestTrade(
                    entry_idx=i,
                    entry_price=price,
                    entry_time=timestamp,
                    side="BUY",
                )
            elif signal == Signal.SELL:
                if open_trade is not None and open_trade.side == "BUY":
                    # Close long position
                    pnl = (price - open_trade.entry_price) * self.position_size
                    open_trade.exit_idx = i
                    open_trade.exit_price = price
                    open_trade.exit_time = timestamp
                    open_trade.pnl = pnl
                    open_trade.exit_reason = "signal"
                    trades.append(open_trade)
                    open_trade = None
                elif open_trade is None:
                    # Open short position
                    open_trade = BacktestTrade(
                        entry_idx=i,
                        entry_price=price,
                        entry_time=timestamp,
                        side="SELL",
                    )

        # Close any remaining open trade at last price
        if open_trade is not None:
            last = signals_df.iloc[-1]
            if open_trade.side == "BUY":
                pnl = (last["close"] - open_trade.entry_price) * self.position_size
            else:
                pnl = (open_trade.entry_price - last["close"]) * self.position_size
            open_trade.exit_idx = len(signals_df) - 1
            open_trade.exit_price = last["close"]
            open_trade.exit_time = str(last["timestamp"])
            open_trade.pnl = pnl
            open_trade.exit_reason = "end_of_data"
            trades.append(open_trade)

        # Convert to dicts for metrics calculation
        trade_dicts = [
            {
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "side": t.side,
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "exit_reason": t.exit_reason,
            }
            for t in trades
        ]

        metrics = calculate_metrics(trade_dicts)

        logger.info(
            "Backtest complete: %s — %d trades, %.1f%% win rate, PF=%.2f",
            strategy.name, metrics.total_trades, metrics.win_rate * 100,
            metrics.profit_factor,
        )

        return BacktestResult(
            strategy_name=strategy.name,
            trades=trade_dicts,
            metrics=metrics,
            signals_df=signals_df,
        )
