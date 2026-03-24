"""
"""Run the trading bot — connect to an exchange and execute a strategy.

Usage:
    python deploy/run_bot.py --strategy macd --symbol BTC/USDT --size 10 --account default
    python deploy/run_bot.py --strategy rsi --symbol ETH/USDT --size 5 --account account_2
    python deploy/run_bot.py --strategy cvd --symbol BTC/USDT --size 10

IMPORTANT: Start small (incubation mode). Scale up only after proven results.
"""
import argparse
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from incubation.logger import setup_logger
from bot.trader import Trader

logger = setup_logger("bot")


def main():
    parser = argparse.ArgumentParser(description="Crypto RBI Bot — Live Trader")
    parser.add_argument(
        "--strategy", type=str, required=True,
        help="Strategy to run: macd, rsi, cvd",
    )
    parser.add_argument(
        "--symbol", type=str, default=None,
        help="Trading pair (e.g. BTC/USDT). Defaults to DEFAULT_SYMBOL in settings.",
    )
    parser.add_argument(
        "--size", type=float, default=10.0,
        help="Position size in USD (default: $10)",
    )
    parser.add_argument(
        "--account", type=str, default="default",
        help="Account name from .env (default: default)",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("  CRYPTO RBI BOT")
    logger.info("  Strategy: %s", args.strategy)
    logger.info("  Symbol: %s", args.symbol or "(default)")
    logger.info("  Size: $%.2f", args.size)
    logger.info("  Account: %s", args.account)
    logger.info("=" * 60)

    if args.size > 50:
        logger.warning(
            "Position size $%.2f is above incubation level. "
            "Make sure you've backtested and incubated this strategy first!",
            args.size,
        )

    trader = Trader(
        strategy_name=args.strategy,
        symbol=args.symbol,
        account_name=args.account,
        position_size=args.size,
    )

    logger.info("Bot starting... Press Ctrl+C to stop.")
    trader.run()


if __name__ == "__main__":
    main()
