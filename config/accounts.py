"""
Multi-account configuration for running parallel bots.
Each account maps to exchange API credentials.
Supports: Binance, Bybit, OKX, Kraken, and 100+ others via ccxt.
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class AccountConfig:
    name: str
    api_key: str
    api_secret: str
    exchange_id: str = "binance"
    password: str = ""  # Passphrase (needed by OKX, Kucoin, etc.)
    sandbox: bool = False


def load_accounts() -> dict[str, AccountConfig]:
    """
    Load accounts from environment variables.
    
    Default account: EXCHANGE_API_KEY / EXCHANGE_API_SECRET
    Additional:      EXCHANGE_API_KEY_2 / EXCHANGE_API_SECRET_2 ...
    """
    accounts = {}
    exchange_id = os.getenv("EXCHANGE_ID", "binance")
    sandbox = os.getenv("EXCHANGE_SANDBOX", "false").lower() == "true"

    # Default account
    key = os.getenv("EXCHANGE_API_KEY", "")
    secret = os.getenv("EXCHANGE_API_SECRET", "")
    if key and secret:
        accounts["default"] = AccountConfig(
            name="default",
            api_key=key,
            api_secret=secret,
            exchange_id=exchange_id,
            password=os.getenv("EXCHANGE_PASSWORD", ""),
            sandbox=sandbox,
        )

    # Numbered accounts (2, 3, 4, ...)
    idx = 2
    while True:
        key = os.getenv(f"EXCHANGE_API_KEY_{idx}", "")
        secret = os.getenv(f"EXCHANGE_API_SECRET_{idx}", "")
        if not key or not secret:
            break
        name = f"account_{idx}"
        accounts[name] = AccountConfig(
            name=name,
            api_key=key,
            api_secret=secret,
            exchange_id=os.getenv(f"EXCHANGE_ID_{idx}", exchange_id),
            password=os.getenv(f"EXCHANGE_PASSWORD_{idx}", ""),
            sandbox=sandbox,
        )
        idx += 1

    return accounts


def get_account(name: str = "default") -> AccountConfig:
    """Get a specific account by name. Raises KeyError if not found."""
    accounts = load_accounts()
    if name not in accounts:
        available = list(accounts.keys())
        raise KeyError(
            f"Account '{name}' not found. Available accounts: {available}. "
            f"Check your .env file."
        )
    return accounts[name]
