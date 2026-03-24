"""Tests for the risk manager."""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.risk_manager import RiskManager


class TestRiskManager(unittest.TestCase):
    def setUp(self):
        self.risk = RiskManager(
            max_position_size=100,
            max_daily_loss=50,
            max_drawdown_pct=20,
            max_open_positions=5,
        )
        self.risk.update_equity(1000)

    def test_allows_normal_trade(self):
        allowed, reason = self.risk.can_trade(10)
        self.assertTrue(allowed)
        self.assertEqual(reason, "OK")

    def test_blocks_oversized_trade(self):
        allowed, reason = self.risk.can_trade(200)
        self.assertFalse(allowed)
        self.assertIn("exceeds max", reason)

    def test_blocks_max_positions(self):
        for _ in range(5):
            self.risk.position_opened()
        allowed, reason = self.risk.can_trade(10)
        self.assertFalse(allowed)
        self.assertIn("positions", reason)

    def test_blocks_daily_loss(self):
        # Simulate losing trades
        self.risk.record_trade_pnl(-30)
        self.risk.record_trade_pnl(-25)
        allowed, reason = self.risk.can_trade(10)
        self.assertFalse(allowed)
        self.assertIn("Daily loss", reason)

    def test_blocks_drawdown(self):
        self.risk.update_equity(1000)
        # Simulate drawdown
        self.risk.current_equity = 750  # 25% drawdown
        allowed, reason = self.risk.can_trade(10)
        self.assertFalse(allowed)
        self.assertIn("drawdown", reason)

    def test_position_tracking(self):
        self.risk.position_opened()
        self.assertEqual(self.risk.open_position_count, 1)
        self.risk.position_closed(pnl=5)
        self.assertEqual(self.risk.open_position_count, 0)
        self.assertEqual(self.risk.daily_pnl, 5)

    def test_status_report(self):
        self.risk.record_trade_pnl(-10)
        status = self.risk.status()
        self.assertEqual(status["daily_pnl"], -10)
        self.assertEqual(status["daily_loss_limit"], 50)
        self.assertIn("drawdown_pct", status)


if __name__ == "__main__":
    unittest.main()
