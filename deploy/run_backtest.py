"""
Run backtest — test strategies against historical data before going live.

Usage:
    python deploy/run_backtest.py --strategy macd
    python deploy/run_backtest.py --strategy rsi
    python deploy/run_backtest.py --strategy cvd
    python deploy/run_backtest.py --all
    python deploy/run_backtest.py --strategy macd --sweep
"""
import argparse
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from incubation.logger import setup_logger
from data.downloader import DataDownloader
from backtesting.runner import run_single_backtest, run_all_strategies, run_parameter_sweep

logger = setup_logger("backtest")


def main():
    parser = argparse.ArgumentParser(description="Polymarket RBI Bot — Backtester")
    parser.add_argument(
        "--strategy", type=str, default="macd",
        help="Strategy to test: macd, rsi, cvd (default: macd)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Run all strategies",
    )
    parser.add_argument(
        "--sweep", action="store_true",
        help="Run parameter sweep for the selected strategy",
    )
    parser.add_argument(
        "--candles", type=int, default=2000,
        help="Number of candles for synthetic data (default: 2000)",
    )
    parser.add_argument(
        "--size", type=float, default=1.0,
        help="Position size for backtest (default: $1)",
    )
    parser.add_argument(
        "--symbol", type=str, default=None,
        help="Real market symbol to fetch via ccxt (e.g. BTC/USDT). If not set, uses synthetic data.",
    )
    args = parser.parse_args()

    # Get data
    downloader = DataDownloader()

    if args.symbol:
        logger.info("Fetching real data for %s...", args.symbol)
        df = downloader.fetch_ohlcv(symbol=args.symbol, limit=args.candles)
    else:
        logger.info("Generating %d synthetic Polymarket candles...", args.candles)
        df = downloader.generate_synthetic_polymarket_data(num_candles=args.candles)

    logger.info("Data ready: %d candles, %s to %s", len(df), df.iloc[0]["timestamp"], df.iloc[-1]["timestamp"])

    if args.all:
        # Run all strategies
        results = run_all_strategies(df, position_size=args.size)
        print("\n" + "=" * 60)
        print("  SUMMARY — ALL STRATEGIES")
        print("=" * 60)
        for r in results:
            m = r.metrics
            status = "PASS ✓" if m.passes_benchmarks() else "FAIL ✗"
            print(f"  {r.strategy_name}: [{status}] WR={m.win_rate:.1%} PF={m.profit_factor:.2f} Trades={m.total_trades}")
        print("=" * 60)
        return

    if args.sweep:
        # Parameter sweep
        if args.strategy == "macd":
            param_grid = [
                {"fast": 3, "slow": 10, "signal": 3},
                {"fast": 3, "slow": 15, "signal": 3},
                {"fast": 3, "slow": 20, "signal": 3},
                {"fast": 5, "slow": 15, "signal": 5},
                {"fast": 5, "slow": 20, "signal": 5},
                {"fast": 8, "slow": 21, "signal": 5},
            ]
        elif args.strategy == "rsi":
            param_grid = [
                {"rsi_period": 7, "rsi_oversold": 25, "rsi_overbought": 75},
                {"rsi_period": 14, "rsi_oversold": 30, "rsi_overbought": 70},
                {"rsi_period": 14, "rsi_oversold": 25, "rsi_overbought": 75},
                {"rsi_period": 21, "rsi_oversold": 30, "rsi_overbought": 70},
            ]
        elif args.strategy == "cvd":
            param_grid = [
                {"lookback": 10, "divergence_threshold": 0.01},
                {"lookback": 20, "divergence_threshold": 0.02},
                {"lookback": 20, "divergence_threshold": 0.03},
                {"lookback": 30, "divergence_threshold": 0.02},
            ]
        else:
            print(f"No sweep grid defined for {args.strategy}")
            return

        run_parameter_sweep(args.strategy, df, param_grid, position_size=args.size)
        return

    # Single strategy backtest
    result = run_single_backtest(args.strategy, df, position_size=args.size)
    print(result.metrics.summary())

    if result.metrics.passes_benchmarks():
        print(f"  >> {args.strategy.upper()} PASSED — ready for incubation with $1 size")
    else:
        print(f"  >> {args.strategy.upper()} FAILED — do not trade live. Adjust parameters or try another strategy.")


if __name__ == "__main__":
    main()
