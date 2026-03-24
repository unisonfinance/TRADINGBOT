"""
Incubation Scaler — manages the $1 → $5 → $10 → $50 → $100 progression.
Only scales up after meeting win rate and trade count requirements.
"""
import logging
from datetime import datetime, timedelta

from config import settings
from data.storage import DataStorage

logger = logging.getLogger(__name__)


class IncubationScaler:
    """
    Manages position size scaling during incubation.
    
    Rules:
    - Start at $1
    - Must hit minimum trades AND minimum win rate at each level
    - Must wait minimum days at each level
    - Only then scale to next level: $1 → $5 → $10 → $50 → $100
    - If performance drops below thresholds, scale DOWN
    """

    def __init__(
        self,
        strategy: str,
        account: str,
        sizes: list[float] = None,
        min_trades: int = None,
        min_winrate: float = None,
        min_days: int = None,
    ):
        self.strategy = strategy
        self.account = account
        self.sizes = sizes or settings.INCUBATION_SIZES
        self.min_trades = min_trades or settings.INCUBATION_MIN_TRADES
        self.min_winrate = min_winrate or settings.INCUBATION_MIN_WINRATE
        self.min_days = min_days or settings.INCUBATION_PERIOD_DAYS

        self.current_level = 0  # Index into self.sizes
        self.level_start_time = datetime.utcnow()
        self.storage = DataStorage()

    @property
    def current_size(self) -> float:
        """Current position size based on incubation level."""
        return self.sizes[self.current_level]

    @property
    def level_name(self) -> str:
        return f"Level {self.current_level + 1} (${self.current_size})"

    def evaluate(self) -> dict:
        """
        Evaluate current performance and determine if scaling is appropriate.
        
        Returns:
            Dict with evaluation results and recommendation
        """
        trades_df = self.storage.get_trades(
            strategy=self.strategy, account=self.account
        )

        if trades_df.empty:
            return {
                "level": self.level_name,
                "size": self.current_size,
                "action": "HOLD",
                "reason": "No trades yet",
                "trades": 0,
                "win_rate": 0,
                "days_at_level": 0,
            }

        total_trades = len(trades_df)
        # Trades with positive PnL
        if "pnl" in trades_df.columns:
            winning = len(trades_df[trades_df["pnl"] > 0])
        else:
            winning = 0
        win_rate = winning / total_trades if total_trades > 0 else 0

        days_elapsed = (datetime.utcnow() - self.level_start_time).days

        # Check scale-up conditions
        can_scale_up = (
            total_trades >= self.min_trades
            and win_rate >= self.min_winrate
            and days_elapsed >= self.min_days
            and self.current_level < len(self.sizes) - 1
        )

        # Check if performance dropped (scale down)
        should_scale_down = (
            total_trades >= self.min_trades
            and win_rate < self.min_winrate * 0.8  # 80% of min threshold
            and self.current_level > 0
        )

        if can_scale_up:
            action = "SCALE_UP"
            reason = (
                f"Passed: {total_trades} trades, {win_rate:.1%} WR, "
                f"{days_elapsed} days. Ready for ${self.sizes[self.current_level + 1]}"
            )
        elif should_scale_down:
            action = "SCALE_DOWN"
            reason = (
                f"Performance dropped: {win_rate:.1%} WR < "
                f"{self.min_winrate * 0.8:.1%} threshold"
            )
        else:
            action = "HOLD"
            remaining_trades = max(0, self.min_trades - total_trades)
            remaining_days = max(0, self.min_days - days_elapsed)
            reason = (
                f"Need {remaining_trades} more trades, "
                f"{remaining_days} more days, "
                f"WR={win_rate:.1%} (need {self.min_winrate:.1%})"
            )

        return {
            "level": self.level_name,
            "size": self.current_size,
            "action": action,
            "reason": reason,
            "trades": total_trades,
            "win_rate": win_rate,
            "days_at_level": days_elapsed,
        }

    def apply_recommendation(self) -> float:
        """
        Evaluate and apply scaling recommendation.
        Returns the new position size.
        """
        result = self.evaluate()

        if result["action"] == "SCALE_UP":
            self.current_level += 1
            self.level_start_time = datetime.utcnow()
            logger.info(
                "SCALE UP: %s → $%.2f (%s)",
                self.strategy, self.current_size, result["reason"],
            )
        elif result["action"] == "SCALE_DOWN":
            self.current_level -= 1
            self.level_start_time = datetime.utcnow()
            logger.warning(
                "SCALE DOWN: %s → $%.2f (%s)",
                self.strategy, self.current_size, result["reason"],
            )
        else:
            logger.info("HOLD at %s: %s", self.level_name, result["reason"])

        return self.current_size
