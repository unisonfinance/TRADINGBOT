import ccxt

for eid in ["binanceus", "bybit", "kraken"]:
    try:
        ex = getattr(ccxt, eid)()
        t = ex.fetch_ticker("BTC/USDT")
        print(f"{eid}: BTC/USDT = {t['last']}")
        t2 = ex.fetch_ticker("ETH/USDT")
        print(f"{eid}: ETH/USDT = {t2['last']}")
        # Test OHLCV too
        o = ex.fetch_ohlcv("BTC/USDT", timeframe="1h", limit=5)
        print(f"{eid}: OHLCV candles = {len(o)}")
        print(f"  => {eid} WORKS!")
        break
    except Exception as e:
        print(f"{eid}: FAILED - {str(e)[:120]}")
