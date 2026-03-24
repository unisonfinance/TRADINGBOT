"""
Abstract base class for all trading strategies.
Every strategy must implement generate_signals().
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

import pandas as pd


class Signal(Enum):
    """Trading signal types."""
    BUY      = "BUY"
    BUY_MORE = "BUY_MORE"   # scale-in: add to existing position if balance allows
    SELL     = "SELL"
    HOLD     = "HOLD"


@dataclass
class TradeSignal:
    """A concrete trade signal emitted by a strategy."""
    signal: Signal
    price: float
    confidence: float  # 0.0 to 1.0
    reason: str
    stop_loss: float = 0.0
    take_profit: float = 0.0


class BaseStrategy(ABC):
    """
    Abstract base strategy. All strategies inherit from this.
    
    Subclasses must implement:
        - name: str property
        - generate_signals(df) -> df with 'signal' column
        - get_signal(df) -> TradeSignal for the latest bar
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable strategy name."""
        ...

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate signals for an entire DataFrame (used in backtesting).
        Must add a 'signal' column with values from Signal enum.
        
        Args:
            df: OHLCV DataFrame with columns: timestamp, open, high, low, close, volume
        Returns:
            Same DataFrame with added indicator columns and 'signal' column
        """
        ...

    @abstractmethod
    def get_signal(self, df: pd.DataFrame) -> TradeSignal:
        """
        Get the current trading signal from the latest data (used in live trading).
        
        Args:
            df: Recent OHLCV DataFrame (last N candles)
        Returns:
            TradeSignal for the most recent bar
        """
        ...

    def validate_dataframe(self, df: pd.DataFrame) -> bool:
        """Check that the DataFrame has required OHLCV columns."""
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        return required.issubset(set(df.columns)) and len(df) > 0
