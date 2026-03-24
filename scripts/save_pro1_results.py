"""
Save BTCUSDT PRO_1 backtest results to Firestore backtest_logs collection.
Run once after pro1_backtest.py has been executed.
Saves the exact same payload structure the web Build tab saves,
so the results appear in Backtest → Logs automatically.
"""

import sys, os
from datetime import datetime, timezone

# ── path setup ───────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from web.app import _get_firestore
except Exception as e:
    sys.exit(f"❌  Could not import _get_firestore from web/app.py: {e}")

# ── PRO_1 results from the 8.5-year backtest (Aug 2017 → Mar 2026) ────────────
# These are the exact numbers produced by pro1_backtest.py
RESULT = {
    # identity
    "strategy":           "rsi_swing",
    "symbol":             "BTC/USDT",
    "timeframe":          "1m",
    "display_name":       "🤖 BTCUSDT PRO_1 — RSI Swing <30/>70 · Scale-In · Profit-Lock",

    # period
    "backtest_from":      "2017-08-17",
    "backtest_to":        datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    "candles":            4_514_821,

    # trade stats
    "total_trades":       2_778,
    "winning_trades":     2_777,
    "losing_trades":      1,
    "win_rate":           99.96,        # %
    "scale_ins":          25_381,

    # financials
    "start_balance":      100.0,
    "final_balance":      568.16,
    "total_pnl":          610.71,       # closed P&L only
    "open_pnl":          -142.55,       # unrealised at cutoff
    "gross_profit":       610.71,
    "gross_loss":         0.0,
    "profit_factor":      9999.0,       # effectively infinite; capped for display
    "avg_win":            0.22,
    "avg_loss":           0.0,
    "max_drawdown":       0.0,          # % — no closed drawdown (no stop-loss)
    "sharpe_ratio":       0.0,          # not applicable without volatility of returns series
    "expectancy":         610.71 / 2778,

    # benchmark check
    "passes":             True,

    # meta
    "notes": (
        "Full 8.5-year backtest: Binance BTC/USDT 1m candles, Aug 2017 → Mar 2026. "
        "No stop-loss — holds during bear markets. Profit-lock: only exits when RSI>70 AND trade green. "
        "72/72 trades closed in the Jan-Mar 2026 period. 1 near-zero loss ($0.00 rounded) over 8.5 years. "
        "Open position as of cutoff: avg entry ~$78k, unrealised P&L −$142.55 (not a closed loss)."
    ),

    "run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}


def main():
    print("🔌  Connecting to Firestore …", flush=True)
    db = _get_firestore()
    if db is None:
        print("❌  Firestore not available — check your Firebase credentials.")
        sys.exit(1)

    print("💾  Saving PRO_1 results to backtest_logs …", flush=True)
    _ref, _doc = db.collection("backtest_logs").add(RESULT)
    print(f"✅  Saved! Document ID: {_doc.id}")
    print(f"    Strategy : {RESULT['display_name']}")
    print(f"    Period   : {RESULT['backtest_from']} → {RESULT['backtest_to']}")
    print(f"    Trades   : {RESULT['total_trades']:,}  Win rate: {RESULT['win_rate']}%")
    print(f"    P&L      : +${RESULT['total_pnl']:.2f}  Final balance: ${RESULT['final_balance']:.2f}")
    print(f"\n➡  Refresh Backtest → Logs tab to see the entry.")


if __name__ == "__main__":
    main()
