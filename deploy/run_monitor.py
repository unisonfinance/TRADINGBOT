"""
Run the monitoring dashboard — shows live status of all bots.

Usage:
    python deploy/run_monitor.py
    python deploy/run_monitor.py --interval 30
"""
import argparse
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from incubation.logger import setup_logger
from incubation.monitor import BotMonitor
from incubation.scaler import IncubationScaler

logger = setup_logger("monitor")


def main():
    parser = argparse.ArgumentParser(description="Polymarket RBI Bot — Monitor")
    parser.add_argument(
        "--interval", type=int, default=60,
        help="Seconds between status reports (default: 60)",
    )
    parser.add_argument(
        "--check-scaling", action="store_true",
        help="Also check incubation scaling recommendations",
    )
    parser.add_argument(
        "--strategy", type=str, default=None,
        help="Filter by strategy name",
    )
    parser.add_argument(
        "--account", type=str, default=None,
        help="Filter by account name",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("  POLYMARKET BOT MONITOR")
    logger.info("  Report interval: %d seconds", args.interval)
    logger.info("=" * 60)

    if args.check_scaling and args.strategy and args.account:
        scaler = IncubationScaler(strategy=args.strategy, account=args.account)
        result = scaler.evaluate()
        print(f"\nIncubation Status: {result['level']}")
        print(f"  Action: {result['action']}")
        print(f"  Reason: {result['reason']}")
        print(f"  Trades: {result['trades']} | Win Rate: {result['win_rate']:.1%}")
        print(f"  Days at level: {result['days_at_level']}")
        print()

    monitor = BotMonitor()
    monitor.run(interval=args.interval)


if __name__ == "__main__":
    main()
