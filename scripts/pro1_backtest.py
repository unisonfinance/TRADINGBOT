"""
BTCUSDT PRO_1 — Full Backtest
Symbol  : BTC/USDT  |  Timeframe: 1m
Period  : 01 Jan 2026 → 20 Mar 2026
Start $ : $100.00 USDT

Rules (identical to live trader):
  1. RSI < 30  → BUY $5 (if no open position)
  2. RSI < 30  → SCALE-IN $5 (if already in trade AND free balance ≥ $5)
  3. RSI > 70 AND price ≥ avg_entry → SELL ALL
  4. RSI > 70 AND price < avg_entry → PROFIT-LOCK (hold; sell as soon as green)
  5. Hard stop-loss at -2% from avg entry (safety net)
"""

import sys, time, os
from datetime import datetime, timezone

# ── dependency check ────────────────────────────────────────────────────────
try:
    import ccxt
except ImportError:
    sys.exit("❌  ccxt not installed.  Run: pip install ccxt")

try:
    import pandas as pd
    import numpy as np
except ImportError:
    sys.exit("❌  pandas/numpy not installed.  Run: pip install pandas numpy")


# ── CONFIG ───────────────────────────────────────────────────────────────────
SYMBOL          = "BTC/USDT"
TIMEFRAME       = "1m"
# Binance launched 2017-08-17; earliest BTC/USDT 1m data starts there
START_DATE      = "2017-08-17T00:00:00Z"
END_DATE        = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
STARTING_USDT   = 100.0
TRADE_SIZE_USD  = 5.0       # dollars per BUY / SCALE-IN
RSI_PERIOD      = 14
RSI_OVERSOLD    = 30
RSI_OVERBOUGHT  = 70
# No stop-loss — if balance runs out we hold BTC long-term until green exit

# CSV cache — stored in data/ alongside other project data files
CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "pro1_cache_1m.csv")


# ── DATA FETCHER ─────────────────────────────────────────────────────────────
def fetch_ohlcv(symbol: str, timeframe: str, since_ms: int, until_ms: int) -> pd.DataFrame:
    # ── use cache if available ───────────────────────────────────────────────
    if os.path.exists(CACHE_FILE):
        print(f"📂  Loading cached data from {CACHE_FILE} …", flush=True)
        df = pd.read_csv(CACHE_FILE, parse_dates=["ts"])
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        cached_end = df["ts"].max()
        cached_end_ms = int(cached_end.timestamp() * 1000)
        print(f"   Cache: {len(df):,} candles  (up to {cached_end.strftime('%Y-%m-%d %H:%M')} UTC)", flush=True)

        # top-up any missing candles up to now
        if cached_end_ms < until_ms - 60_000:
            print(f"📡  Topping up from {cached_end.strftime('%Y-%m-%d')} to today …", flush=True)
            new_df = _download(symbol, timeframe, cached_end_ms + 1, until_ms)
            if not new_df.empty:
                df = pd.concat([df, new_df], ignore_index=True)
                df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
                df.to_csv(CACHE_FILE, index=False)
                print(f"   Cache updated: {len(df):,} total candles", flush=True)
        return df

    # ── fresh download ───────────────────────────────────────────────────────
    df = _download(symbol, timeframe, since_ms, until_ms)
    df.to_csv(CACHE_FILE, index=False)
    print(f"💾  Saved to cache: {CACHE_FILE}", flush=True)
    return df


def _download(symbol: str, timeframe: str, since_ms: int, until_ms: int) -> pd.DataFrame:
    exchange = ccxt.binance({"enableRateLimit": True})
    all_bars = []
    batch    = 1000
    current  = since_ms
    t0       = time.time()

    while current < until_ms:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe, since=current, limit=batch)
        except Exception as e:
            print(f"\n⚠️  Fetch error: {e} — retrying in 5s …", flush=True)
            time.sleep(5)
            continue
        if not bars:
            break
        all_bars.extend(bars)
        current = bars[-1][0] + 1
        elapsed = time.time() - t0
        rate    = len(all_bars) / elapsed if elapsed > 0 else 0
        pct     = min(100, (current - since_ms) / (until_ms - since_ms) * 100)
        eta_s   = (until_ms - current) / 60000 / (rate / 60) if rate > 0 else 0
        print(f"   {len(all_bars):>8,} candles  {pct:5.1f}%  {rate:,.0f} c/s  ETA ~{eta_s/60:.0f}m", end="\r", flush=True)
        if len(bars) < batch:
            break

    print(f"\n✅  {len(all_bars):,} candles fetched", flush=True)
    if not all_bars:
        return pd.DataFrame()

    df = pd.DataFrame(all_bars, columns=["ts","open","high","low","close","volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df[df["ts"] <= pd.Timestamp(END_DATE, tz="UTC")]
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    return df


# ── RSI ───────────────────────────────────────────────────────────────────────
def calc_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_g = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_l = loss.ewm(com=period - 1, min_periods=period).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ── SIMULATION ────────────────────────────────────────────────────────────────
def simulate(df: pd.DataFrame) -> dict:
    df   = df.copy()
    df["rsi"] = calc_rsi(df["close"], RSI_PERIOD)
    df = df.dropna(subset=["rsi"]).reset_index(drop=True)

    usdt_balance   = STARTING_USDT
    btc_held       = 0.0
    avg_entry      = 0.0
    in_trade       = False
    profit_lock    = False
    trades         = []          # list of closed trade dicts
    scale_ins      = 0

    for i, row in df.iterrows():
        price = float(row["close"])
        rsi   = float(row["rsi"])
        ts    = row["ts"]

        # ── profit-lock: both conditions must be met to sell ───────────────
        if profit_lock:
            if rsi > RSI_OVERBOUGHT and price >= avg_entry:
                proceeds      = btc_held * price
                cost_basis    = btc_held * avg_entry
                pnl           = proceeds - cost_basis
                usdt_balance += proceeds
                trades.append({
                    "exit_ts": ts, "exit_price": price,
                    "avg_entry": avg_entry, "btc": btc_held,
                    "pnl": pnl, "result": "WIN (lock)",
                })
                btc_held = avg_entry = 0.0
                in_trade = profit_lock = False
            # still holding — no new entries while locked
            continue

        # ── normal RSI > 70 exit ────────────────────────────────────────────
        if in_trade and rsi > RSI_OVERBOUGHT:
            if price >= avg_entry:                       # green → sell
                proceeds      = btc_held * price
                cost_basis    = btc_held * avg_entry
                pnl           = proceeds - cost_basis
                usdt_balance += proceeds
                trades.append({
                    "exit_ts": ts, "exit_price": price,
                    "avg_entry": avg_entry, "btc": btc_held,
                    "pnl": pnl, "result": "WIN",
                })
                btc_held = avg_entry = 0.0
                in_trade = False
            else:                                        # red → engage lock
                profit_lock = True
            continue

        # ── RSI < 30  BUY / SCALE-IN ────────────────────────────────────────
        if rsi < RSI_OVERSOLD:
            if not in_trade:
                # fresh entry
                if usdt_balance >= TRADE_SIZE_USD:
                    spend     = min(TRADE_SIZE_USD, usdt_balance)
                    btc_bought = spend / price
                    usdt_balance -= spend
                    btc_held   += btc_bought
                    avg_entry   = price
                    in_trade    = True
            else:
                # scale-in
                if usdt_balance >= TRADE_SIZE_USD:
                    spend      = TRADE_SIZE_USD
                    btc_bought = spend / price
                    total_btc  = btc_held + btc_bought
                    avg_entry  = (btc_held * avg_entry + btc_bought * price) / total_btc
                    btc_held   = total_btc
                    usdt_balance -= spend
                    scale_ins  += 1

    # ── close any remaining open position at last price ────────────────────
    open_pnl = 0.0
    if in_trade:
        last_price    = float(df["close"].iloc[-1])
        proceeds      = btc_held * last_price
        cost_basis    = btc_held * avg_entry
        open_pnl      = proceeds - cost_basis
        # included in final balance without "closing" (still open)

    # ── compute metrics ─────────────────────────────────────────────────────
    wins      = [t for t in trades if t["pnl"] > 0]
    losses    = [t for t in trades if t["pnl"] <= 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_los = abs(sum(t["pnl"] for t in losses))
    pf        = gross_win / gross_los if gross_los else float("inf")

    # equity curve for max drawdown
    equity = [STARTING_USDT]
    running = STARTING_USDT
    for t in trades:
        running += t["pnl"]
        equity.append(running)
    peak     = STARTING_USDT
    drawdown = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100
        if dd > drawdown:
            drawdown = dd

    final_balance = usdt_balance + (btc_held * float(df["close"].iloc[-1]) if in_trade else 0)

    return {
        "candles":        len(df),
        "total_trades":   len(trades),
        "wins":           len(wins),
        "losses":         len(losses),
        "scale_ins":      scale_ins,
        "win_rate":       len(wins) / len(trades) * 100 if trades else 0,
        "gross_profit":   gross_win,
        "gross_loss":     gross_los,
        "profit_factor":  pf,
        "net_pnl":        sum(t["pnl"] for t in trades),
        "open_pnl":       open_pnl,
        "max_drawdown":   drawdown,
        "start_balance":  STARTING_USDT,
        "final_balance":  final_balance,
        "in_trade":       in_trade,
        "trades":         trades,
    }


# ── DISPLAY ───────────────────────────────────────────────────────────────────
def print_report(r: dict) -> None:
    SEP = "═" * 58
    sep = "─" * 58
    pnl_sign = "+" if r["net_pnl"] >= 0 else ""
    bal_chg  = r["final_balance"] - r["start_balance"]
    bal_sign = "+" if bal_chg >= 0 else ""
    wl_bar   = ""
    if r["total_trades"]:
        w = round(r["wins"] / r["total_trades"] * 30)
        wl_bar = "█" * w + "░" * (30 - w)

    print(f"\n{SEP}")
    print(f"  🤖  BTCUSDT PRO_1 — BACKTEST RESULTS")
    print(f"      {SYMBOL}  ·  {TIMEFRAME}  ·  Aug 2017 → {datetime.now(timezone.utc).strftime('%d %b %Y')}")
    print(SEP)
    print(f"  Candles analysed : {r['candles']:>10,}")
    print(f"  Total trades     : {r['total_trades']:>10,}")
    print(sep)
    print(f"  ✅  Wins         : {r['wins']:>10,}")
    print(f"  ❌  Losses       : {r['losses']:>10,}")
    print(f"  ➕  Scale-ins    : {r['scale_ins']:>10,}")
    print(f"  ⏳  Still holding: {'YES — waiting for green exit' if r['in_trade'] else 'No open position'}")
    if r['in_trade']:
        print(f"      Open P&L     : ${r['open_pnl']:+.2f}")
    print(f"  Win / Loss bar   :  [{wl_bar}]  {r['win_rate']:.1f}%")
    print(sep)
    print(f"  Gross profit     : ${r['gross_profit']:>9.2f}")
    print(f"  Gross loss       : ${r['gross_loss']:>9.2f}")
    print(f"  Net P&L          : ${pnl_sign}{r['net_pnl']:.2f}")
    print(f"  Profit factor    : {r['profit_factor']:.2f}")
    print(f"  Max drawdown     : {r['max_drawdown']:.1f}%")
    print(sep)
    print(f"  Starting balance : ${r['start_balance']:.2f}")
    if r["in_trade"]:
        print(f"  Open position P&L: ${r['open_pnl']:+.2f}  (not yet closed)")
    print(f"  ★  Final balance : ${r['final_balance']:.2f}  ({bal_sign}{bal_chg:.2f}  /  {bal_sign}{bal_chg/r['start_balance']*100:.1f}%)")
    print(SEP)

    # last 10 trades
    if r["trades"]:
        print(f"\n  Last 10 closed trades:")
        print(f"  {'Exit Time':<22} {'Entry $':>9} {'Exit $':>9} {'P&L':>8}  Result")
        print(f"  {'-'*22} {'-'*9} {'-'*9} {'-'*8}  {'-'*12}")
        for t in r["trades"][-10:]:
            sign = "+" if t["pnl"] >= 0 else ""
            icon = "✅" if t["pnl"] > 0 else ("🛑" if t["result"] == "STOP-LOSS" else "❌")
            print(f"  {str(t['exit_ts'].strftime('%Y-%m-%d %H:%M')):<22} "
                  f"${t['avg_entry']:>8.2f} ${t['exit_price']:>8.2f} "
                  f"{sign}${t['pnl']:.3f}  {icon} {t['result']}")
    print(f"\n{SEP}\n")


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    since_ms = int(datetime.fromisoformat(START_DATE.replace("Z","")).replace(tzinfo=timezone.utc).timestamp() * 1000)
    until_ms = int(datetime.fromisoformat(END_DATE.replace("Z","")).replace(tzinfo=timezone.utc).timestamp() * 1000)

    df = fetch_ohlcv(SYMBOL, TIMEFRAME, since_ms, until_ms)

    print("⚙️  Running BTCUSDT PRO_1 simulation …", flush=True)
    result = simulate(df)

    print_report(result)
