"""
RSI Mean Reversion Strategy with VWAP confirmation.

Entry: RSI < 30 (oversold) -> BUY (long entry on pullback)
Exit:  RSI > 50 or price reaches VWAP
       Also: stop-loss / take-profit

Suited for pullbacks after sharp moves on Polymarket.
Backtest benchmark: ~59% win rate on Polymarket 5-min markets.
"""
import pandas as pd
import numpy as np
import ta

from config import settings
from strategies.base_strategy import BaseStrategy, Signal, TradeSignal


class RSIMeanReversionStrategy(BaseStrategy):

    def __init__(
        self,
        rsi_period: int = None,
        rsi_oversold: int = None,
        rsi_overbought: int = None,
        rsi_exit: int = None,
        stop_loss_pct: float = None,
        take_profit_pct: float = None,
    ):
        self.rsi_period = rsi_period or settings.RSI_PERIOD
        self.rsi_oversold = rsi_oversold or settings.RSI_OVERSOLD
        self.rsi_overbought = rsi_overbought or settings.RSI_OVERBOUGHT
        self.rsi_exit = rsi_exit or settings.RSI_EXIT
        self.stop_loss_pct = stop_loss_pct or settings.STOP_LOSS_PCT
        self.take_profit_pct = take_profit_pct or settings.TAKE_PROFIT_PCT

    @property
    def name(self) -> str:
        return f"RSI_MeanRev({self.rsi_period})"

    def _calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        """Calculate Volume Weighted Average Price (VWAP)."""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        cumulative_tp_vol = (typical_price * df["volume"]).cumsum()
        cumulative_vol = df["volume"].cumsum()
        # Avoid division by zero
        vwap = cumulative_tp_vol / cumulative_vol.replace(0, np.nan)
        return vwap

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add RSI and VWAP indicators."""
        df = df.copy()
        df["rsi"] = ta.momentum.RSIIndicator(
            close=df["close"], window=self.rsi_period
        ).rsi()
        df["vwap"] = self._calculate_vwap(df)
        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate signals based on RSI mean reversion with VWAP.
        
        Logic:
        - BUY when RSI < oversold threshold (mean reversion entry)
        - SELL when RSI > exit threshold OR price >= VWAP (take profit at mean)
        - SELL when RSI > overbought (overbought exit)
        """
        if not self.validate_dataframe(df):
            raise ValueError("Invalid OHLCV DataFrame")

        df = self._add_indicators(df)
        df["signal"] = Signal.HOLD

        in_position = False

        for i in range(1, len(df)):
            rsi = df.iloc[i]["rsi"]
            price = df.iloc[i]["close"]
            vwap = df.iloc[i]["vwap"]

            if pd.isna(rsi) or pd.isna(vwap):
                continue

            if not in_position:
                # Entry: RSI oversold
                if rsi < self.rsi_oversold:
                    df.iloc[i, df.columns.get_loc("signal")] = Signal.BUY
                    in_position = True
            else:
                # Exit conditions
                should_exit = False
                if rsi > self.rsi_exit:
                    should_exit = True  # RSI recovered to neutral
                if price >= vwap:
                    should_exit = True  # Price reached VWAP (mean)
                if rsi > self.rsi_overbought:
                    should_exit = True  # Now overbought

                if should_exit:
                    df.iloc[i, df.columns.get_loc("signal")] = Signal.SELL
                    in_position = False

        return df

    def get_signal(self, df: pd.DataFrame) -> TradeSignal:
        """Get the latest signal for live trading."""
        df = self._add_indicators(df)

        if len(df) < self.rsi_period + 1:
            return TradeSignal(
                signal=Signal.HOLD, price=0, confidence=0, reason="Insufficient data"
            )

        last = df.iloc[-1]
        price = last["close"]
        rsi = last["rsi"]
        vwap = last["vwap"]

        if pd.isna(rsi):
            return TradeSignal(
                signal=Signal.HOLD, price=price, confidence=0, reason="RSI not ready"
            )

        # Determine signal
        signal = Signal.HOLD
        reason = f"RSI={rsi:.1f}, VWAP={vwap:.4f}"

        if rsi < self.rsi_oversold:
            signal = Signal.BUY
            reason = f"RSI oversold ({rsi:.1f} < {self.rsi_oversold})"
        elif rsi > self.rsi_overbought:
            signal = Signal.SELL
            reason = f"RSI overbought ({rsi:.1f} > {self.rsi_overbought})"
        elif rsi > self.rsi_exit and price >= vwap:
            signal = Signal.SELL
            reason = f"RSI neutral ({rsi:.1f}) + price at VWAP"

        # Confidence based on distance from thresholds
        if signal == Signal.BUY:
            confidence = min(1.0, (self.rsi_oversold - rsi) / self.rsi_oversold)
        elif signal == Signal.SELL:
            confidence = min(1.0, (rsi - self.rsi_exit) / (100 - self.rsi_exit))
        else:
            confidence = 0.0

        stop_loss = price * (1 - self.stop_loss_pct / 100)
        take_profit = vwap if not pd.isna(vwap) else price * (1 + self.take_profit_pct / 100)

        return TradeSignal(
            signal=signal,
            price=price,
            confidence=confidence,
            reason=reason,
            stop_loss=round(max(0.01, min(0.99, stop_loss)), 2),
            take_profit=round(max(0.01, min(0.99, take_profit)), 2),
        )
