import requests

base = "https://web-production-eea3.up.railway.app"
coins = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "ADA/USDT", "LINK/USDT"]
for sym in coins:
    r = requests.get(f"{base}/api/price/{sym}", timeout=30)
    d = r.json()
    if "error" in d:
        print(f"{sym}: ERROR - {d['error'][:80]}")
    else:
        print(f"{sym}: price={d['price']}  bid={d['bid']}  ask={d['ask']}")
