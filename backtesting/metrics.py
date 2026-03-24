"""
Performance metrics for backtesting and live trading evaluation.

Key metrics:
- Win rate (must be > 55%)
- Profit factor (must be > 1.5)
- Max drawdown (must be < 20%)
- Sharpe ratio
- Total trades (must be >= 100 for statistical significance)
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import settings


@dataclass
class BacktestMetrics:
    """Complete metrics report for a backtest or live performance."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    max_drawdown_pct: float
    sharpe_ratio: float
    avg_trade_pnl: float
    largest_win: float
    largest_loss: float
    consecutive_wins: int
    consecutive_losses: int

    def passes_benchmarks(self) -> bool:
        """Check if the strategy passes minimum benchmarks.
        Reads live values from settings so user edits take effect immediately.
        """
        from importlib import reload
        from config import settings as _s
        reload(_s)
        return (
            self.win_rate >= _s.BACKTEST_MIN_WINRATE
            and self.profit_factor >= _s.BACKTEST_MIN_PROFIT_FACTOR
            and self.max_drawdown_pct <= _s.BACKTEST_MAX_DRAWDOWN
            and self.total_trades >= _s.BACKTEST_MIN_TRADES
        )

    def summary(self) -> str:
        """Human-readable summary."""
        status = "PASS" if self.passes_benchmarks() else "FAIL"
        return (
            f"\n{'='*50}\n"
            f"  BACKTEST RESULTS [{status}]\n"
            f"{'='*50}\n"
            f"  Total trades:      {self.total_trades}\n"
            f"  Win rate:          {self.win_rate:.1%} {'✓' if self.win_rate >= settings.BACKTEST_MIN_WINRATE else '✗'}\n"
            f"  Profit factor:     {self.profit_factor:.2f} {'✓' if self.profit_factor >= settings.BACKTEST_MIN_PROFIT_FACTOR else '✗'}\n"
            f"  Max drawdown:      {self.max_drawdown_pct:.1%} {'✓' if self.max_drawdown_pct <= settings.BACKTEST_MAX_DRAWDOWN else '✗'}\n"
            f"  Sharpe ratio:      {self.sharpe_ratio:.2f}\n"
            f"  Total P&L:         ${self.total_pnl:.2f}\n"
            f"  Avg trade P&L:     ${self.avg_trade_pnl:.4f}\n"
            f"  Avg win:           ${self.avg_win:.4f}\n"
            f"  Avg loss:          ${self.avg_loss:.4f}\n"
            f"  Largest win:       ${self.largest_win:.4f}\n"
            f"  Largest loss:      ${self.largest_loss:.4f}\n"
            f"  Max consec. wins:  {self.consecutive_wins}\n"
            f"  Max consec. losses:{self.consecutive_losses}\n"
            f"  Min trades (100):  {'✓' if self.total_trades >= settings.BACKTEST_MIN_TRADES else '✗'}\n"
            f"{'='*50}\n"
        )


def calculate_metrics(trades: list[dict]) -> BacktestMetrics:
    """
    Calculate performance metrics from a list of completed trades.
    
    Each trade dict should have:
        - pnl: float (profit/loss of the trade)
        - entry_price: float
        - exit_price: float
    """
    if not trades:
        return BacktestMetrics(
            total_trades=0, winning_trades=0, losing_trades=0,
            win_rate=0, profit_factor=0, total_pnl=0,
            avg_win=0, avg_loss=0, max_drawdown_pct=0,
            sharpe_ratio=0, avg_trade_pnl=0,
            largest_win=0, largest_loss=0,
            consecutive_wins=0, consecutive_losses=0,
        )

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total_trades = len(trades)
    winning_trades = len(wins)
    losing_trades = len(losses)
    win_rate = winning_trades / total_trades if total_trades > 0 else 0

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    total_pnl = sum(pnls)
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    avg_trade_pnl = np.mean(pnls) if pnls else 0

    largest_win = max(wins) if wins else 0
    largest_loss = min(losses) if losses else 0

    # Max drawdown
    equity_curve = np.cumsum(pnls)
    running_max = np.maximum.accumulate(equity_curve)
    drawdowns = (running_max - equity_curve)
    # Express as percentage of peak
    peak_values = np.where(running_max > 0, running_max, 1)
    drawdown_pcts = drawdowns / peak_values
    max_drawdown_pct = float(np.max(drawdown_pcts)) if len(drawdown_pcts) > 0 else 0

    # Sharpe ratio (annualized, assuming daily trades)
    if len(pnls) > 1 and np.std(pnls) > 0:
        sharpe_ratio = (np.mean(pnls) / np.std(pnls)) * np.sqrt(252)
    else:
        sharpe_ratio = 0

    # Consecutive wins/losses
    max_consec_wins = _max_consecutive(pnls, positive=True)
    max_consec_losses = _max_consecutive(pnls, positive=False)

    return BacktestMetrics(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        total_pnl=total_pnl,
        avg_win=avg_win,
        avg_loss=avg_loss,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        avg_trade_pnl=avg_trade_pnl,
        largest_win=largest_win,
        largest_loss=largest_loss,
        consecutive_wins=max_consec_wins,
        consecutive_losses=max_consec_losses,
    )


def _max_consecutive(pnls: list[float], positive: bool) -> int:
    """Count max consecutive wins (positive=True) or losses (positive=False)."""
    max_streak = 0
    current = 0
    for pnl in pnls:
        if (positive and pnl > 0) or (not positive and pnl <= 0):
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak
