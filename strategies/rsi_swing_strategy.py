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


class RSISwingProStrategy(BaseStrategy):
    """
    RSI Swing with balance-aware scale-in (BTCUSDT PRO_1).

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

    def get_signal(self, df: pd.DataFrame, in_position: bool = False) -> TradeSignal:
        """
        Live signal — evaluates the latest candle.

        Parameters
        ----------
        df : pd.DataFrame
            Recent OHLCV candles (last N bars).
        in_position : bool
            **Authoritative** position state supplied by the Trader.
            True  = a position is currently open → look for scale-in or exit.
            False = no position open → look for fresh entry.

        Returns BUY, BUY_MORE, SELL, or HOLD.
        The caller (Trader) is responsible for the balance guard on BUY_MORE
        so that no margin / leverage is ever used.

        NOTE: We use `in_position` directly instead of replaying RSI history
        to infer state.  History replay is fundamentally unreliable — it can
        mistake an ancient RSI dip as an open trade and permanently suppress
        BUY signals, causing the bot to hold forever with 0 trades.
        """
        df = self._add_rsi(df)

        last   = df.iloc[-1]
        rsi    = last["rsi"]
        price  = float(last["close"])

        if pd.isna(rsi):
            return TradeSignal(
                signal=Signal.HOLD, price=price, confidence=0.0,
                reason="RSI not yet computed",
            )

        # ── IDLE (no open position) ──────────────────────────────────────
        if not in_position:
            if rsi < self.oversold:
                signal     = Signal.BUY
                confidence = min(1.0, (self.oversold - rsi) / self.oversold)
                reason     = f"RSI={rsi:.2f} < {self.oversold} → BUY (oversold entry)"
            else:
                signal     = Signal.HOLD
                confidence = 0.0
                reason     = (
                    f"RSI={rsi:.2f} — idle, waiting for RSI < {self.oversold}"
                )
            return TradeSignal(
                signal=signal,
                price=price,
                confidence=max(0.0, confidence),
                reason=reason,
                stop_loss=round(price * (1 - self.stop_loss_pct / 100), 2),
                take_profit=round(price * (1 + self.take_profit_pct / 100), 2),
            )

        # ── IN TRADE (position is open) ──────────────────────────────────
        if rsi > self.overbought:
            signal     = Signal.SELL
            confidence = min(1.0, (rsi - self.overbought) / (100 - self.overbought))
            reason     = (
                f"RSI={rsi:.2f} > {self.overbought} → SELL (overbought exit)"
            )
        elif rsi < self.oversold:
            # RSI dipped below oversold again — scale-in; balance check done by Trader
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
                f"RSI={rsi:.2f} — in trade, waiting for "
                f"RSI > {self.overbought} (exit) or < {self.oversold} (scale-in)"
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

    def get_signal(self, df: pd.DataFrame, in_position: bool = False) -> TradeSignal:
        """
        Live signal — evaluates the latest candle using the ACTUAL bot
        position state rather than an unreliable historical replay.

        Parameters
        ----------
        df          : Recent OHLCV candles (at least rsi_period + 1 bars).
        in_position : True if the bot currently holds an open position.
                      The Trader must pass this so the strategy never
                      diverges from reality (e.g. after profit-lock or
                      stop-loss closes the position mid-replay).
        """
        df    = self._add_rsi(df)
        last  = df.iloc[-1]
        rsi   = last["rsi"]
        price = float(last["close"])

        if pd.isna(rsi):
            return TradeSignal(
                signal=Signal.HOLD, price=price, confidence=0.0,
                reason="RSI not yet computed — insufficient data",
            )

        # ── Determine state from ACTUAL position, not simulation ────────
        # States: 0 = IDLE (no position, look for RSI < oversold)
        #         1 = IN_TRADE (position open, look for RSI > overbought)
        #         2 = WAIT_RESET (just sold, wait for next RSI < oversold)
        if in_position:
            # Bot has a confirmed open position — we ARE in trade
            state = 1
        else:
            # No real position.  Replay recent history only to distinguish
            # IDLE (state 0) from WAIT_RESET (state 2) so we never miss a
            # fresh BUY after a quick sell+dip cycle within the window.
            state = 0
            for i in range(self.rsi_period, len(df) - 1):
                rsi_val = df.iloc[i]["rsi"]
                if pd.isna(rsi_val):
                    continue
                if state == 0 and rsi_val < self.oversold:
                    state = 1
                elif state == 1 and rsi_val > self.overbought:
                    state = 2
                elif state == 2 and rsi_val < self.oversold:
                    state = 1
            # If replay ends in state=1 but we have NO real position
            # (e.g. stopped out, or profit-lock sell diverged history),
            # treat as WAIT_RESET — any RSI<oversold triggers a fresh BUY.
            if state == 1:
                state = 2

        # ── Emit signal for the current (last) candle ────────────────────
        if state in (0, 2) and rsi < self.oversold:
            signal     = Signal.BUY
            confidence = min(1.0, (self.oversold - rsi) / self.oversold)
            reason     = (
                f"RSI={rsi:.2f} < {self.oversold} → BUY "
                f"({'idle' if state == 0 else 'post-sell reset'} entry)"
            )
        elif state == 1 and rsi > self.overbought:
            signal     = Signal.SELL
            confidence = min(1.0, (rsi - self.overbought) / (100 - self.overbought))
            reason     = (
                f"RSI={rsi:.2f} > {self.overbought} → SELL (overbought exit)"
            )
        else:
            signal     = Signal.HOLD
            confidence = 0.0
            reason     = (
                f"RSI={rsi:.2f} — "
                f"{'in trade, waiting for RSI>' + str(self.overbought) if state == 1 else 'idle, waiting for RSI<' + str(self.oversold)}"
            )

        return TradeSignal(
            signal=signal,
            price=price,
            confidence=max(0.0, confidence),
            reason=reason,
            stop_loss=round(price * (1 - self.stop_loss_pct / 100), 2),
            take_profit=round(price * (1 + self.take_profit_pct / 100), 2),
        )
