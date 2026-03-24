"""Tests for the backtesting engine and metrics."""
import sys
import os
import unittest

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtesting.engine import BacktestEngine
from backtesting.metrics import calculate_metrics, BacktestMetrics
from strategies.macd_strategy import MACDStrategy
from strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from strategies.cvd_strategy import CVDStrategy


def _get_test_data(num_candles=1000) -> pd.DataFrame:
    """Generate test data."""
    np.random.seed(42)
    from datetime import datetime
    timestamps = pd.date_range(end=datetime.now(), periods=num_candles, freq="5min")
    price = 0.50
    rows = []
    for ts in timestamps:
        change = np.random.normal(0, 0.02)
        price = max(0.05, min(0.95, price + change))
        h = min(0.99, price + abs(np.random.normal(0, 0.01)))
        l = max(0.01, price - abs(np.random.normal(0, 0.01)))
        c = max(0.01, min(0.99, price + np.random.normal(0, 0.005)))
        v = abs(np.random.normal(1000, 500))
        rows.append({"timestamp": ts, "open": price, "high": h, "low": l, "close": c, "volume": v})
    return pd.DataFrame(rows)


class TestMetrics(unittest.TestCase):
    def test_empty_trades(self):
        metrics = calculate_metrics([])
        self.assertEqual(metrics.total_trades, 0)
        self.assertEqual(metrics.win_rate, 0)

    def test_all_winners(self):
        trades = [{"pnl": 10, "entry_price": 0.5, "exit_price": 0.6}] * 10
        metrics = calculate_metrics(trades)
        self.assertEqual(metrics.win_rate, 1.0)
        self.assertEqual(metrics.winning_trades, 10)
        self.assertEqual(metrics.losing_trades, 0)

    def test_all_losers(self):
        trades = [{"pnl": -5, "entry_price": 0.5, "exit_price": 0.4}] * 10
        metrics = calculate_metrics(trades)
        self.assertEqual(metrics.win_rate, 0.0)
        self.assertEqual(metrics.losing_trades, 10)

    def test_mixed_trades(self):
        trades = [
            {"pnl": 10, "entry_price": 0.5, "exit_price": 0.6},
            {"pnl": -3, "entry_price": 0.5, "exit_price": 0.47},
            {"pnl": 5, "entry_price": 0.5, "exit_price": 0.55},
            {"pnl": -2, "entry_price": 0.5, "exit_price": 0.48},
            {"pnl": 8, "entry_price": 0.5, "exit_price": 0.58},
        ]
        metrics = calculate_metrics(trades)
        self.assertEqual(metrics.total_trades, 5)
        self.assertEqual(metrics.winning_trades, 3)
        self.assertEqual(metrics.losing_trades, 2)
        self.assertAlmostEqual(metrics.win_rate, 0.6)
        self.assertGreater(metrics.profit_factor, 1.0)

    def test_passes_benchmarks(self):
        # Create enough trades to pass all benchmark requirements
        # 90 wins + 30 losses = 120 trades, 75% WR, PF=6.0
        trades = [{"pnl": 2, "entry_price": 0.5, "exit_price": 0.52}] * 90
        trades += [{"pnl": -1, "entry_price": 0.5, "exit_price": 0.49}] * 30
        metrics = calculate_metrics(trades)
        self.assertTrue(metrics.passes_benchmarks())

    def test_fails_benchmarks_low_trades(self):
        trades = [{"pnl": 2, "entry_price": 0.5, "exit_price": 0.52}] * 5
        metrics = calculate_metrics(trades)
        self.assertFalse(metrics.passes_benchmarks())


class TestBacktestEngine(unittest.TestCase):
    def setUp(self):
        self.df = _get_test_data(1000)
        self.engine = BacktestEngine(position_size=1.0)

    def test_macd_backtest_produces_trades(self):
        strategy = MACDStrategy(fast=3, slow=15, signal=3)
        result = self.engine.run(strategy, self.df)
        self.assertGreater(len(result.trades), 0, "Backtest should produce trades")
        self.assertIsNotNone(result.metrics)
        self.assertEqual(result.strategy_name, "MACD(3/15/3)")

    def test_rsi_backtest_produces_trades(self):
        strategy = RSIMeanReversionStrategy()
        result = self.engine.run(strategy, self.df)
        self.assertGreater(len(result.trades), 0)
        self.assertIsNotNone(result.metrics)

    def test_cvd_backtest_produces_trades(self):
        strategy = CVDStrategy(lookback=20, divergence_threshold=0.02)
        result = self.engine.run(strategy, self.df)
        self.assertIsNotNone(result.metrics)

    def test_backtest_result_has_signals_df(self):
        strategy = MACDStrategy()
        result = self.engine.run(strategy, self.df)
        self.assertIsNotNone(result.signals_df)
        self.assertIn("signal", result.signals_df.columns)

    def test_all_trades_have_pnl(self):
        strategy = MACDStrategy()
        result = self.engine.run(strategy, self.df)
        for trade in result.trades:
            self.assertIn("pnl", trade)
            self.assertIsInstance(trade["pnl"], float)


if __name__ == "__main__":
    unittest.main()
