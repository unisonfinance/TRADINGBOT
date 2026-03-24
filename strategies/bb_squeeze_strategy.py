"""
Bollinger Band Squeeze + Momentum Breakout Strategy.

RESEARCH BASIS:
  The "Squeeze" was popularized by John Carter as one of the highest-probability
  setups in technical analysis. When Bollinger Bands (20,2) contract INSIDE
  Keltner Channels (20,1.5×ATR), the market is coiling — volatility compression
  before an explosive breakout move.

LOGIC:
  Squeeze ON  = BBands inside Keltner Channels (volatility compressed)
  Squeeze OFF = BBands expand outside Keltner (energy releasing)
  Direction   = Momentum oscillator (close - midpoint of highest-high/lowest-low)
                smoothed with EMA — positive = breakout to upside, negative = down

ENTRY:
  BUY  when squeeze fires (BB expands above KC) + momentum turns positive
  SELL when squeeze fires + momentum turns negative

ADDITIONAL FILTER:
  RSI(14) mid-zone (35–65) — avoids chasing already-extended moves

BEST TIMEFRAMES: 5m, 15m, 1h
EXPECTED PERFORMANCE (published): 55-65% WR on trending crypto pairs
"""
import pandas as pd
import numpy as np
import ta

from strategies.base_strategy import BaseStrategy, Signal, TradeSignal


class BBSqueezeStrategy(BaseStrategy):

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        kc_period: int = 20,
        kc_mult: float = 1.5,
        mom_period: int = 12,
        rsi_period: int = 14,
        stop_loss_pct: float = 1.5,
        take_profit_pct: float = 3.0,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.kc_period = kc_period
        self.kc_mult = kc_mult
        self.mom_period = mom_period
        self.rsi_period = rsi_period
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    @property
    def name(self) -> str:
        return f"BBSqueeze({self.bb_period},{self.bb_std}×KC{self.kc_mult})"

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(df["close"], window=self.bb_period, window_dev=self.bb_std)
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_mid"]   = bb.bollinger_mavg()
        df["bb_width"] = df["bb_upper"] - df["bb_lower"]

        # Keltner Channels
        kc = ta.volatility.KeltnerChannel(
            df["high"], df["low"], df["close"],
            window=self.kc_period, window_atr=self.kc_period,
            multiplier=self.kc_mult,
        )
        df["kc_upper"] = kc.keltner_channel_hband()
        df["kc_lower"] = kc.keltner_channel_lband()

        # Squeeze: True when BBands are inside Keltner
        df["squeeze_on"] = (df["bb_upper"] < df["kc_upper"]) & (df["bb_lower"] > df["kc_lower"])

        # Momentum: close minus midpoint of high/low range (TTM Squeeze momentum)
        highest = df["high"].rolling(self.mom_period).max()
        lowest  = df["low"].rolling(self.mom_period).min()
        mid     = (highest + lowest) / 2
        delta   = df["close"] - ((mid + df["bb_mid"]) / 2)
        df["momentum"] = delta.ewm(span=self.mom_period).mean()

        # RSI
        df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=self.rsi_period).rsi()

        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.validate_dataframe(df):
            raise ValueError("Invalid OHLCV DataFrame")

        df = self._add_indicators(df)
        df["signal"] = Signal.HOLD

        for i in range(1, len(df)):
            prev_squeeze = df["squeeze_on"].iloc[i - 1]
            curr_squeeze = df["squeeze_on"].iloc[i]
            mom          = df["momentum"].iloc[i]
            prev_mom     = df["momentum"].iloc[i - 1]
            rsi          = df["rsi"].iloc[i]

            if pd.isna(mom) or pd.isna(rsi):
                continue

            # Squeeze just fired (was ON, now OFF) — breakout
            squeeze_fired = prev_squeeze and not curr_squeeze

            if squeeze_fired:
                if mom > 0 and prev_mom <= 0 and 35 < rsi < 70:
                    df.iloc[i, df.columns.get_loc("signal")] = Signal.BUY
                elif mom < 0 and prev_mom >= 0 and 30 < rsi < 65:
                    df.iloc[i, df.columns.get_loc("signal")] = Signal.SELL

            # Momentum flip while already out of squeeze (continuation)
            elif not curr_squeeze:
                if mom > 0 and prev_mom <= 0 and 40 < rsi < 65:
                    df.iloc[i, df.columns.get_loc("signal")] = Signal.BUY
                elif mom < 0 and prev_mom >= 0 and 35 < rsi < 60:
                    df.iloc[i, df.columns.get_loc("signal")] = Signal.SELL

        return df

    def get_signal(self, df: pd.DataFrame) -> TradeSignal:
        df = self._add_indicators(df)
        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(last["close"])

        squeeze_fired = bool(prev["squeeze_on"]) and not bool(last["squeeze_on"])
        mom  = float(last["momentum"]) if not pd.isna(last["momentum"]) else 0.0
        pmom = float(prev["momentum"]) if not pd.isna(prev["momentum"]) else 0.0
        rsi  = float(last["rsi"])      if not pd.isna(last["rsi"])      else 50.0

        sl_long  = close * (1 - self.stop_loss_pct / 100)
        tp_long  = close * (1 + self.take_profit_pct / 100)
        sl_short = close * (1 + self.stop_loss_pct / 100)
        tp_short = close * (1 - self.take_profit_pct / 100)

        if squeeze_fired and mom > 0 and pmom <= 0 and 35 < rsi < 70:
            return TradeSignal(Signal.BUY, close, 0.80,
                f"BB Squeeze fired UP, mom={mom:.4f}, RSI={rsi:.1f}",
                stop_loss=sl_long, take_profit=tp_long)

        if squeeze_fired and mom < 0 and pmom >= 0 and 30 < rsi < 65:
            return TradeSignal(Signal.SELL, close, 0.80,
                f"BB Squeeze fired DOWN, mom={mom:.4f}, RSI={rsi:.1f}",
                stop_loss=sl_short, take_profit=tp_short)

        return TradeSignal(Signal.HOLD, close, 0.0,
            f"Squeeze={'ON' if last['squeeze_on'] else 'off'}, mom={mom:.4f}")
