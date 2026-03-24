"""
Parallel backtest runner — test multiple strategies / parameter combos at once.
"""
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd

from strategies.base_strategy import BaseStrategy
from strategies.macd_strategy import MACDStrategy
from strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from strategies.cvd_strategy import CVDStrategy
from backtesting.engine import BacktestEngine, BacktestResult

logger = logging.getLogger(__name__)

# Strategy registry
STRATEGY_MAP = {
    "macd": MACDStrategy,
    "rsi": RSIMeanReversionStrategy,
    "cvd": CVDStrategy,
}


def get_strategy(name: str, **kwargs) -> BaseStrategy:
    """Get a strategy instance by name."""
    name = name.lower()
    if name not in STRATEGY_MAP:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(STRATEGY_MAP.keys())}")
    return STRATEGY_MAP[name](**kwargs)


def run_single_backtest(
    strategy_name: str,
    df: pd.DataFrame,
    position_size: float = 1.0,
    **strategy_kwargs,
) -> BacktestResult:
    """Run a single backtest. Can be called in a subprocess."""
    strategy = get_strategy(strategy_name, **strategy_kwargs)
    engine = BacktestEngine(position_size=position_size)
    return engine.run(strategy, df)


def run_all_strategies(
    df: pd.DataFrame,
    position_size: float = 1.0,
) -> list[BacktestResult]:
    """Run backtests for all registered strategies and return results."""
    results = []
    for name in STRATEGY_MAP:
        logger.info("Running backtest for: %s", name)
        result = run_single_backtest(name, df, position_size)
        results.append(result)
        print(result.metrics.summary())
    return results


def run_parameter_sweep(
    strategy_name: str,
    df: pd.DataFrame,
    param_grid: list[dict],
    position_size: float = 1.0,
) -> list[BacktestResult]:
    """
    Test multiple parameter combinations for a strategy.
    
    Example:
        param_grid = [
            {"fast": 3, "slow": 10, "signal": 3},
            {"fast": 3, "slow": 15, "signal": 3},
            {"fast": 5, "slow": 20, "signal": 5},
        ]
    """
    results = []
    for params in param_grid:
        logger.info("Testing %s with params: %s", strategy_name, params)
        result = run_single_backtest(strategy_name, df, position_size, **params)
        results.append(result)

    # Sort by profit factor descending
    results.sort(key=lambda r: r.metrics.profit_factor, reverse=True)

    print(f"\n{'='*60}")
    print(f"  PARAMETER SWEEP: {strategy_name.upper()}")
    print(f"  {len(param_grid)} combinations tested")
    print(f"{'='*60}")
    for i, r in enumerate(results):
        m = r.metrics
        status = "PASS" if m.passes_benchmarks() else "FAIL"
        print(
            f"  #{i+1} [{status}] {r.strategy_name}: "
            f"WR={m.win_rate:.1%} PF={m.profit_factor:.2f} "
            f"DD={m.max_drawdown_pct:.1%} Trades={m.total_trades}"
        )
    print(f"{'='*60}\n")

    return results
