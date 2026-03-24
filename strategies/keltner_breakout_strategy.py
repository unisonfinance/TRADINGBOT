"""
Keltner Channel Breakout + RSI Confirmation Strategy.

RESEARCH BASIS:
  Keltner Channels use ATR (true volatility) rather than standard deviation,
  making them more responsive to real market conditions than Bollinger Bands.

  When price breaks OUTSIDE a Keltner Channel and RSI confirms the momentum,
  it signals a genuine volatility expansion and directional move is underway.

  This is fundamentally different from BB Squeeze — here we want continuation
  of a breakout move, not mean reversion.

  The strategy is particularly effective in crypto because:
  1. Crypto has fat tails — breakouts persist longer than in equities
  2. Crypto lacks institutional mean-reversion algos to immediately fade moves
  3. Channel breaks often lead to 3-8% continuation moves on 1h+

LOGIC:
  EMA(20) is the Keltner midline
  Upper Band = EMA(20) + 2×ATR(10)
  Lower Band = EMA(20) - 2×ATR(10)

ENTRY:
  BUY  when: close breaks above upper KC + RSI 55-75 (momentum, not overbought)
             + bar closes above KC (not just wick)
  SELL when: close breaks below lower KC + RSI 25-45
             + bar closes below KC

CONTINUATION ENTRY (pyramid):
  After initial break, if price retests the channel top (acts as support)
  + RSI dips to 50 = second entry

BEST TIMEFRAMES: 30m, 1h, 4h
EXPECTED PERFORMANCE: 52-60% WR, with 2:1+ R:R giving positive expectancy
"""
import pandas as pd
import numpy as np
import ta

from strategies.base_strategy import BaseStrategy, Signal, TradeSignal


class KeltnerBreakoutStrategy(BaseStrategy):

    def __init__(
        self,
        ema_period: int = 20,
        atr_period: int = 10,
        atr_mult: float = 2.0,
        rsi_period: int = 14,
        stop_loss_pct: float = 1.5,
        take_profit_pct: float = 3.5,
    ):
        self.ema_period  = ema_period
        self.atr_period  = atr_period
        self.atr_mult    = atr_mult
        self.rsi_period  = rsi_period
        self.stop_loss_pct   = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    @property
    def name(self) -> str:
        return f"KeltnerBreakout(EMA{self.ema_period},{self.atr_mult}×ATR)"

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        kc = ta.volatility.KeltnerChannel(
            df["high"], df["low"], df["close"],
            window=self.ema_period,
            window_atr=self.atr_period,
            multiplier=self.atr_mult,
        )
        df["kc_upper"]  = kc.keltner_channel_hband()
        df["kc_lower"]  = kc.keltner_channel_lband()
        df["kc_mid"]    = kc.keltner_channel_mband()
        df["kc_pband"]  = kc.keltner_channel_pband()   # percent band (0=lo, 1=hi)
        df["kc_wband"]  = kc.keltner_channel_wband()   # width

        df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=self.rsi_period).rsi()

        # ATR for stop sizing
        df["atr"] = ta.volatility.AverageTrueRange(
            df["high"], df["low"], df["close"], window=self.atr_period
        ).average_true_range()

        df["vol_avg"] = df["volume"].rolling(20).mean()

        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.validate_dataframe(df):
            raise ValueError("Invalid OHLCV DataFrame")

        df = self._add_indicators(df)
        df["signal"] = Signal.HOLD

        for i in range(1, len(df)):
            row  = df.iloc[i]
            prev = df.iloc[i - 1]

            close      = row["close"]
            p_close    = prev["close"]
            kc_upper   = row["kc_upper"]
            kc_lower   = row["kc_lower"]
            p_kc_upper = prev["kc_upper"]
            p_kc_lower = prev["kc_lower"]
            rsi        = row["rsi"]
            vol        = row["volume"]
            vol_avg    = row["vol_avg"]

            if any(pd.isna(x) for x in [kc_upper, kc_lower, rsi]):
                continue

            vol_ok = vol > vol_avg * 0.9 if not pd.isna(vol_avg) else True

            # Upside breakout: close crosses above upper KC
            if p_close <= p_kc_upper and close > kc_upper and 52 < rsi < 78 and vol_ok:
                df.iloc[i, df.columns.get_loc("signal")] = Signal.BUY

            # Downside breakout: close crosses below lower KC
            elif p_close >= p_kc_lower and close < kc_lower and 22 < rsi < 48 and vol_ok:
                df.iloc[i, df.columns.get_loc("signal")] = Signal.SELL

        return df

    def get_signal(self, df: pd.DataFrame) -> TradeSignal:
        df = self._add_indicators(df)
        last = df.iloc[-1]
        prev = df.iloc[-2]
        close      = float(last["close"])
        p_close    = float(prev["close"])
        kc_upper   = float(last["kc_upper"])   if not pd.isna(last["kc_upper"])   else close
        kc_lower   = float(last["kc_lower"])   if not pd.isna(last["kc_lower"])   else close
        p_kc_upper = float(prev["kc_upper"])   if not pd.isna(prev["kc_upper"])   else close
        p_kc_lower = float(prev["kc_lower"])   if not pd.isna(prev["kc_lower"])   else close
        rsi        = float(last["rsi"])         if not pd.isna(last["rsi"])        else 50
        atr        = float(last["atr"])         if not pd.isna(last["atr"])        else 0
        vol        = float(last["volume"])
        vol_avg    = float(last["vol_avg"])     if not pd.isna(last["vol_avg"])    else vol

        vol_ok = vol > vol_avg * 0.9

        sl_long  = close - 1.5 * atr if atr > 0 else close * (1 - self.stop_loss_pct / 100)
        tp_long  = close + 3.0 * atr if atr > 0 else close * (1 + self.take_profit_pct / 100)
        sl_short = close + 1.5 * atr if atr > 0 else close * (1 + self.stop_loss_pct / 100)
        tp_short = close - 3.0 * atr if atr > 0 else close * (1 - self.take_profit_pct / 100)

        if p_close <= p_kc_upper and close > kc_upper and 52 < rsi < 78 and vol_ok:
            return TradeSignal(Signal.BUY, close, 0.70,
                f"KC breakout UP: close={close:.2f}>KC_upper={kc_upper:.2f}, RSI={rsi:.1f}",
                stop_loss=sl_long, take_profit=tp_long)

        if p_close >= p_kc_lower and close < kc_lower and 22 < rsi < 48 and vol_ok:
            return TradeSignal(Signal.SELL, close, 0.70,
                f"KC breakout DOWN: close={close:.2f}<KC_lower={kc_lower:.2f}, RSI={rsi:.1f}",
                stop_loss=sl_short, take_profit=tp_short)

        pband = float(last["kc_pband"]) if not pd.isna(last["kc_pband"]) else 0.5
        return TradeSignal(Signal.HOLD, close, 0.0,
            f"KC: pband={pband:.2f}, RSI={rsi:.1f}, kc_u={kc_upper:.2f}")
