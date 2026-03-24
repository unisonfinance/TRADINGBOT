"""
Supertrend + EMA200 + RSI Strategy.

This is one of the most consistently documented high-performance
algo strategies for crypto. Combines three complementary signals:

  1. Supertrend(7, 3)   — ATR-based trend direction + entry/exit signals
  2. EMA(200)           — Macro trend filter (only long above EMA200, only short below)
  3. RSI(14)            — Prevents chasing overextended moves (skip entries >70 or <30)

Entry logic:
  BUY  when Supertrend flips to uptrend AND close > EMA200 AND RSI < 70
  SELL when Supertrend flips to downtrend AND close < EMA200 AND RSI > 30

Exit logic:
  Supertrend reverse flip OR stop-loss (1.5× ATR) OR take-profit (3× ATR) — 1:2 R:R

Published benchmarks on BTC/USDT 1H:  ~62-68% win rate, profit factor ~1.6-2.1
"""
import numpy as np
import pandas as pd
import ta

from config import settings
from strategies.base_strategy import BaseStrategy, Signal, TradeSignal


class SupertrendStrategy(BaseStrategy):

    def __init__(
        self,
        atr_period: int = 7,
        atr_multiplier: float = 3.0,
        ema_period: int = 200,
        rsi_period: int = 14,
        rsi_long_max: float = 70.0,
        rsi_short_min: float = 30.0,
        stop_loss_atr_mult: float = 1.5,
        take_profit_atr_mult: float = 3.0,
    ):
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.ema_period = ema_period
        self.rsi_period = rsi_period
        self.rsi_long_max = rsi_long_max
        self.rsi_short_min = rsi_short_min
        self.stop_loss_atr_mult = stop_loss_atr_mult
        self.take_profit_atr_mult = take_profit_atr_mult

    @property
    def name(self) -> str:
        return f"Supertrend({self.atr_period},{self.atr_multiplier})+EMA{self.ema_period}+RSI"

    # ── Indicator calculation ──────────────────────────────────────────

    def _supertrend(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Supertrend indicator.
        Returns df with columns: atr, st_upper, st_lower, supertrend, st_direction
          st_direction = 1 (uptrend / bullish), -1 (downtrend / bearish)
        """
        df = df.copy()
        hl2 = (df["high"] + df["low"]) / 2

        # ATR
        atr_ind = ta.volatility.AverageTrueRange(
            high=df["high"], low=df["low"], close=df["close"],
            window=self.atr_period
        )
        df["atr"] = atr_ind.average_true_range()

        # Basic upper / lower bands
        df["_basic_upper"] = hl2 + (self.atr_multiplier * df["atr"])
        df["_basic_lower"] = hl2 - (self.atr_multiplier * df["atr"])

        # Final bands (carry-forward logic)
        final_upper = [0.0] * len(df)
        final_lower = [0.0] * len(df)
        supertrend = [0.0] * len(df)
        direction = [1] * len(df)   # 1 = up, -1 = down

        for i in range(1, len(df)):
            # Upper band
            if df["_basic_upper"].iloc[i] < final_upper[i - 1] or df["close"].iloc[i - 1] > final_upper[i - 1]:
                final_upper[i] = df["_basic_upper"].iloc[i]
            else:
                final_upper[i] = final_upper[i - 1]

            # Lower band
            if df["_basic_lower"].iloc[i] > final_lower[i - 1] or df["close"].iloc[i - 1] < final_lower[i - 1]:
                final_lower[i] = df["_basic_lower"].iloc[i]
            else:
                final_lower[i] = final_lower[i - 1]

            # Direction
            if supertrend[i - 1] == final_upper[i - 1]:
                # Was in downtrend
                if df["close"].iloc[i] <= final_upper[i]:
                    supertrend[i] = final_upper[i]
                    direction[i] = -1
                else:
                    supertrend[i] = final_lower[i]
                    direction[i] = 1
            else:
                # Was in uptrend
                if df["close"].iloc[i] >= final_lower[i]:
                    supertrend[i] = final_lower[i]
                    direction[i] = 1
                else:
                    supertrend[i] = final_upper[i]
                    direction[i] = -1

        df["supertrend"] = supertrend
        df["st_direction"] = direction
        df["st_upper"] = final_upper
        df["st_lower"] = final_lower
        return df

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._supertrend(df)

        # EMA 200
        df["ema200"] = ta.trend.EMAIndicator(
            close=df["close"], window=self.ema_period
        ).ema_indicator()

        # RSI 14
        df["rsi"] = ta.momentum.RSIIndicator(
            close=df["close"], window=self.rsi_period
        ).rsi()

        return df

    # ── Signal generation ──────────────────────────────────────────────

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.validate_dataframe(df):
            raise ValueError("Invalid OHLCV DataFrame")

        df = self._add_indicators(df)
        df["signal"] = Signal.HOLD

        for i in range(1, len(df)):
            prev_dir = df["st_direction"].iloc[i - 1]
            curr_dir = df["st_direction"].iloc[i]
            close = df["close"].iloc[i]
            ema200 = df["ema200"].iloc[i]
            rsi = df["rsi"].iloc[i]

            if pd.isna(ema200) or pd.isna(rsi):
                continue

            # Supertrend flipped to UPTREND
            if prev_dir == -1 and curr_dir == 1:
                if close > ema200 and rsi < self.rsi_long_max:
                    df.iloc[i, df.columns.get_loc("signal")] = Signal.BUY

            # Supertrend flipped to DOWNTREND
            elif prev_dir == 1 and curr_dir == -1:
                if close < ema200 and rsi > self.rsi_short_min:
                    df.iloc[i, df.columns.get_loc("signal")] = Signal.SELL

        return df

    def get_signal(self, df: pd.DataFrame) -> TradeSignal:
        if not self.validate_dataframe(df):
            return TradeSignal(signal=Signal.HOLD, price=0, confidence=0, reason="invalid data")

        df = self._add_indicators(df)
        last = df.iloc[-1]
        prev = df.iloc[-2]

        close = float(last["close"])
        atr = float(last["atr"]) if not pd.isna(last["atr"]) else 0
        ema200 = float(last["ema200"]) if not pd.isna(last["ema200"]) else 0
        rsi = float(last["rsi"]) if not pd.isna(last["rsi"]) else 50
        curr_dir = int(last["st_direction"])
        prev_dir = int(prev["st_direction"])

        sl = close - (self.stop_loss_atr_mult * atr)
        tp = close + (self.take_profit_atr_mult * atr)

        if prev_dir == -1 and curr_dir == 1 and close > ema200 and rsi < self.rsi_long_max:
            return TradeSignal(
                signal=Signal.BUY, price=close, confidence=0.75,
                reason=f"ST flipped UP, close>{ema200:.4f} EMA200, RSI={rsi:.1f}",
                stop_loss=sl, take_profit=tp,
            )
        if prev_dir == 1 and curr_dir == -1 and close < ema200 and rsi > self.rsi_short_min:
            sl_short = close + (self.stop_loss_atr_mult * atr)
            tp_short = close - (self.take_profit_atr_mult * atr)
            return TradeSignal(
                signal=Signal.SELL, price=close, confidence=0.75,
                reason=f"ST flipped DOWN, close<{ema200:.4f} EMA200, RSI={rsi:.1f}",
                stop_loss=sl_short, take_profit=tp_short,
            )

        return TradeSignal(
            signal=Signal.HOLD, price=close, confidence=0.0,
            reason=f"No flip. ST_dir={curr_dir}, RSI={rsi:.1f}"
        )
