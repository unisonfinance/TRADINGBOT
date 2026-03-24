"""
Trade logger — structured logging for all bot activity.
Logs to both console and rotating log files.
"""
import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler

from config import settings


def setup_logger(
    name: str = "polymarket_bot",
    level: str = None,
    log_dir: str = None,
) -> logging.Logger:
    """
    Set up structured logging with console + file output.
    
    Args:
        name: Logger name (used as filename too)
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_dir: Directory for log files
    Returns:
        Configured logger
    """
    level = level or settings.LOG_LEVEL
    log_dir = log_dir or settings.LOG_DIR
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler (rotating, 5MB max, keep 5 backups)
    log_file = os.path.join(log_dir, f"{name}.log")
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Trade-specific file (just trades, no debug noise)
    trade_file = os.path.join(log_dir, f"{name}_trades.log")
    trade_handler = RotatingFileHandler(
        trade_file, maxBytes=5 * 1024 * 1024, backupCount=5
    )
    trade_handler.setLevel(logging.INFO)
    trade_handler.setFormatter(formatter)
    trade_logger = logging.getLogger(f"{name}.trades")
    trade_logger.addHandler(trade_handler)

    return logger


def log_trade(
    strategy: str,
    account: str,
    side: str,
    token_id: str,
    price: float,
    size: float,
    pnl: float = None,
    reason: str = "",
):
    """Log a trade to the dedicated trade log."""
    trade_logger = logging.getLogger("polymarket_bot.trades")
    pnl_str = f"P&L=${pnl:.4f}" if pnl is not None else "P&L=pending"
    trade_logger.info(
        "TRADE | %s | %s | %s | %s | $%.4f x $%.2f | %s | %s",
        strategy, account, side, token_id[:12], price, size, pnl_str, reason,
    )
