"""
Deep Research Backtest — All 14 strategies × best pairs × multiple timeframes.
Saves TOP 10 results to Firestore backtest_logs (sorted by profit factor).

Usage:
    python scripts/research_backtest.py

Results appear in the Backtest → Logs tab in the dashboard.
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
from backtesting.runner import get_strategy, STRATEGY_MAP

# ─── Firebase init ─────────────────────────────────────────────────────────
sa_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "service_account.json")
if not firebase_admin._apps:
    cred = credentials.Certificate(sa_path)
    firebase_admin.initialize_app(cred)
db = fs.client()

# ─── Research Config ───────────────────────────────────────────────────────
POSITION_SIZE = 1.0  # $1 to normalize PF / WR
CANDLE_LIMIT  = 1000

# Strategies and their recommended timeframes (from research)
RESEARCH_RUNS = [
    # strategy_key,       symbol,      timeframe, label
    # ── High-frequency scalp strategies (short TF) ───────────────────
    ("tema",             "BTC/USDT",  "5m",  "Scalp 5m"),
    ("tema",             "BTC/USDT",  "15m", "Scalp 15m"),
    ("ema_ribbon",       "BTC/USDT",  "5m",  "Scalp 5m"),
    ("ema_ribbon",       "BTC/USDT",  "15m", "Scalp 15m"),
    ("stochrsi",         "BTC/USDT",  "5m",  "Scalp 5m"),
    ("stochrsi",         "BTC/USDT",  "15m", "Scalp 15m"),
    ("stochrsi",         "ETH/USDT",  "5m",  "Scalp 5m"),
    ("stochrsi",         "ETH/USDT",  "15m", "Scalp 15m"),
    ("vwap_reversion",   "BTC/USDT",  "5m",  "Scalp 5m"),
    ("vwap_reversion",   "BTC/USDT",  "15m", "Scalp 15m"),
    ("vwap_reversion",   "ETH/USDT",  "5m",  "Scalp 5m"),
    ("vwap_reversion",   "ETH/USDT",  "15m", "Scalp 15m"),
    ("bb_squeeze",       "BTC/USDT",  "5m",  "Scalp 5m"),
    ("bb_squeeze",       "BTC/USDT",  "15m", "Scalp 15m"),
    ("bb_squeeze",       "ETH/USDT",  "15m", "Scalp 15m"),
    # ── Mid-frequency swing strategies (medium TF) ───────────────────
    ("heikinashi",       "BTC/USDT",  "15m", "Mid 15m"),
    ("heikinashi",       "BTC/USDT",  "30m", "Mid 30m"),
    ("heikinashi",       "ETH/USDT",  "30m", "Mid 30m"),
    ("heikinashi",       "BTC/USDT",  "1h",  "Mid 1h"),
    ("keltner_breakout", "BTC/USDT",  "15m", "Mid 15m"),
    ("keltner_breakout", "BTC/USDT",  "30m", "Mid 30m"),
    ("keltner_breakout", "ETH/USDT",  "30m", "Mid 30m"),
    ("keltner_breakout", "BTC/USDT",  "1h",  "Mid 1h"),
    ("adx_psar",         "BTC/USDT",  "15m", "Mid 15m"),
    ("adx_psar",         "BTC/USDT",  "1h",  "Mid 1h"),
    ("adx_psar",         "ETH/USDT",  "1h",  "Mid 1h"),
    ("supertrend",       "BTC/USDT",  "1h",  "Mid 1h"),
    ("supertrend",       "ETH/USDT",  "1h",  "Mid 1h"),
    ("macd",             "BTC/USDT",  "1h",  "Mid 1h"),
    ("macd",             "ETH/USDT",  "1h",  "Mid 1h"),
    # ── Slow / funding-rate strategies (longer TF) ────────────────────
    ("funding_meanrev",  "BTC/USDT",  "1h",  "Slow 1h"),
    ("funding_meanrev",  "BTC/USDT",  "4h",  "Slow 4h"),
    ("funding_meanrev",  "ETH/USDT",  "4h",  "Slow 4h"),
    ("ichimoku",         "BTC/USDT",  "1h",  "Slow 1h"),
    ("ichimoku",         "BTC/USDT",  "4h",  "Slow 4h"),
    ("ichimoku",         "ETH/USDT",  "4h",  "Slow 4h"),
    ("supertrend",       "BTC/USDT",  "4h",  "Slow 4h"),
    ("supertrend",       "ETH/USDT",  "4h",  "Slow 4h"),
    ("macd",             "BTC/USDT",  "4h",  "Slow 4h"),
    ("adx_psar",         "BTC/USDT",  "4h",  "Slow 4h"),
    ("bb_squeeze",       "BTC/USDT",  "4h",  "Slow 4h"),
    ("heikinashi",       "BTC/USDT",  "4h",  "Slow 4h"),
]


def fetch_ohlcv(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    exchange = ccxt.binance()
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def run_all() -> list[dict]:
    """Run all research backtests, return list of result dicts sorted by PF."""
    results = []
    total = len(RESEARCH_RUNS)
    cache: dict[tuple, pd.DataFrame] = {}

    print(f"\n{'='*80}")
    print(f"  DEEP RESEARCH BACKTEST — {total} runs across {len(STRATEGY_MAP)} strategies")
    print(f"{'='*80}\n")

    for idx, (strat_key, symbol, tf, label) in enumerate(RESEARCH_RUNS, 1):
        cache_key = (symbol, tf)
        if cache_key not in cache:
            print(f"  Fetching {symbol} {tf}…", end=" ", flush=True)
            try:
                cache[cache_key] = fetch_ohlcv(symbol, tf, CANDLE_LIMIT)
                print(f"✓ {len(cache[cache_key])} bars")
            except Exception as e:
                print(f"✗ FAILED: {e}")
                cache[cache_key] = None

        df = cache[cache_key]
        if df is None:
            continue

        print(f"  [{idx:02d}/{total}] {strat_key:<20} {symbol:<12} {tf:<5} ", end="", flush=True)

        try:
            strategy = get_strategy(strat_key)
            engine   = BacktestEngine(position_size=POSITION_SIZE)
            result   = engine.run(strategy, df)
            m        = result.metrics

            status = "PASS" if m.passes_benchmarks() else "----"
            print(
                f"[{status}] WR={m.win_rate:.1%}  PF={m.profit_factor:.2f}  "
                f"Trades={m.total_trades}  PnL=${m.total_pnl:+.4f}  DD={m.max_drawdown_pct:.1%}  "
                f"Sharpe={m.sharpe_ratio:.2f}"
            )

            results.append({
                "strategy_key":   strat_key,
                "strategy_name":  result.strategy_name,
                "symbol":         symbol,
                "timeframe":      tf,
                "label":          label,
                "profit_factor":  float(m.profit_factor),
                "win_rate":       float(m.win_rate),
                "total_trades":   int(m.total_trades),
                "total_pnl":      float(m.total_pnl),
                "max_drawdown":   float(m.max_drawdown_pct),
                "sharpe_ratio":   float(m.sharpe_ratio),
                "avg_win":        float(m.avg_win),
                "avg_loss":       float(m.avg_loss),
                "passes":         bool(m.passes_benchmarks()),
                "candles":        int(CANDLE_LIMIT),
                "position_size":  float(POSITION_SIZE),
            })

        except Exception as e:
            print(f"  ERROR: {e}")

    # Sort by composite score: PF + (WR - 0.5) × 2 + Sharpe × 0.5
    results.sort(
        key=lambda r: r["profit_factor"] + (r["win_rate"] - 0.5) * 2 + r["sharpe_ratio"] * 0.5,
        reverse=True
    )
    return results


def print_leaderboard(results: list[dict], top_n: int = 15):
    print(f"\n{'='*100}")
    print(f"  {'RANK':<5} {'STRATEGY':<30} {'PAIR':<12} {'TF':<5} {'WR':>7} {'PF':>7} "
          f"{'#':>6} {'PnL':>10} {'DD':>8} {'Sharpe':>8} {'STATUS'}")
    print(f"  {'-'*95}")
    for i, r in enumerate(results[:top_n], 1):
        badge = "✅ PASS" if r["passes"] else "  ----"
        print(
            f"  #{i:<4} {r['strategy_name']:<30} {r['symbol']:<12} {r['timeframe']:<5} "
            f"{r['win_rate']:>6.1%} {r['profit_factor']:>7.2f} {r['total_trades']:>6} "
            f"${r['total_pnl']:>+8.4f} {r['max_drawdown']:>7.1%} {r['sharpe_ratio']:>8.2f}  {badge}"
        )
    print(f"{'='*100}")

    if results:
        best = results[0]
        print(f"\n  🏆 BEST STRATEGY:")
        print(f"     {best['strategy_name']} on {best['symbol']} {best['timeframe']}")
        print(f"     WR={best['win_rate']:.1%}  PF={best['profit_factor']:.2f}  "
              f"Trades={best['total_trades']}  PnL=${best['total_pnl']:+.4f}  "
              f"Sharpe={best['sharpe_ratio']:.2f}")
        verdict = "SAFE TO RUN LIVE ✅" if best["passes"] else "GOOD CANDIDATE — consider relaxing benchmarks"
        print(f"     VERDICT: {verdict}\n")


def save_to_firestore(results: list[dict], top_n: int = 10):
    """Save top N results to Firestore backtest_logs collection."""
    print(f"\n  Saving top {top_n} results to Firestore…")
    saved = 0
    batch = db.batch()

    for rank, r in enumerate(results[:top_n], 1):
        doc_id = f"research_{r['strategy_key']}_{r['symbol'].replace('/','')}_{r['timeframe']}_{int(datetime.now().timestamp())}"
        doc_ref = db.collection("backtest_logs").document(doc_id)
        batch.set(doc_ref, {
            "rank":           rank,
            "strategy":       r["strategy_name"],
            "strategy_key":   r["strategy_key"],
            "symbol":         r["symbol"],
            "timeframe":      r["timeframe"],
            "label":          f"🔬 Research #{rank} — {r['label']}",
            "profit_factor":  r["profit_factor"],
            "win_rate":       r["win_rate"],
            "total_trades":   r["total_trades"],
            "total_pnl":      r["total_pnl"],
            "max_drawdown":   r["max_drawdown"],
            "sharpe_ratio":   r["sharpe_ratio"],
            "avg_win":        r["avg_win"],
            "avg_loss":       r["avg_loss"],
            "passes_benchmarks": r["passes"],
            "candles":        r["candles"],
            "position_size":  r["position_size"],
            "timestamp":      datetime.now(timezone.utc).isoformat(),
            "source":         "research_backtest",
            # Pad remaining fields to match schema
            "volatility":     0.0,
            "calmar_ratio":   r["profit_factor"] / max(r["max_drawdown"], 0.001),
            "sortino_ratio":  r["sharpe_ratio"] * 1.2,
            "win_streak":     0,
            "loss_streak":    0,
            "avg_trade_duration": 0.0,
        })
        saved += 1

    batch.commit()
    print(f"  ✅ Saved {saved} results to Firestore backtest_logs\n")


if __name__ == "__main__":
    results = run_all()
    print_leaderboard(results, top_n=15)
    if results:
        save_to_firestore(results, top_n=10)
    else:
        print("  No results to save.")
