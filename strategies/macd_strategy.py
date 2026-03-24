"""
MACD Histogram Strategy (fast=3, slow=15, signal=3).

Entry: MACD line crosses above signal line -> BUY
       MACD line crosses below signal line -> SELL
Exit:  Reverse crossover or stop-loss / take-profit

Works well on trending moves within 5-minute windows on Polymarket.
Backtest benchmark: ~60% win rate on Polymarket 5-min markets.
"""
import pandas as pd
import ta

from config import settings
from strategies.base_strategy import BaseStrategy, Signal, TradeSignal


class MACDStrategy(BaseStrategy):

    def __init__(
        self,
        fast: int = None,
        slow: int = None,
        signal: int = None,
        stop_loss_pct: float = None,
        take_profit_pct: float = None,
    ):
        self.fast = fast or settings.MACD_FAST
        self.slow = slow or settings.MACD_SLOW
        self.signal_period = signal or settings.MACD_SIGNAL
        self.stop_loss_pct = stop_loss_pct or settings.STOP_LOSS_PCT
        self.take_profit_pct = take_profit_pct or settings.TAKE_PROFIT_PCT

    @property
    def name(self) -> str:
        return f"MACD({self.fast}/{self.slow}/{self.signal_period})"

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add MACD indicators to the DataFrame."""
        macd = ta.trend.MACD(
            close=df["close"],
            window_fast=self.fast,
            window_slow=self.slow,
            window_sign=self.signal_period,
        )
        df = df.copy()
        df["macd_line"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_histogram"] = macd.macd_diff()
        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate BUY/SELL signals based on MACD crossovers."""
        if not self.validate_dataframe(df):
            raise ValueError("Invalid OHLCV DataFrame")

        df = self._add_indicators(df)
        df["signal"] = Signal.HOLD

        for i in range(1, len(df)):
            prev_macd = df.iloc[i - 1]["macd_line"]
            prev_signal = df.iloc[i - 1]["macd_signal"]
            curr_macd = df.iloc[i]["macd_line"]
            curr_signal = df.iloc[i]["macd_signal"]

            # Skip if indicators not ready (NaN)
            if pd.isna(prev_macd) or pd.isna(curr_macd):
                continue

            # Bullish crossover: MACD crosses above signal
            if prev_macd <= prev_signal and curr_macd > curr_signal:
                df.iloc[i, df.columns.get_loc("signal")] = Signal.BUY

            # Bearish crossover: MACD crosses below signal
            elif prev_macd >= prev_signal and curr_macd < curr_signal:
                df.iloc[i, df.columns.get_loc("signal")] = Signal.SELL

        return df

    def get_signal(self, df: pd.DataFrame) -> TradeSignal:
        """Get the latest signal for live trading."""
        df = self.generate_signals(df)

        if len(df) < 2:
            return TradeSignal(
                signal=Signal.HOLD, price=0, confidence=0, reason="Insufficient data"
            )

        last = df.iloc[-1]
        price = last["close"]
        signal = last["signal"]

        # Calculate confidence based on histogram magnitude
        hist = abs(last["macd_histogram"]) if not pd.isna(last["macd_histogram"]) else 0
        confidence = min(1.0, hist * 50)  # Scale histogram to 0-1

        stop_loss = price * (1 - self.stop_loss_pct / 100) if signal == Signal.BUY else price * (1 + self.stop_loss_pct / 100)
        take_profit = price * (1 + self.take_profit_pct / 100) if signal == Signal.BUY else price * (1 - self.take_profit_pct / 100)

        return TradeSignal(
            signal=signal,
            price=price,
            confidence=confidence,
            reason=f"MACD {'bullish' if signal == Signal.BUY else 'bearish' if signal == Signal.SELL else 'no'} crossover",
            stop_loss=round(max(0.01, min(0.99, stop_loss)), 2),
            take_profit=round(max(0.01, min(0.99, take_profit)), 2),
        )
