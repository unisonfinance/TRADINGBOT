"""
BTCUSDT PRO_1 — RSI Swing Strategy with balance-aware scale-in
              and profit-locked exits.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FINAL TRADING RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. ENTRY — RSI CLOSES BELOW 30
   ● Candle closes with RSI < 30 and no open position → BUY $5 of BTC
   ● No leverage, no margin — only free USDT balance is used.

2. SCALE-IN — RSI CLOSES BELOW 30 AGAIN (while still in trade)
   ● RSI dips below 30 again BEFORE a sell has been executed.
   ● Bot checks real free balance:
       – free balance ≥ $5  → BUY another $5 (scale-in, avg cost updated)
       – free balance < $5  → HOLD — skip, never borrow
   ● After scale-in the average entry price is recalculated
     (weighted average of all buy prices × sizes).

3. SELL CONDITION — RSI CLOSES ABOVE 70 AND TRADE IS IN GREEN
   ● BOTH must be true on the SAME candle close:
       a) RSI > 70
       b) current close price ≥ average entry price  (green or break-even)
   ● Even $0.001 profit counts — break-even also triggers the sell.

4. PROFIT-LOCK — RSI > 70 BUT TRADE IS IN LOSS
   ● Bot engages PROFIT-LOCK mode: does NOT sell.
   ● Waits for a future candle where BOTH RSI > 70 AND trade is green.
   ● If RSI drops back below 70 while still in loss → keep holding.
   ● No new buys or scale-ins while PROFIT-LOCK is active.

5. CYCLE RESET
   ● After a successful sell the bot goes back to IDLE and waits for
     the next RSI < 30 candle before buying again.

GUARANTEES
   ✓ Never sells at a loss (unless stop-loss triggers — see below).
   ✓ Never uses margin or leverage.
   ✓ Every new position is funded only from real available balance.
   ✓ Stop-loss (default –2 %) still protects against sharp drops.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import logging

import numpy as np
import pandas as pd
import ta

from strategies.base_strategy import BaseStrategy, Signal, TradeSignal

logger = logging.getLogger(__name__)

DISPLAY_NAME = "BTCUSDT PRO_1"


class RSISwingStrategy(BaseStrategy):
    """
    RSI Swing with balance-aware scale-in.

    Parameters
    ----------
    rsi_period : int
        RSI look-back window (default 14).
    oversold : float
        RSI level that triggers a BUY / BUY_MORE (default 30).
    overbought : float
        RSI level that triggers a SELL (default 70).
    stop_loss_pct : float
        Hard stop-loss from entry price in % (default 2.0).
    take_profit_pct : float
        Take-profit from entry price in % (default 3.0).
    min_trade_usd : float
        Minimum USD balance needed to scale into another position
        (default 5.0 — same as the base position size).
    """

    def __init__(
        self,
        rsi_period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        stop_loss_pct: float = 2.0,
        take_profit_pct: float = 3.0,
        min_trade_usd: float = 5.0,
    ):
        self.rsi_period      = rsi_period
        self.oversold        = oversold
        self.overbought      = overbought
        self.stop_loss_pct   = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.min_trade_usd   = min_trade_usd

    # ── BaseStrategy interface ────────────────────────────────────────

    @property
    def name(self) -> str:
        return DISPLAY_NAME

    def _add_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi"] = ta.momentum.RSIIndicator(
            close=df["close"], window=self.rsi_period
        ).rsi()
        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Backtest signal generation over the full DataFrame.

        NOTE: profit-lock (rule 3/4) cannot be simulated here without
        knowing the exact entry price at each bar.  SELL is therefore
        emitted whenever RSI > 70, and the backtesting runner is
        responsible for filtering out loss-making exits if needed.

        State machine
        -------------
        IDLE (0)     — no position; BUY when RSI < oversold.
        IN_TRADE (1) — in position:
                         • RSI < oversold again → BUY_MORE (scale-in)
                         • RSI > overbought     → SELL  (profit check in Trader)
        """
        if not self.validate_dataframe(df):
            raise ValueError("Invalid OHLCV DataFrame")

        df = self._add_rsi(df)
        df["signal"] = Signal.HOLD

        state = 0  # 0 = IDLE, 1 = IN_TRADE

        for i in range(self.rsi_period, len(df)):
            rsi = df.iloc[i]["rsi"]
            if pd.isna(rsi):
                continue

            if state == 0:
                # IDLE — looking for first oversold entry
                if rsi < self.oversold:
                    df.iloc[i, df.columns.get_loc("signal")] = Signal.BUY
                    state = 1

            elif state == 1:
                # IN_TRADE
                if rsi > self.overbought:
                    # Exit the whole accumulated position
                    df.iloc[i, df.columns.get_loc("signal")] = Signal.SELL
                    state = 0  # go straight back to IDLE (wait for next oversold)
                elif rsi < self.oversold:
                    # RSI dipped below oversold again — propose scale-in
                    # The live trader will do the balance check; for backtesting
                    # we treat BUY_MORE as an unconditional extra buy.
                    df.iloc[i, df.columns.get_loc("signal")] = Signal.BUY_MORE

        return df

    def get_signal(self, df: pd.DataFrame) -> TradeSignal:
        """
        Live signal — evaluates the latest candle.

        Returns BUY, BUY_MORE, SELL, or HOLD.
        The caller (Trader) is responsible for the balance guard on BUY_MORE
        so that no margin / leverage is ever used.
        """
        df = self._add_rsi(df)

        # Replay state up to (but NOT including) the last candle so the
        # final signal evaluation sees the correct pre-last-bar state.
        state = 0
        for i in range(self.rsi_period, len(df) - 1):
            rsi_val = df.iloc[i]["rsi"]
            if pd.isna(rsi_val):
                continue
            if state == 0:
                if rsi_val < self.oversold:
                    state = 1
            else:
                if rsi_val > self.overbought:
                    state = 0

        last   = df.iloc[-1]
        rsi    = last["rsi"]
        price  = float(last["close"])

        if pd.isna(rsi):
            return TradeSignal(
                signal=Signal.HOLD, price=price, confidence=0.0,
                reason="RSI not yet computed",
            )

        # Decide signal for the CURRENT (last) candle given inferred state
        if state == 0 and rsi < self.oversold:
            signal     = Signal.BUY
            confidence = min(1.0, (self.oversold - rsi) / self.oversold)
            reason     = (
                f"RSI={rsi:.2f} < {self.oversold} → BUY (fresh oversold entry)"
            )
        elif state == 1 and rsi > self.overbought:
            signal     = Signal.SELL
            confidence = min(1.0, (rsi - self.overbought) / (100 - self.overbought))
            reason     = (
                f"RSI={rsi:.2f} > {self.overbought} → SELL (overbought exit)"
            )
        elif state == 1 and rsi < self.oversold:
            # Scale-in opportunity; balance check is done by the Trader
            signal     = Signal.BUY_MORE
            confidence = min(1.0, (self.oversold - rsi) / self.oversold)
            reason     = (
                f"RSI={rsi:.2f} < {self.oversold} again while IN TRADE → "
                f"BUY_MORE (scale-in if balance ≥ ${self.min_trade_usd:.0f})"
            )
        else:
            signal     = Signal.HOLD
            confidence = 0.0
            reason     = (
                f"RSI={rsi:.2f} — holding "
                f"({'in trade' if state == 1 else 'idle'}, waiting)"
            )

        return TradeSignal(
            signal=signal,
            price=price,
            confidence=max(0.0, confidence),
            reason=reason,
            stop_loss=round(price * (1 - self.stop_loss_pct / 100), 2),
            take_profit=round(price * (1 + self.take_profit_pct / 100), 2),
        )



class RSISwingStrategy(BaseStrategy):
    """
    RSI Swing: buy oversold (<30), sell overbought (>70), wait for
    a fresh oversold dip before buying again.

    Parameters
    ----------
    rsi_period : int
        RSI look-back window (default 14).
    oversold : float
        RSI level that triggers a BUY (default 30).
    overbought : float
        RSI level that triggers a SELL (default 70).
    stop_loss_pct : float
        Hard stop-loss from entry price in % (default 2.0).
    take_profit_pct : float
        Take-profit from entry price in % (default 3.0).
    """

    def __init__(
        self,
        rsi_period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        stop_loss_pct: float = 2.0,
        take_profit_pct: float = 3.0,
    ):
        self.rsi_period  = rsi_period
        self.oversold    = oversold
        self.overbought  = overbought
        self.stop_loss_pct   = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    # ── BaseStrategy interface ────────────────────────────────────────

    @property
    def name(self) -> str:
        return f"RSI Swing ({self.rsi_period}) <{self.oversold}/>{ self.overbought}"

    def _add_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi"] = ta.momentum.RSIIndicator(
            close=df["close"], window=self.rsi_period
        ).rsi()
        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Backtest signal generation over the full DataFrame.

        State machine:
          IDLE       — not in position, looking for RSI < oversold
          IN_TRADE   — in position, looking for RSI > overbought
          WAIT_RESET — just sold, waiting for RSI to drop below oversold
                       before allowing the next BUY
        """
        if not self.validate_dataframe(df):
            raise ValueError("Invalid OHLCV DataFrame")

        df = self._add_rsi(df)
        df["signal"] = Signal.HOLD

        # States: 0=idle/looking, 1=in trade, 2=wait_reset
        state = 0

        for i in range(self.rsi_period, len(df)):
            rsi = df.iloc[i]["rsi"]
            if pd.isna(rsi):
                continue

            if state == 0:
                # Waiting for oversold — BUY when RSI crosses below 30
                if rsi < self.oversold:
                    df.iloc[i, df.columns.get_loc("signal")] = Signal.BUY
                    state = 1

            elif state == 1:
                # In trade — SELL when RSI crosses above 70
                if rsi > self.overbought:
                    df.iloc[i, df.columns.get_loc("signal")] = Signal.SELL
                    state = 2  # wait for RSI to reset below oversold

            elif state == 2:
                # Sold — wait for RSI to dip below oversold again
                if rsi < self.oversold:
                    df.iloc[i, df.columns.get_loc("signal")] = Signal.BUY
                    state = 1

        return df

    def get_signal(self, df: pd.DataFrame) -> TradeSignal:
        """
        Live signal — evaluates only the latest candle.

        The state is inferred from the most recent BUY/SELL in the
        signal history. This means the caller should pass enough recent
        candles so the strategy can determine its own position state.
        """
        df = self.generate_signals(df)
        last   = df.iloc[-1]
        rsi    = last["rsi"]
        price  = float(last["close"])
        signal = last["signal"]

        # Confidence: how far RSI is from the threshold
        if signal == Signal.BUY:
            confidence = min(1.0, (self.oversold - rsi) / self.oversold)
            reason = (
                f"RSI={rsi:.2f} crossed below {self.oversold} → BUY "
                f"(oversold entry)"
            )
        elif signal == Signal.SELL:
            confidence = min(1.0, (rsi - self.overbought) / (100 - self.overbought))
            reason = (
                f"RSI={rsi:.2f} crossed above {self.overbought} → SELL "
                f"(overbought exit)"
            )
        else:
            confidence = 0.0
            reason = f"RSI={rsi:.2f} — no signal (between {self.oversold} and {self.overbought})"

        return TradeSignal(
            signal=signal,
            price=price,
            confidence=max(0.0, confidence),
            reason=reason,
            stop_loss=round(price * (1 - self.stop_loss_pct / 100), 2),
            take_profit=round(price * (1 + self.take_profit_pct / 100), 2),
        )
