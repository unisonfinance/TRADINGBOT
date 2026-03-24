"""
Run comprehensive backtest and save every result to Firestore backtest_logs.
This populates the Logs tab in the web dashboard.

Usage:
    python scripts/save_backtest_logs.py
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore as fs

from backtesting.engine import BacktestEngine
from backtesting.runner import get_strategy

# ─── Firebase init ────────────────────────────────────────────────
sa_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "service_account.json")
if not firebase_admin._apps:
    cred = credentials.Certificate(sa_path)
    firebase_admin.initialize_app(cred)
db = fs.client()


# ─── Config ───────────────────────────────────────────────────────
POSITION_SIZE = 1.0

RUNS = [
    # (strategy_key, symbol, timeframe, candles, label)
    # ── 4H BTC/USDT — primary target ──────────────────────────────
    ("macd",        "BTC/USDT",  "4h", 1000, "PRIMARY — MACD 4H BTC/USDT"),
    # ── Full 1H sweep ─────────────────────────────────────────────
    ("macd",        "BTC/USDT",  "1h", 1000, "Sweep 1H"),
    ("rsi",         "BTC/USDT",  "1h", 1000, "Sweep 1H"),
    ("cvd",         "BTC/USDT",  "1h", 1000, "Sweep 1H"),
    ("macd",        "ETH/USDT",  "1h", 1000, "Sweep 1H"),
    ("rsi",         "ETH/USDT",  "1h", 1000, "Sweep 1H"),
    ("cvd",         "ETH/USDT",  "1h", 1000, "Sweep 1H"),
    ("macd",        "LUNA/USDC", "1h", 1000, "Sweep 1H"),
    ("rsi",         "LUNA/USDC", "1h", 1000, "Sweep 1H"),
    ("cvd",         "LUNA/USDC", "1h", 1000, "Sweep 1H"),
    # ── Full 4H sweep ─────────────────────────────────────────────
    ("supertrend",  "BTC/USDT",  "4h", 1000, "Sweep 4H"),
    ("rsi",         "BTC/USDT",  "4h", 1000, "Sweep 4H"),
    ("supertrend",  "ETH/USDT",  "4h", 1000, "Sweep 4H"),
    ("macd",        "ETH/USDT",  "4h", 1000, "Sweep 4H"),
    ("rsi",         "ETH/USDT",  "4h", 1000, "Sweep 4H"),
    ("supertrend",  "LUNA/USDC", "4h", 1000, "Sweep 4H"),
    ("macd",        "LUNA/USDC", "4h", 1000, "Sweep 4H"),
    ("rsi",         "LUNA/USDC", "4h", 1000, "Sweep 4H"),
]


def fetch_ohlcv(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    exchange = ccxt.binance()
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def run_and_save(strategy_key, symbol, timeframe, candles, label):
    print(f"  Running {strategy_key.upper():<12} {symbol:<12} {timeframe}  ({candles} bars)  ...", end=" ", flush=True)
    try:
        df = fetch_ohlcv(symbol, timeframe, candles)
        data_from = str(df["timestamp"].iloc[0])
        data_to   = str(df["timestamp"].iloc[-1])

        strategy = get_strategy(strategy_key)
        engine   = BacktestEngine(position_size=POSITION_SIZE)
        result   = engine.run(strategy, df)
        m        = result.metrics

        wr_dec       = m.win_rate
        loss_rate    = 1.0 - wr_dec
        expectancy   = (m.avg_win * wr_dec) + (m.avg_loss * loss_rate)
        run_at       = datetime.now(timezone.utc).isoformat()

        doc = {
            "run_at":             run_at,
            "label":              label,
            "strategy":           result.strategy_name,
            "symbol":             symbol,
            "timeframe":          timeframe,
            "candles":            int(candles),
            "position_size":      float(POSITION_SIZE),
            "data_from":          data_from,
            "data_to":            data_to,
            "total_trades":       int(m.total_trades),
            "winning_trades":     int(m.winning_trades),
            "losing_trades":      int(m.losing_trades),
            "win_rate":           float(round(wr_dec * 100, 2)),
            "profit_factor":      float(round(m.profit_factor, 4)),
            "total_pnl":          float(round(m.total_pnl, 4)),
            "max_drawdown":       float(round(m.max_drawdown_pct * 100, 2)),
            "sharpe_ratio":       float(round(m.sharpe_ratio, 4)),
            "avg_win":            float(round(m.avg_win, 4)),
            "avg_loss":           float(round(m.avg_loss, 4)),
            "avg_trade_pnl":      float(round(m.avg_trade_pnl, 4)),
            "largest_win":        float(round(m.largest_win, 4)),
            "largest_loss":       float(round(m.largest_loss, 4)),
            "consecutive_wins":   int(m.consecutive_wins),
            "consecutive_losses": int(m.consecutive_losses),
            "expectancy":         float(round(expectancy, 4)),
            "passes":             bool(m.passes_benchmarks()),
        }

        db.collection("backtest_logs").add(doc)
        status = "PASS ✓" if m.passes_benchmarks() else f"PF={m.profit_factor:.2f} WR={m.win_rate:.0%} T={m.total_trades}"
        print(f"{status}  PnL ${m.total_pnl:+.4f}")
        return doc

    except Exception as e:
        print(f"ERROR — {e}")
        return None


def main():
    print()
    print("=" * 72)
    print("  Saving backtest results to Firestore → backtest_logs")
    print("=" * 72)

    saved = 0
    for args in RUNS:
        doc = run_and_save(*args)
        if doc:
            saved += 1

    print()
    print(f"  Done — {saved}/{len(RUNS)} results saved to Firestore.")
    print("  Open the dashboard → Backtest → Logs tab to view.")
    print("=" * 72)


if __name__ == "__main__":
    main()
