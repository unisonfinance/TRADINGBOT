"""
OHLCV data downloader using ccxt.
Downloads candlestick data for backtesting and live analysis.
"""
import logging
import time
from datetime import datetime, timedelta

import ccxt
import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


class DataDownloader:
    """Downloads OHLCV data from exchanges via ccxt for backtesting."""

    def __init__(self, exchange_id: str = "binance"):
        """
        Initialize downloader. Uses ccxt for OHLCV data since
        Polymarket doesn't provide historical candles directly.
        We use correlated crypto market data as a proxy for 
        strategy development and backtesting.
        """
        exchange_class = getattr(ccxt, exchange_id, None)
        if exchange_class is None:
            raise ValueError(f"Exchange '{exchange_id}' not supported by ccxt")
        self.exchange = exchange_class({"enableRateLimit": True})
        logger.info("DataDownloader initialized with exchange: %s", exchange_id)

    def fetch_ohlcv(
        self,
        symbol: str = "BTC/USDT",
        timeframe: str = None,
        since: datetime = None,
        limit: int = None,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candlestick data.
        
        Args:
            symbol: Trading pair (e.g. "BTC/USDT")
            timeframe: Candle timeframe (e.g. "5m", "1h")
            since: Start datetime (default: 500 candles back)
            limit: Number of candles to fetch
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        timeframe = timeframe or settings.DEFAULT_TIMEFRAME
        limit = limit or settings.CANDLE_HISTORY_LIMIT

        since_ms = None
        if since:
            since_ms = int(since.timestamp() * 1000)

        logger.info(
            "Fetching %d candles of %s %s", limit, symbol, timeframe
        )

        all_candles = []
        fetched = 0

        while fetched < limit:
            batch_limit = min(1000, limit - fetched)
            candles = self.exchange.fetch_ohlcv(
                symbol, timeframe, since=since_ms, limit=batch_limit
            )
            if not candles:
                break

            all_candles.extend(candles)
            fetched += len(candles)

            # Move the cursor forward
            since_ms = candles[-1][0] + 1

            # Respect rate limits
            time.sleep(self.exchange.rateLimit / 1000)

            if len(candles) < batch_limit:
                break  # No more data available

        df = pd.DataFrame(
            all_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
        df = df.reset_index(drop=True)

        logger.info("Fetched %d candles for %s", len(df), symbol)
        return df

    def fetch_multiple_symbols(
        self,
        symbols: list[str],
        timeframe: str = None,
        limit: int = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for multiple symbols. Returns dict of DataFrames."""
        results = {}
        for symbol in symbols:
            try:
                results[symbol] = self.fetch_ohlcv(
                    symbol, timeframe=timeframe, limit=limit
                )
            except Exception as e:
                logger.error("Failed to fetch %s: %s", symbol, e)
        return results

    def generate_synthetic_polymarket_data(
        self,
        num_candles: int = 1000,
        timeframe_minutes: int = 5,
    ) -> pd.DataFrame:
        """
        Generate synthetic Polymarket-like price data for backtesting.
        Polymarket prices are bounded 0.01 - 0.99 (probabilities).
        """
        import numpy as np

        np.random.seed(42)
        timestamps = pd.date_range(
            end=datetime.now(),
            periods=num_candles,
            freq=f"{timeframe_minutes}min",
        )

        # Random walk bounded between 0.05 and 0.95
        price = 0.50
        prices = []
        for _ in range(num_candles):
            change = np.random.normal(0, 0.02)
            price = max(0.05, min(0.95, price + change))
            prices.append(price)

        opens = prices
        highs = [min(0.99, p + abs(np.random.normal(0, 0.01))) for p in prices]
        lows = [max(0.01, p - abs(np.random.normal(0, 0.01))) for p in prices]
        closes = [
            max(0.01, min(0.99, p + np.random.normal(0, 0.005)))
            for p in prices
        ]
        volumes = [abs(np.random.normal(1000, 500)) for _ in prices]

        df = pd.DataFrame({
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        })
        df = df.round({"open": 4, "high": 4, "low": 4, "close": 4, "volume": 2})

        logger.info("Generated %d synthetic Polymarket candles", len(df))
        return df
