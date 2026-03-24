"""
Quick test to verify Binance connection works.
Run: python deploy/test_connection.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from config.accounts import get_account
from data.exchange_client import ExchangeClient


def main():
    print("=" * 50)
    print("  BINANCE CONNECTION TEST")
    print("=" * 50)

    # 1. Check config
    account = get_account("default")
    print(f"\nExchange: {account.exchange_id}")
    print(f"Sandbox:  {account.sandbox}")

    if account.api_key == "YOUR_API_KEY_HERE" or not account.api_key:
        print("\n❌ API key not set! Edit your .env file first:")
        print("   EXCHANGE_API_KEY=your_key_here")
        print("   EXCHANGE_API_SECRET=your_secret_here")
        return

    # 2. Connect
    print("\nConnecting to Binance...")
    client = ExchangeClient(
        exchange_id=account.exchange_id,
        api_key=account.api_key,
        api_secret=account.api_secret,
        sandbox=account.sandbox,
    )
    print("✅ Connected!")

    # 3. Fetch public data (no auth needed)
    print("\n--- Public Data Test ---")
    try:
        price = client.get_price("BTC/USDT")
        print(f"BTC/USDT price: ${price:,.2f}")
    except Exception as e:
        print(f"❌ Failed to get BTC price: {e}")
        return

    try:
        bid, ask = client.get_bid_ask("BTC/USDT")
        print(f"BTC/USDT bid: ${bid:,.2f}  ask: ${ask:,.2f}")
    except Exception as e:
        print(f"⚠ Bid/ask failed: {e}")

    try:
        candles = client.get_ohlcv("BTC/USDT", timeframe="1h", limit=5)
        print(f"Fetched {len(candles)} candles (1h)")
    except Exception as e:
        print(f"⚠ Candle fetch failed: {e}")

    # 4. Fetch balance (requires auth)
    print("\n--- Account Balance Test ---")
    try:
        balance = client.get_balance()
        non_zero = {k: v for k, v in balance.items()
                    if v.get("total", 0) > 0}
        if non_zero:
            for coin, amounts in non_zero.items():
                total = amounts.get("total", 0)
                free = amounts.get("free", 0)
                print(f"  {coin}: {total:.8f} (free: {free:.8f})")
        else:
            print("  No balances found")
        print("✅ Auth works!")
    except Exception as e:
        print(f"❌ Balance fetch failed (check API key permissions): {e}")
        return

    # 5. Check USDC balance for trading
    print(f"\n--- Trading Readiness ---")
    quote = settings.QUOTE_CURRENCY
    try:
        free = client.get_free_balance(quote)
        print(f"Free {quote}: ${free:.2f}")
        if free >= settings.DEFAULT_POSITION_SIZE:
            print(f"✅ Enough {quote} for ${settings.DEFAULT_POSITION_SIZE} trades")
        else:
            print(f"⚠ Only ${free:.2f} {quote} available. Need ${settings.DEFAULT_POSITION_SIZE} per trade.")
            print(f"  Either deposit more {quote} or lower DEFAULT_POSITION_SIZE in .env")
    except Exception as e:
        print(f"⚠ Could not check {quote} balance: {e}")

    print(f"\nDefault symbol: {settings.DEFAULT_SYMBOL}")
    print(f"Position size:  ${settings.DEFAULT_POSITION_SIZE}")
    print("\n✅ All good! You can run the bot with:")
    print(f"  python deploy/run_bot.py --strategy macd --symbol {settings.DEFAULT_SYMBOL} --size {settings.DEFAULT_POSITION_SIZE}")


if __name__ == "__main__":
    main()
