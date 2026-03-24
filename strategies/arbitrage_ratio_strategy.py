"""
Arbitrage Ratio Strategy — BTC/ETH pair-swap arbitrage.

Monitors the BTC/ETH price ratio in real time.
When the ratio spikes above its moving average + threshold → swap BTC → ETH.
When the ratio drops below its moving average − threshold → swap ETH → BTC.
Profits from mean-reversion of the ratio.

Inspired by TradingView "BTC ETH Bot" indicator.
"""
import logging

import numpy as np
import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal, TradeSignal

logger = logging.getLogger(__name__)


class ArbitrageRatioStrategy(BaseStrategy):
    """
    BTC/ETH ratio arbitrage.

    The strategy works on a *synthetic* ratio series.  When used in the
    live Trader loop the caller feeds it a DataFrame that already contains
    a ``ratio`` column (btc_close / eth_close).  For back-testing it
    builds that column from the primary symbol (BTC/USDT) close prices
    and a supplied ``eth_prices`` Series, or it falls back to a simple
    close-price ratio if only one series is available.

    Parameters
    ----------
    avg_period : int
        SMA look-back for the ratio average (default 30 bars).
    spike_pct : float
        % deviation from SMA required to trigger a swap (default 2.0%).
    cooldown : int
        Minimum bars between consecutive swaps to avoid whipsaw (default 3).
    stop_loss_pct : float
        Stop-loss as % of entry ratio (default 3.0%).
    take_profit_pct : float
        Take-profit as % of entry ratio (default 4.0%).
    """

    def __init__(
        self,
        avg_period: int = 30,
        spike_pct: float = 2.0,
        cooldown: int = 3,
        stop_loss_pct: float = 3.0,
        take_profit_pct: float = 4.0,
    ):
        self.avg_period = avg_period
        self.spike_pct = spike_pct / 100.0
        self.cooldown = cooldown
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    # ── BaseStrategy interface ────────────────────────────────────────

    @property
    def name(self) -> str:
        return "Arbitrage Ratio (BTC/ETH)"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Back-test signal generation.

        Expects ``df`` to contain at least ``close`` (BTC price).
        If a ``ratio`` column is already present it uses that directly;
        otherwise it treats ``close`` *as* the ratio (for unit-testing or
        when the caller pre-computes the ratio).
        """
        df = df.copy()

        # If no ratio column, use close as-is (caller should provide ratio)
        if "ratio" not in df.columns:
            df["ratio"] = df["close"]

        # Indicators
        df["ratio_sma"] = df["ratio"].rolling(window=self.avg_period, min_periods=1).mean()
        df["ratio_std"] = df["ratio"].rolling(window=self.avg_period, min_periods=1).std().fillna(0)
        df["ratio_zscore"] = np.where(
            df["ratio_std"] > 0,
            (df["ratio"] - df["ratio_sma"]) / df["ratio_std"],
            0,
        )
        df["ratio_dev"] = (df["ratio"] - df["ratio_sma"]) / df["ratio_sma"]

        # Signals
        df["signal"] = Signal.HOLD
        last_signal_bar = -self.cooldown  # allow first signal immediately

        for i in range(self.avg_period, len(df)):
            dev = df.iloc[i]["ratio_dev"]

            # Cooldown check
            if (i - last_signal_bar) < self.cooldown:
                continue

            # Ratio spiked UP → BTC is expensive vs ETH → sell BTC / buy ETH
            if dev >= self.spike_pct:
                df.iloc[i, df.columns.get_loc("signal")] = Signal.SELL
                last_signal_bar = i

            # Ratio dropped DOWN → ETH is expensive vs BTC → buy BTC / sell ETH
            elif dev <= -self.spike_pct:
                df.iloc[i, df.columns.get_loc("signal")] = Signal.BUY
                last_signal_bar = i

        return df

    def get_signal(self, df: pd.DataFrame) -> TradeSignal:
        """
        Live trading signal from the most recent bar.
        """
        df = self.generate_signals(df)
        last = df.iloc[-1]
        ratio = last["ratio"]
        sma = last["ratio_sma"]
        dev = last["ratio_dev"]
        zscore = last["ratio_zscore"]
        price = last["close"]
        signal = last["signal"]

        # Confidence from z-score magnitude (clamped 0-1)
        confidence = min(1.0, abs(zscore) / 3.0)

        direction = "neutral"
        if signal == Signal.SELL:
            direction = "ratio HIGH → swap BTC→ETH"
        elif signal == Signal.BUY:
            direction = "ratio LOW → swap ETH→BTC"

        return TradeSignal(
            signal=signal,
            price=price,
            confidence=confidence,
            reason=(
                f"Ratio={ratio:.4f} SMA={sma:.4f} "
                f"Dev={dev:+.2%} Z={zscore:+.2f} → {direction}"
            ),
            stop_loss=round(price * (1 - self.stop_loss_pct / 100), 2),
            take_profit=round(price * (1 + self.take_profit_pct / 100), 2),
        )
