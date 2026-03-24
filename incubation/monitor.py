"""
Bot Monitor — periodic status reports on running bots.
Shows positions, P&L, risk status, and incubation progress.
"""
import logging
import time
from datetime import datetime

from config import settings
from data.storage import DataStorage
from backtesting.metrics import calculate_metrics

logger = logging.getLogger(__name__)


class BotMonitor:
    """
    Monitors running bot performance and generates status reports.
    Run in a separate terminal: python deploy/run_monitor.py
    """

    def __init__(self):
        self.storage = DataStorage()
        self.start_time = datetime.utcnow()

    def get_strategy_report(self, strategy: str = None, account: str = None) -> str:
        """Generate a performance report for a strategy/account."""
        trades_df = self.storage.get_trades(strategy=strategy, account=account)

        if trades_df.empty:
            return f"No trades found for strategy={strategy}, account={account}"

        # Calculate metrics from trade data
        trade_list = []
        for _, row in trades_df.iterrows():
            pnl = row.get("pnl", 0)
            if isinstance(pnl, str):
                try:
                    pnl = float(pnl)
                except (ValueError, TypeError):
                    pnl = 0
            trade_list.append({
                "pnl": pnl,
                "entry_price": row.get("price", 0),
                "exit_price": 0,
            })

        metrics = calculate_metrics(trade_list)
        status = "PASS" if metrics.passes_benchmarks() else "INCUBATING"

        report = (
            f"\n{'─'*50}\n"
            f"  Strategy: {strategy or 'ALL'} | Account: {account or 'ALL'}\n"
            f"  Status: {status}\n"
            f"{'─'*50}\n"
            f"  Trades: {metrics.total_trades} | "
            f"Win Rate: {metrics.win_rate:.1%} | "
            f"Profit Factor: {metrics.profit_factor:.2f}\n"
            f"  Total P&L: ${metrics.total_pnl:.2f} | "
            f"Max Drawdown: {metrics.max_drawdown_pct:.1%}\n"
            f"  Sharpe: {metrics.sharpe_ratio:.2f} | "
            f"Avg Trade: ${metrics.avg_trade_pnl:.4f}\n"
            f"{'─'*50}\n"
        )
        return report

    def get_full_report(self) -> str:
        """Generate a full report across all strategies and accounts."""
        trades_df = self.storage.get_trades()
        uptime = datetime.utcnow() - self.start_time

        header = (
            f"\n{'='*60}\n"
            f"  POLYMARKET BOT MONITOR\n"
            f"  Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"  Uptime: {uptime}\n"
            f"  Total trades in DB: {len(trades_df)}\n"
            f"{'='*60}\n"
        )

        if trades_df.empty:
            return header + "  No trades recorded yet.\n"

        report = header

        # Per-strategy breakdown
        if "strategy" in trades_df.columns:
            strategies = trades_df["strategy"].unique()
            for strat in strategies:
                report += self.get_strategy_report(strategy=strat)

        # Per-account breakdown
        if "account" in trades_df.columns:
            accounts = trades_df["account"].unique()
            if len(accounts) > 1:
                report += "\n  --- By Account ---\n"
                for acct in accounts:
                    report += self.get_strategy_report(account=acct)

        return report

    def run(self, interval: int = None):
        """
        Run monitor loop — prints status report every N seconds.
        
        Args:
            interval: Seconds between reports (default from settings)
        """
        interval = interval or settings.MONITOR_POLL_INTERVAL
        logger.info("Monitor started. Reporting every %d seconds.", interval)

        try:
            while True:
                report = self.get_full_report()
                print(report)
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Monitor stopped by user.")
