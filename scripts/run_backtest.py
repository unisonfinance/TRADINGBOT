"""
Run comprehensive backtest across all strategies and pairs.
Usage: python scripts/run_backtest.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt
import pandas as pd
from backtesting.runner import run_single_backtest, STRATEGY_MAP

PAIRS = ["BTC/USDT", "ETH/USDT", "LUNA/USDC"]
POSITION_SIZE = 1.0   # USD per trade


def fetch(symbol, tf="1h", limit=1000):
    ex = ccxt.binance()
    raw = ex.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def run_table(strategies, pairs, tf, limit, label):
    results = []
    print()
    print("=" * 86)
    print(f"  {label}  |  {tf} x {limit} bars  |  ${POSITION_SIZE:.2f} USD per trade")
    print("=" * 86)
    print(f"  {'':5} {'Strategy':<40} {'Pair':<12} {'WR':>7} {'PF':>6} {'#':>6} {'PnL':>9} {'MaxDD':>8}")
    print("  " + "-" * 80)

    for pair in pairs:
        try:
            df = fetch(pair, tf=tf, limit=limit)
        except Exception as e:
            print(f"  ! Could not fetch {pair}: {e}")
            continue

        for strat in strategies:
            try:
                r = run_single_backtest(strat, df, position_size=POSITION_SIZE)
                m = r.metrics
                flag = "PASS" if m.passes_benchmarks() else "    "
                results.append((m.profit_factor, strat, pair, m, r.strategy_name, tf))
                print(
                    f"  {flag} {r.strategy_name:<40} {pair:<12}"
                    f" {m.win_rate:>6.1%} {m.profit_factor:>6.2f}"
                    f" {m.total_trades:>6}  ${m.total_pnl:>+7.4f} {m.max_drawdown_pct:>7.1%}"
                )
            except Exception as e:
                print(f"  ERR  {strat:<40} {pair:<12} {e}")

    print("  " + "-" * 80)
    return results


def main():
    strats_1h  = ["macd", "rsi", "cvd"]
    strats_4h  = ["supertrend", "macd", "rsi"]

    all_results = []
    all_results += run_table(strats_1h,  PAIRS, "1h",  1000, "1H STRATEGIES (MACD / RSI / CVD)")
    all_results += run_table(strats_4h,  PAIRS, "4h",  1000, "4H STRATEGIES (SUPERTREND / MACD / RSI) — 1000 bars")

    if all_results:
        best = sorted(all_results, key=lambda x: x[0], reverse=True)[0]
        pf, best_strat, best_pair, best_m, full_name, tf = best

        print()
        print("=" * 86)
        print("  VERDICT")
        print("=" * 86)
        print(f"  Best Strategy : {full_name}")
        print(f"  Best Pair     : {best_pair}  ({tf} candles)")
        print(f"  Win Rate      : {best_m.win_rate:.1%}  (need >55%)")
        print(f"  Profit Factor : {best_m.profit_factor:.2f}  (>1.5=good, >2.0=excellent)")
        print(f"  Total Trades  : {best_m.total_trades}  (need >30 for statistical significance)")
        print(f"  Total PnL     : ${best_m.total_pnl:+.4f}  on $1/trade over {tf} x data")
        print(f"  Max Drawdown  : {best_m.max_drawdown_pct:.1%}  (need <20%)")
        print(f"  Avg Win       : ${best_m.avg_win:+.4f}  |  Avg Loss: ${best_m.avg_loss:+.4f}")
        verdict = "SAFE TO RUN LIVE" if best_m.passes_benchmarks() else "NOT YET — too few trades or low win rate"
        print(f"  VERDICT       : {verdict}")
        print("=" * 86)


if __name__ == "__main__":
    main()
