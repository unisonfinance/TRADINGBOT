"""Tests for trading strategies."""
import sys
import os
import unittest

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.base_strategy import Signal, TradeSignal
from strategies.macd_strategy import MACDStrategy
from strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from strategies.cvd_strategy import CVDStrategy


def _get_test_data(num_candles=500) -> pd.DataFrame:
    """Generate test OHLCV data."""
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


class TestMACDStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = MACDStrategy(fast=3, slow=15, signal=3)
        self.df = _get_test_data()

    def test_name(self):
        self.assertEqual(self.strategy.name, "MACD(3/15/3)")

    def test_generate_signals_adds_columns(self):
        result = self.strategy.generate_signals(self.df)
        self.assertIn("signal", result.columns)
        self.assertIn("macd_line", result.columns)
        self.assertIn("macd_signal", result.columns)
        self.assertIn("macd_histogram", result.columns)

    def test_generate_signals_produces_trades(self):
        result = self.strategy.generate_signals(self.df)
        signals = result["signal"]
        buy_count = sum(1 for s in signals if s == Signal.BUY)
        sell_count = sum(1 for s in signals if s == Signal.SELL)
        self.assertGreater(buy_count, 0, "Should have at least one BUY signal")
        self.assertGreater(sell_count, 0, "Should have at least one SELL signal")

    def test_get_signal_returns_trade_signal(self):
        signal = self.strategy.get_signal(self.df)
        self.assertIsInstance(signal, TradeSignal)
        self.assertIn(signal.signal, [Signal.BUY, Signal.SELL, Signal.HOLD])

    def test_validates_dataframe(self):
        bad_df = pd.DataFrame({"x": [1, 2, 3]})
        with self.assertRaises(ValueError):
            self.strategy.generate_signals(bad_df)


class TestRSIStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = RSIMeanReversionStrategy()
        self.df = _get_test_data()

    def test_name(self):
        self.assertEqual(self.strategy.name, "RSI_MeanRev(14)")

    def test_generate_signals_adds_rsi_and_vwap(self):
        result = self.strategy.generate_signals(self.df)
        self.assertIn("rsi", result.columns)
        self.assertIn("vwap", result.columns)
        self.assertIn("signal", result.columns)

    def test_get_signal(self):
        signal = self.strategy.get_signal(self.df)
        self.assertIsInstance(signal, TradeSignal)

    def test_rsi_bounds(self):
        result = self.strategy.generate_signals(self.df)
        rsi_values = result["rsi"].dropna()
        self.assertTrue((rsi_values >= 0).all())
        self.assertTrue((rsi_values <= 100).all())


class TestCVDStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = CVDStrategy(lookback=20, divergence_threshold=0.02)
        self.df = _get_test_data()

    def test_name(self):
        self.assertEqual(self.strategy.name, "CVD(20)")

    def test_generate_signals_adds_cvd(self):
        result = self.strategy.generate_signals(self.df)
        self.assertIn("cvd", result.columns)
        self.assertIn("divergence", result.columns)
        self.assertIn("signal", result.columns)

    def test_get_signal(self):
        signal = self.strategy.get_signal(self.df)
        self.assertIsInstance(signal, TradeSignal)


if __name__ == "__main__":
    unittest.main()
