"""
Position Tracker — tracks open positions, calculates unrealized P&L,
and manages stop-loss / take-profit exits.
"""
import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """An open trading position."""
    token_id: str
    side: str  # "BUY" (long) or "SELL" (short)
    entry_price: float
    size: float
    stop_loss: float
    take_profit: float
    entry_time: str
    strategy: str
    trade_id: int = 0  # DB trade ID for logging

    def unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized P&L at current price."""
        if self.side == "BUY":
            return (current_price - self.entry_price) * self.size
        else:
            return (self.entry_price - current_price) * self.size

    def should_stop_loss(self, current_price: float) -> bool:
        """Check if stop-loss has been hit."""
        if self.side == "BUY":
            return current_price <= self.stop_loss
        else:
            return current_price >= self.stop_loss

    def should_take_profit(self, current_price: float) -> bool:
        """Check if take-profit has been hit."""
        if self.side == "BUY":
            return current_price >= self.take_profit
        else:
            return current_price <= self.take_profit


class PositionTracker:
    """Manages all open positions."""

    def __init__(self):
        self.positions: dict[str, Position] = {}  # token_id -> Position
        self.closed_pnl: float = 0.0
        self.total_trades: int = 0

    def open_position(
        self,
        token_id: str,
        side: str,
        entry_price: float,
        size: float,
        stop_loss: float,
        take_profit: float,
        strategy: str,
        trade_id: int = 0,
    ) -> Position:
        """Open a new position."""
        if token_id in self.positions:
            logger.warning("Position already exists for %s — closing first", token_id[:8])
            self.close_position(token_id, entry_price)

        pos = Position(
            token_id=token_id,
            side=side,
            entry_price=entry_price,
            size=size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=datetime.utcnow().isoformat(),
            strategy=strategy,
            trade_id=trade_id,
        )
        self.positions[token_id] = pos
        logger.info(
            "Opened %s position: %s @ $%.4f, SL=$%.4f, TP=$%.4f",
            side, token_id[:8], entry_price, stop_loss, take_profit,
        )
        return pos

    def add_to_position(
        self,
        token_id: str,
        new_price: float,
        new_size: float,
    ) -> "Position":
        """
        Add to an existing position (scale-in) and recalculate the
        weighted-average entry price.

        Cost basis = (old_size * old_entry + new_size * new_price)
                     / (old_size + new_size)

        If no position exists yet, opens a fresh one (no SL/TP set here —
        caller must update them separately if needed).
        """
        if token_id not in self.positions:
            logger.warning(
                "add_to_position called but no open position for %s — "
                "opening fresh position instead", token_id[:8]
            )
            return self.open_position(
                token_id=token_id,
                side="BUY",
                entry_price=new_price,
                size=new_size,
                stop_loss=0.0,
                take_profit=0.0,
                strategy="",
            )

        pos = self.positions[token_id]
        total_size  = pos.size + new_size
        avg_price   = (pos.size * pos.entry_price + new_size * new_price) / total_size
        pos.size        = total_size
        pos.entry_price = avg_price
        logger.info(
            "Scale-in: %s total_size=%.6f  new_avg_entry=$%.4f",
            token_id[:8], total_size, avg_price,
        )
        return pos

    def close_position(self, token_id: str, exit_price: float) -> float:
        """
        Close a position and return realized P&L.
        
        Returns:
            Realized P&L in USD
        """
        if token_id not in self.positions:
            logger.warning("No open position for %s", token_id[:8])
            return 0.0

        pos = self.positions.pop(token_id)
        pnl = pos.unrealized_pnl(exit_price)
        self.closed_pnl += pnl
        self.total_trades += 1

        logger.info(
            "Closed %s position: %s @ $%.4f -> $%.4f, P&L=$%.4f",
            pos.side, token_id[:8], pos.entry_price, exit_price, pnl,
        )
        return pnl

    def check_exits(self, prices: dict[str, float]) -> list[tuple[str, str, float]]:
        """
        Check all positions for stop-loss / take-profit triggers.
        
        Args:
            prices: dict of token_id -> current_price
        Returns:
            List of (token_id, reason, exit_price) for positions that should be closed
        """
        exits = []
        for token_id, pos in self.positions.items():
            current = prices.get(token_id)
            if current is None:
                continue

            if pos.should_stop_loss(current):
                exits.append((token_id, "stop_loss", pos.stop_loss))
            elif pos.should_take_profit(current):
                exits.append((token_id, "take_profit", pos.take_profit))

        return exits

    def get_open_count(self) -> int:
        return len(self.positions)

    def total_unrealized_pnl(self, prices: dict[str, float]) -> float:
        """Total unrealized P&L across all open positions."""
        total = 0.0
        for token_id, pos in self.positions.items():
            current = prices.get(token_id)
            if current is not None:
                total += pos.unrealized_pnl(current)
        return total

    def status(self, prices: dict[str, float] = None) -> list[dict]:
        """Summary of all open positions."""
        prices = prices or {}
        result = []
        for tid, pos in self.positions.items():
            current = prices.get(tid, pos.entry_price)
            result.append({
                "token": tid[:8],
                "side": pos.side,
                "entry": pos.entry_price,
                "current": current,
                "unrealized_pnl": pos.unrealized_pnl(current),
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit,
                "strategy": pos.strategy,
            })
        return result
