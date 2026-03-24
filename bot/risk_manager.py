"""
Risk Manager — enforces position limits, daily loss caps, and drawdown controls.
The bot will NOT place orders if risk limits are breached.
"""
import logging
from datetime import datetime, date

from config import settings

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Enforces risk controls before any trade is placed.
    
    Controls:
    - Max position size per trade
    - Max total open positions
    - Daily loss limit
    - Max drawdown percentage
    """

    def __init__(
        self,
        max_position_size: float = None,
        max_daily_loss: float = None,
        max_drawdown_pct: float = None,
        max_open_positions: int = None,
    ):
        self.max_position_size = max_position_size or settings.MAX_POSITION_SIZE
        self.max_daily_loss = max_daily_loss or settings.MAX_DAILY_LOSS
        self.max_drawdown_pct = max_drawdown_pct or settings.MAX_DRAWDOWN_PCT
        self.max_open_positions = max_open_positions or settings.MAX_OPEN_POSITIONS

        # Tracking state
        self.daily_pnl: float = 0.0
        self.daily_date: date = date.today()
        self.peak_equity: float = 0.0
        self.current_equity: float = 0.0
        self.open_position_count: int = 0

    def _reset_daily_if_needed(self):
        """Reset daily P&L tracker at the start of a new day."""
        today = date.today()
        if today != self.daily_date:
            logger.info(
                "New day — resetting daily P&L (yesterday: $%.2f)", self.daily_pnl
            )
            self.daily_pnl = 0.0
            self.daily_date = today

    def update_equity(self, equity: float):
        """Update current equity and peak."""
        self.current_equity = equity
        if equity > self.peak_equity:
            self.peak_equity = equity

    def record_trade_pnl(self, pnl: float):
        """Record a completed trade's P&L."""
        self._reset_daily_if_needed()
        self.daily_pnl += pnl
        self.current_equity += pnl
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity

    def can_trade(self, size: float) -> tuple[bool, str]:
        """
        Check if a new trade is allowed under current risk limits.
        
        Returns:
            (allowed: bool, reason: str)
        """
        self._reset_daily_if_needed()

        # Check position size
        if size > self.max_position_size:
            return False, f"Size ${size} exceeds max ${self.max_position_size}"

        # Check open positions
        if self.open_position_count >= self.max_open_positions:
            return False, f"Max open positions ({self.max_open_positions}) reached"

        # Check daily loss
        if self.daily_pnl <= -self.max_daily_loss:
            return False, f"Daily loss limit reached (${self.daily_pnl:.2f} <= -${self.max_daily_loss})"

        # Check drawdown
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - self.current_equity) / self.peak_equity
            if drawdown >= self.max_drawdown_pct / 100:
                return False, f"Max drawdown reached ({drawdown:.1%} >= {self.max_drawdown_pct}%)"

        return True, "OK"

    def position_opened(self):
        """Called when a new position is opened."""
        self.open_position_count += 1

    def position_closed(self, pnl: float):
        """Called when a position is closed."""
        self.open_position_count = max(0, self.open_position_count - 1)
        self.record_trade_pnl(pnl)

    def status(self) -> dict:
        """Current risk status."""
        drawdown = 0.0
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - self.current_equity) / self.peak_equity
        return {
            "daily_pnl": self.daily_pnl,
            "daily_loss_limit": self.max_daily_loss,
            "daily_remaining": self.max_daily_loss + self.daily_pnl,
            "drawdown_pct": drawdown,
            "max_drawdown_pct": self.max_drawdown_pct,
            "open_positions": self.open_position_count,
            "max_positions": self.max_open_positions,
        }
