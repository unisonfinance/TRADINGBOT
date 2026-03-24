"""
Data storage — save/load OHLCV data and trade logs to CSV and SQLite.
"""
import logging
import os
import sqlite3
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "raw")


class DataStorage:
    """Persist OHLCV data and trade records."""

    def __init__(self, storage_dir: str = None):
        self.storage_dir = storage_dir or DATA_DIR
        os.makedirs(self.storage_dir, exist_ok=True)

    # ── CSV storage ──────────────────────────────────────────────────

    def save_csv(self, df: pd.DataFrame, filename: str) -> str:
        """Save DataFrame to CSV. Returns the file path."""
        path = os.path.join(self.storage_dir, filename)
        df.to_csv(path, index=False)
        logger.info("Saved %d rows to %s", len(df), path)
        return path

    def load_csv(self, filename: str) -> pd.DataFrame:
        """Load DataFrame from CSV."""
        path = os.path.join(self.storage_dir, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Data file not found: {path}")
        df = pd.read_csv(path, parse_dates=["timestamp"])
        logger.info("Loaded %d rows from %s", len(df), path)
        return df

    # ── SQLite storage ───────────────────────────────────────────────

    def get_db_path(self) -> str:
        return os.path.join(self.storage_dir, "trades.sqlite")

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.get_db_path())
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_trades_table(self):
        """Create the trades table if it doesn't exist."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                strategy TEXT NOT NULL,
                account TEXT NOT NULL,
                token_id TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                pnl REAL DEFAULT 0,
                status TEXT DEFAULT 'open',
                order_id TEXT,
                notes TEXT
            )
        """)
        conn.commit()
        conn.close()
        logger.info("Trades table initialized")

    def record_trade(
        self,
        strategy: str,
        account: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        order_id: str = None,
        notes: str = None,
    ) -> int:
        """Record a trade. Returns the trade row ID."""
        self.init_trades_table()
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO trades (timestamp, strategy, account, token_id, side, price, size, order_id, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.utcnow().isoformat(),
                strategy,
                account,
                token_id,
                side,
                price,
                size,
                order_id,
                notes,
            ),
        )
        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()
        logger.info("Recorded trade #%d: %s %s @ %.2f", trade_id, side, token_id[:8], price)
        return trade_id

    def update_trade(self, trade_id: int, pnl: float = None, status: str = None):
        """Update a trade's PnL or status."""
        self.init_trades_table()
        conn = self._get_conn()
        if pnl is not None:
            conn.execute("UPDATE trades SET pnl = ? WHERE id = ?", (pnl, trade_id))
        if status is not None:
            conn.execute("UPDATE trades SET status = ? WHERE id = ?", (status, trade_id))
        conn.commit()
        conn.close()

    def get_trades(
        self, strategy: str = None, account: str = None, status: str = None
    ) -> pd.DataFrame:
        """Query trades with optional filters."""
        self.init_trades_table()
        conn = self._get_conn()
        query = "SELECT * FROM trades WHERE 1=1"
        params = []
        if strategy:
            query += " AND strategy = ?"
            params.append(strategy)
        if account:
            query += " AND account = ?"
            params.append(account)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY timestamp DESC"
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        return df
