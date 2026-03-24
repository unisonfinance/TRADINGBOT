"""
Web Dashboard — Flask backend for the Crypto RBI Trading Bot.
Provides API endpoints and serves the frontend.
"""
import json
import os
import sys
import threading
import time
from datetime import datetime

from flask import Flask, render_template, request, jsonify, redirect, url_for

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from config.accounts import get_account, load_accounts
from data.exchange_client import ExchangeClient
from data.storage import DataStorage
from backtesting.engine import BacktestEngine
from backtesting.runner import get_strategy
from bot.trader import Trader
from deploy.deploy_firestore_rules import deploy_rules

# ─── Firebase Admin (Firestore for server-side log saves) ─────────
_firestore_db = None

def _get_firestore():
    """Lazy-init and return Firestore client, or None on failure."""
    global _firestore_db
    if _firestore_db is not None:
        return _firestore_db
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore as fs
        sa_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "service_account.json")
        if not firebase_admin._apps:
            cred = credentials.Certificate(sa_path)
            firebase_admin.initialize_app(cred)
        _firestore_db = fs.client()
        return _firestore_db
    except Exception as e:
        print(f"[Firestore] Admin init failed: {e}")
        return None

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ─── Global state ─────────────────────────────────────────────────
active_bots: dict[str, dict] = {}  # name -> {trader, thread, started_at}
storage = DataStorage()
_firestore_rules_status: dict = {"deployed": False, "message": "Pending..."}


def _auto_deploy_firestore_rules():
    """Deploy Firestore security rules in a background thread on startup."""
    global _firestore_rules_status
    print("[Firebase] Deploying Firestore security rules...")
    result = deploy_rules()
    if result["success"]:
        _firestore_rules_status = {"deployed": True, "message": "Rules deployed ✓", "ruleset": result.get("ruleset", "")}
        print(f"[Firebase] ✓ Firestore rules deployed: {result.get('ruleset', '')}")
    else:
        _firestore_rules_status = {"deployed": False, "message": result["error"]}
        print(f"[Firebase] ✗ Rules deploy failed: {result['error']}")


# Launch rules deploy in background so server starts immediately
threading.Thread(target=_auto_deploy_firestore_rules, daemon=True).start()


# ─── Helper: read/write .env ─────────────────────────────────────
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def read_env() -> dict:
    """Read .env file into a dict."""
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
    return env


def write_env(env: dict):
    """Write dict back to .env, preserving comments."""
    lines = []
    existing_keys = set()

    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.partition("=")[0].strip()
                    if key in env:
                        lines.append(f"{key}={env[key]}\n")
                        existing_keys.add(key)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)

    # Add any new keys
    for key, value in env.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}\n")

    with open(ENV_PATH, "w") as f:
        f.writelines(lines)


def get_client():
    """Create an ExchangeClient from current .env config."""
    env = read_env()
    api_key = env.get("EXCHANGE_API_KEY", "")
    api_secret = env.get("EXCHANGE_API_SECRET", "")
    exchange_id = env.get("EXCHANGE_ID", "binance")
    sandbox = env.get("EXCHANGE_SANDBOX", "false").lower() == "true"
    password = env.get("EXCHANGE_PASSWORD", "") or None

    if not api_key or api_key == "YOUR_API_KEY_HERE":
        return None

    return ExchangeClient(
        exchange_id=exchange_id,
        api_key=api_key,
        api_secret=api_secret,
        password=password,
        sandbox=sandbox,
    )


# ─── Pages ────────────────────────────────────────────────────────
@app.route("/login")
def login():
    return render_template("login.html", active_page="login")


@app.route("/")
def dashboard():
    return render_template("dashboard.html", active_page="dashboard")


@app.route("/trading")
def trading():
    return render_template("trading.html", active_page="trading")


@app.route("/backtest")
def backtest():
    return render_template("backtest.html", active_page="backtest")


@app.route("/settings")
def settings_page():
    return render_template("settings.html", active_page="settings")


# ─── API: Account & Balance ──────────────────────────────────────
@app.route("/api/balance")
def api_balance():
    try:
        client = get_client()
        if not client:
            return jsonify({"error": "API keys not configured"}), 400

        raw = client.get_balance()
        totals = raw.get("total", {})
        free  = raw.get("free", {})
        used  = raw.get("used", {})
        non_zero = {}
        for coin, total in totals.items():
            if isinstance(total, (int, float)) and total > 0:
                non_zero[coin] = {
                    "total": round(float(total), 8),
                    "free":  round(float(free.get(coin, 0) or 0), 8),
                    "used":  round(float(used.get(coin, 0) or 0), 8),
                }
        return jsonify({"balances": non_zero})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/price/<path:symbol>")
def api_price(symbol):
    try:
        client = get_client()
        if not client:
            # Use unauthenticated client for public data
            client = ExchangeClient(
                exchange_id=read_env().get("EXCHANGE_ID", "binance"),
                api_key="", api_secret="", sandbox=False,
            )
        price = client.get_price(symbol)
        ba = client.get_bid_ask(symbol)
        return jsonify({"symbol": symbol, "price": price, "bid": ba["bid"], "ask": ba["ask"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/candles/<path:symbol>")
def api_candles(symbol):
    try:
        import ccxt
        exchange_id = read_env().get("EXCHANGE_ID", "binance")
        exchange = getattr(ccxt, exchange_id)()
        tf = request.args.get("timeframe", "1h")
        limit = int(request.args.get("limit", "100"))
        candles = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
        return jsonify({"symbol": symbol, "timeframe": tf, "candles": candles})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Trading Bot Control ───────────────────────────────────
@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    data = request.json
    strategy = data.get("strategy", settings.DEFAULT_STRATEGY)
    symbol   = data.get("symbol",   settings.DEFAULT_SYMBOL)
    timeframe= data.get("timeframe",settings.DEFAULT_TIMEFRAME)
    size     = float(data.get("size", settings.DEFAULT_POSITION_SIZE))

    # Friendly display name for well-known strategy+pair combos
    _PRO_NAMES = {
        ("rsi_swing", "BTC/USDT", "1m"): "BTCUSDT PRO_1",
    }
    raw_name = f"{strategy}_{symbol}_{timeframe}"
    bot_name = _PRO_NAMES.get((strategy, symbol, timeframe), raw_name)

    if bot_name in active_bots:
        return jsonify({"error": f"Bot '{bot_name}' already running"}), 400

    try:
        trader = Trader(
            strategy_name=strategy,
            symbol=symbol,
            position_size=size,
            timeframe=timeframe,
        )

        def run_bot():
            trader.run()

        thread = threading.Thread(target=run_bot, daemon=True)
        thread.start()

        active_bots[bot_name] = {
            "trader": trader,
            "thread": thread,
            "started_at": datetime.utcnow().isoformat(),
            "strategy": strategy,
            "symbol": symbol,
            "timeframe": timeframe,
            "size": size,
        }

        return jsonify({"message": f"Bot '{bot_name}' started", "name": bot_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/bot/stop", methods=["POST"])
def api_bot_stop():
    data = request.json
    bot_name = data.get("name")

    if bot_name not in active_bots:
        return jsonify({"error": f"Bot '{bot_name}' not found"}), 404

    active_bots[bot_name]["trader"].stop()
    del active_bots[bot_name]
    return jsonify({"message": f"Bot '{bot_name}' stopped"})


@app.route("/api/bot/status")
def api_bot_status():
    bots = []
    for name, info in active_bots.items():
        trader = info["trader"]
        bots.append({
            "name": name,
            "strategy": info["strategy"],
            "symbol": info["symbol"],
            "timeframe": info.get("timeframe", "?"),
            "size": info["size"],
            "started_at": info["started_at"],
            "cycles": trader.cycle_count,
            "running": trader.running,
            "positions": trader.positions.get_open_count(),
        })
    return jsonify({"bots": bots})


# ─── API: Backtest ───────────────────────────────────────────────
@app.route("/api/backtest", methods=["POST"])
def api_run_backtest():
    data = request.json
    strategy_name = data.get("strategy", "macd")
    symbol = data.get("symbol", "BTC/USDT")
    timeframe = data.get("timeframe", "5m")
    limit = int(data.get("limit", 1000))

    try:
        # Fetch candles
        import ccxt
        import pandas as pd
        exchange_id = read_env().get("EXCHANGE_ID", "binance")
        exchange = getattr(ccxt, exchange_id)()
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

        # For arbitrage strategy, fetch ETH candles and compute ratio column
        if strategy_name == "arbitrage":
            eth_raw = exchange.fetch_ohlcv("ETH/USDT", timeframe=timeframe, limit=limit)
            eth_df = pd.DataFrame(eth_raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            min_len = min(len(df), len(eth_df))
            df = df.tail(min_len).reset_index(drop=True)
            eth_df = eth_df.tail(min_len).reset_index(drop=True)
            df["ratio"] = df["close"] / eth_df["close"]

        data_from = str(df["timestamp"].iloc[0]) if len(df) > 0 else ""
        data_to   = str(df["timestamp"].iloc[-1]) if len(df) > 0 else ""

        # Run backtest
        strategy = get_strategy(strategy_name)
        position_size = float(data.get("size", 10))
        engine = BacktestEngine(position_size=position_size)
        result = engine.run(strategy, df)

        metrics = result.metrics

        # Expectancy = avg_win * win_rate - avg_loss * loss_rate
        win_rate_dec = metrics.win_rate
        loss_rate_dec = 1.0 - win_rate_dec
        expectancy = (metrics.avg_win * win_rate_dec) + (metrics.avg_loss * loss_rate_dec)

        payload = {
            "strategy": result.strategy_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": limit,
            "position_size": position_size,
            "data_from": data_from,
            "data_to": data_to,
            "total_trades": metrics.total_trades,
            "winning_trades": metrics.winning_trades,
            "losing_trades": metrics.losing_trades,
            "win_rate": round(metrics.win_rate * 100, 2),
            "profit_factor": round(metrics.profit_factor, 4),
            "total_pnl": round(metrics.total_pnl, 4),
            "max_drawdown": round(metrics.max_drawdown_pct * 100, 2),
            "sharpe_ratio": round(metrics.sharpe_ratio, 4),
            "avg_win": round(metrics.avg_win, 4),
            "avg_loss": round(metrics.avg_loss, 4),
            "avg_trade_pnl": round(metrics.avg_trade_pnl, 4),
            "largest_win": round(metrics.largest_win, 4),
            "largest_loss": round(metrics.largest_loss, 4),
            "consecutive_wins": metrics.consecutive_wins,
            "consecutive_losses": metrics.consecutive_losses,
            "expectancy": round(expectancy, 4),
            "passes": metrics.passes_benchmarks(),
        }

        # Save to Firestore backtest_logs collection (server-side)
        try:
            db = _get_firestore()
            if db is not None:
                log_entry = {k: (bool(v) if hasattr(v, '__class__') and v.__class__.__name__ == 'bool_' else v)
                             for k, v in payload.items()}
                log_entry["run_at"] = datetime.utcnow().isoformat() + "Z"
                # Ensure all numeric values are plain Python types
                for k, v in log_entry.items():
                    if hasattr(v, 'item'):  # numpy scalar
                        log_entry[k] = v.item()
                db.collection("backtest_logs").add(log_entry)
        except Exception as fe:
            print(f"[Firestore] Log save failed: {fe}")

        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Backtest Logs ──────────────────────────────────────────
@app.route("/api/backtest/logs")
def api_backtest_logs():
    """Return the last 100 saved backtest runs from Firestore."""
    try:
        db = _get_firestore()
        if db is None:
            return jsonify({"logs": [], "error": "Firestore not available"}), 200
        docs = db.collection("backtest_logs").order_by("run_at", direction="DESCENDING").limit(100).stream()
        logs = []
        for doc in docs:
            entry = doc.to_dict()
            entry["id"] = doc.id
            logs.append(entry)
        return jsonify({"logs": logs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Trades History ─────────────────────────────────────────
@app.route("/api/trades")
def api_trades():
    try:
        trades = storage.get_recent_trades(limit=50)
        return jsonify({"trades": trades})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Settings ───────────────────────────────────────────────
@app.route("/api/benchmarks", methods=["GET"])
def api_get_benchmarks():
    env = read_env()
    return jsonify({
        "min_win_rate":      float(env.get("BACKTEST_MIN_WINRATE",       "0.55")) * 100,
        "min_profit_factor": float(env.get("BACKTEST_MIN_PROFIT_FACTOR", "1.5")),
        "max_drawdown":      float(env.get("BACKTEST_MAX_DRAWDOWN",      "0.20")) * 100,
        "min_trades":        int(env.get("BACKTEST_MIN_TRADES",          "100")),
        "min_sharpe":        float(env.get("BACKTEST_MIN_SHARPE",        "1.0")),
    })


@app.route("/api/benchmarks", methods=["POST"])
def api_save_benchmarks():
    data = request.json
    env  = read_env()
    env["BACKTEST_MIN_WINRATE"]       = str(round(float(data["min_win_rate"])      / 100, 4))
    env["BACKTEST_MIN_PROFIT_FACTOR"] = str(round(float(data["min_profit_factor"]),       4))
    env["BACKTEST_MAX_DRAWDOWN"]      = str(round(float(data["max_drawdown"])      / 100, 4))
    env["BACKTEST_MIN_TRADES"]        = str(int(data["min_trades"]))
    env["BACKTEST_MIN_SHARPE"]        = str(round(float(data["min_sharpe"]),              4))
    write_env(env)
    return jsonify({"message": "Benchmarks saved"})


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    env = read_env()
    # Mask API secret for display
    secret = env.get("EXCHANGE_API_SECRET", "")
    masked_secret = secret[:4] + "****" + secret[-4:] if len(secret) > 8 else "****"

    return jsonify({
        "exchange_id": env.get("EXCHANGE_ID", "binance"),
        "api_key": env.get("EXCHANGE_API_KEY", ""),
        "api_secret_masked": masked_secret,
        "sandbox": env.get("EXCHANGE_SANDBOX", "false"),
        "default_symbol": env.get("DEFAULT_SYMBOL", "BTC/USDT"),
        "position_size": env.get("DEFAULT_POSITION_SIZE", "1.0"),
        "quote_currency": env.get("QUOTE_CURRENCY", "USDC"),
        "max_position_size": env.get("MAX_POSITION_SIZE", "5"),
        "max_daily_loss": env.get("MAX_DAILY_LOSS", "2"),
        "max_drawdown_pct": env.get("MAX_DRAWDOWN_PCT", "30"),
    })


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    data = request.json
    env = read_env()

    updates = {
        "EXCHANGE_ID": data.get("exchange_id", env.get("EXCHANGE_ID", "binance")),
        "EXCHANGE_API_KEY": data.get("api_key", env.get("EXCHANGE_API_KEY", "")),
        "EXCHANGE_SANDBOX": data.get("sandbox", env.get("EXCHANGE_SANDBOX", "false")),
        "DEFAULT_SYMBOL": data.get("default_symbol", env.get("DEFAULT_SYMBOL", "BTC/USDT")),
        "DEFAULT_POSITION_SIZE": data.get("position_size", env.get("DEFAULT_POSITION_SIZE", "1.0")),
        "QUOTE_CURRENCY": data.get("quote_currency", env.get("QUOTE_CURRENCY", "USDC")),
        "MAX_POSITION_SIZE": data.get("max_position_size", env.get("MAX_POSITION_SIZE", "5")),
        "MAX_DAILY_LOSS": data.get("max_daily_loss", env.get("MAX_DAILY_LOSS", "2")),
        "MAX_DRAWDOWN_PCT": data.get("max_drawdown_pct", env.get("MAX_DRAWDOWN_PCT", "30")),
    }

    # Only update secret if a new one was provided (not the masked version)
    if data.get("api_secret") and "****" not in data["api_secret"]:
        updates["EXCHANGE_API_SECRET"] = data["api_secret"]

    env.update(updates)
    write_env(env)

    return jsonify({"message": "Settings saved"})


@app.route("/api/test-connection", methods=["POST"])
def api_test_connection():
    try:
        client = get_client()
        if not client:
            return jsonify({"error": "API keys not configured"}), 400

        price = client.get_price("BTC/USDT")
        raw = client.get_balance()
        # ccxt balance has a 'total' dict with {currency: amount} — safe to use directly
        totals = raw.get("total", {})
        non_zero = {k: round(float(v), 8) for k, v in totals.items()
                    if isinstance(v, (int, float)) and v > 0}

        return jsonify({
            "success": True,
            "btc_price": price,
            "balances": non_zero,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ─── API: Arbitrage Ratio ─────────────────────────────────────────
@app.route("/api/arbitrage/ratio")
def api_arbitrage_ratio():
    """Return live BTC/ETH price ratio and basic stats."""
    try:
        import ccxt
        exchange_id = read_env().get("EXCHANGE_ID", "binance")
        exchange = getattr(ccxt, exchange_id)()

        btc_ticker = exchange.fetch_ticker("BTC/USDT")
        eth_ticker = exchange.fetch_ticker("ETH/USDT")

        btc_price = float(btc_ticker.get("last", 0))
        eth_price = float(eth_ticker.get("last", 0))

        if eth_price <= 0:
            return jsonify({"error": "ETH price unavailable"}), 500

        ratio = btc_price / eth_price

        # Fetch recent hourly candles to compute SMA & z-score of ratio
        import pandas as pd
        import numpy as np
        avg_period = int(request.args.get("period", "30"))
        btc_ohlcv = exchange.fetch_ohlcv("BTC/USDT", timeframe="1h", limit=avg_period + 5)
        eth_ohlcv = exchange.fetch_ohlcv("ETH/USDT", timeframe="1h", limit=avg_period + 5)

        min_len = min(len(btc_ohlcv), len(eth_ohlcv))
        btc_closes = [c[4] for c in btc_ohlcv[-min_len:]]
        eth_closes = [c[4] for c in eth_ohlcv[-min_len:]]
        ratios = [b / e for b, e in zip(btc_closes, eth_closes) if e > 0]

        sma = float(np.mean(ratios[-avg_period:])) if len(ratios) >= avg_period else float(np.mean(ratios))
        std = float(np.std(ratios[-avg_period:])) if len(ratios) >= avg_period else float(np.std(ratios))
        zscore = (ratio - sma) / std if std > 0 else 0.0
        dev_pct = ((ratio - sma) / sma) * 100 if sma > 0 else 0.0

        # Action recommendation
        spike_pct = float(request.args.get("spike", "2.0"))
        if dev_pct >= spike_pct:
            action = "SWAP BTC→ETH"
            action_color = "sell"
        elif dev_pct <= -spike_pct:
            action = "SWAP ETH→BTC"
            action_color = "buy"
        else:
            action = "HOLD"
            action_color = "neutral"

        return jsonify({
            "btc_price": round(btc_price, 2),
            "eth_price": round(eth_price, 2),
            "ratio": round(ratio, 4),
            "sma": round(sma, 4),
            "std": round(std, 4),
            "zscore": round(zscore, 4),
            "dev_pct": round(dev_pct, 4),
            "action": action,
            "action_color": action_color,
            "period": avg_period,
            "history": [round(r, 4) for r in ratios[-avg_period:]],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/firestore-rules/status")
def api_firestore_rules_status():
    """Return the current Firestore rules deployment status."""
    return jsonify(_firestore_rules_status)


@app.route("/api/firestore-rules/deploy", methods=["POST"])
def api_firestore_rules_deploy():
    """Manually re-trigger Firestore rules deployment."""
    global _firestore_rules_status
    _firestore_rules_status = {"deployed": False, "message": "Deploying..."}
    threading.Thread(target=_auto_deploy_firestore_rules, daemon=True).start()
    return jsonify({"message": "Deployment triggered"})


# ─── Run ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  CRYPTO RBI BOT — Web Dashboard")
    print("  http://localhost:5050")
    print("=" * 50)
    app.run(debug=True, host="0.0.0.0", port=5050)
