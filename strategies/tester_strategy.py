"""
Tester Strategy — fires BUY/SELL every single bar.

Purpose: Test that the bot places real orders on the exchange.
Pattern: Alternates BUY → SELL → BUY → SELL on every 1-minute candle.
Size:    Designed for minimum position size ($0.10 or exchange minimum).
"""
import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal, TradeSignal


class TesterStrategy(BaseStrategy):
    """
    Always-trigger strategy for order-placement testing.
    Alternates BUY/SELL on every bar so we can verify the full
    order lifecycle (place → fill → close) with tiny amounts.
    """

    def __init__(self, **kwargs):
        # Accept and ignore any extra kwargs so it plays nicely with strategy_kwargs
        pass

    @property
    def name(self) -> str:
        return "Tester (always-trade)"

    # ── Backtesting ───────────────────────────────────────────────────
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.validate_dataframe(df):
            raise ValueError("Invalid OHLCV DataFrame")

        df = df.copy()
        # Alternate BUY on even rows, SELL on odd rows
        df["signal"] = df.index.to_series().apply(
            lambda i: Signal.BUY if i % 2 == 0 else Signal.SELL
        )
        return df

    # ── Live trading ──────────────────────────────────────────────────
    def get_signal(self, df: pd.DataFrame, in_position: bool = False) -> TradeSignal:
        if len(df) < 1:
            return TradeSignal(
                signal=Signal.HOLD, price=0, confidence=0,
                reason="No data",
            )

        price = float(df.iloc[-1]["close"])
        bar_index = len(df)

        # If we're in a position → SELL to close it
        # If we're NOT in a position → BUY to open one
        if in_position:
            return TradeSignal(
                signal=Signal.SELL,
                price=price,
                confidence=1.0,
                reason=f"Tester: auto-SELL bar #{bar_index} (close position)",
                stop_loss=0.0,
                take_profit=0.0,
            )
        else:
            return TradeSignal(
                signal=Signal.BUY,
                price=price,
                confidence=1.0,
                reason=f"Tester: auto-BUY bar #{bar_index} (open position)",
                stop_loss=0.0,
                take_profit=0.0,
            )
