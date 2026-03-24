"""
Global settings for the RBI trading bot.
Supports any exchange via ccxt (Binance, Bybit, OKX, Kraken, etc.)
Override via environment variables or .env file.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Exchange connection ─────────────────────────────────────────────
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "binance")  # binance, bybit, okx, kraken...
EXCHANGE_SANDBOX = os.getenv("EXCHANGE_SANDBOX", "false").lower() == "true"

# ─── Trading defaults ────────────────────────────────────────────────
DEFAULT_SYMBOL = os.getenv("DEFAULT_SYMBOL", "BTC/USDT")
DEFAULT_POSITION_SIZE = float(os.getenv("DEFAULT_POSITION_SIZE", "5.0"))  # USD
QUOTE_CURRENCY = os.getenv("QUOTE_CURRENCY", "USDT")  # Balance currency

# ─── Timeframes ──────────────────────────────────────────────────────
DEFAULT_TIMEFRAME = os.getenv("DEFAULT_TIMEFRAME", "4h")  # Candle timeframe
CANDLE_HISTORY_LIMIT = int(os.getenv("CANDLE_HISTORY_LIMIT", "200"))  # Candles to fetch
DEFAULT_STRATEGY = os.getenv("DEFAULT_STRATEGY", "macd")

# ─── Risk management ─────────────────────────────────────────────────
MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "100.0"))
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "50.0"))
MAX_DRAWDOWN_PCT = float(os.getenv("MAX_DRAWDOWN_PCT", "20.0"))
STOP_LOSS_PCT = 5.0     # Default stop-loss percentage
TAKE_PROFIT_PCT = 10.0  # Default take-profit percentage
MAX_OPEN_POSITIONS = 5   # Max simultaneous positions

# ─── Strategy parameters ─────────────────────────────────────────────
MACD_FAST = 3
MACD_SLOW = 15
MACD_SIGNAL = 3

RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
RSI_EXIT = 50

CVD_LOOKBACK = 20
CVD_DIVERGENCE_THRESHOLD = 0.02

# ─── Incubation scaling ──────────────────────────────────────────────
INCUBATION_SIZES = [1, 2, 5, 10, 25]  # USD progression (adjusted for small accounts)
INCUBATION_MIN_TRADES = 50    # Min trades before scaling up
INCUBATION_MIN_WINRATE = 0.55 # Min win rate to scale up
INCUBATION_PERIOD_DAYS = 14   # Min days per incubation level

# ─── Backtest benchmarks (pass/fail) ─────────────────────────────────
BACKTEST_MIN_WINRATE       = float(os.getenv("BACKTEST_MIN_WINRATE",       "0.55"))
BACKTEST_MIN_PROFIT_FACTOR = float(os.getenv("BACKTEST_MIN_PROFIT_FACTOR", "1.5"))
BACKTEST_MAX_DRAWDOWN      = float(os.getenv("BACKTEST_MAX_DRAWDOWN",      "0.20"))
BACKTEST_MIN_TRADES        = int(os.getenv("BACKTEST_MIN_TRADES",          "100"))
BACKTEST_MIN_SHARPE        = float(os.getenv("BACKTEST_MIN_SHARPE",        "1.0"))

# ─── Logging ─────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = "logs"

# ─── Polling intervals (seconds) ─────────────────────────────────────
BOT_POLL_INTERVAL = 10  # How often the bot checks for signals
MONITOR_POLL_INTERVAL = 60  # How often the monitor reports status
