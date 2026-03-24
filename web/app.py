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

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ─── Global state ─────────────────────────────────────────────────
active_bots: dict[str, dict] = {}  # name -> {trader, thread, started_at}
storage = DataStorage()


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

        balance = client.get_balance()
        non_zero = {}
        for coin, amounts in balance.items():
            total = amounts.get("total", 0)
            if total and total > 0:
                non_zero[coin] = {
                    "total": total,
                    "free": amounts.get("free", 0),
                    "used": amounts.get("used", 0),
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
        bid, ask = client.get_bid_ask(symbol)
        return jsonify({"symbol": symbol, "price": price, "bid": bid, "ask": ask})
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
    strategy = data.get("strategy", "macd")
    symbol = data.get("symbol", settings.DEFAULT_SYMBOL)
    size = float(data.get("size", settings.DEFAULT_POSITION_SIZE))
    bot_name = f"{strategy}_{symbol}"

    if bot_name in active_bots:
        return jsonify({"error": f"Bot '{bot_name}' already running"}), 400

    try:
        trader = Trader(
            strategy_name=strategy,
            symbol=symbol,
            position_size=size,
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

        # Run backtest
        strategy = get_strategy(strategy_name)
        engine = BacktestEngine(position_size=float(data.get("size", 10)))
        result = engine.run(strategy, df)

        metrics = result.metrics
        return jsonify({
            "strategy": result.strategy_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "total_trades": metrics.total_trades,
            "winning_trades": metrics.winning_trades,
            "losing_trades": metrics.losing_trades,
            "win_rate": round(metrics.win_rate * 100, 1),
            "profit_factor": round(metrics.profit_factor, 2),
            "total_pnl": round(metrics.total_pnl, 4),
            "max_drawdown": round(metrics.max_drawdown_pct * 100, 1),
            "avg_win": round(metrics.avg_win, 4),
            "avg_loss": round(metrics.avg_loss, 4),
            "passes": metrics.passes_benchmarks(),
        })
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
        balance = client.get_balance()
        non_zero = {k: v["total"] for k, v in balance.items() if v.get("total", 0) > 0}

        return jsonify({
            "success": True,
            "btc_price": price,
            "balances": non_zero,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ─── Run ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  CRYPTO RBI BOT — Web Dashboard")
    print("  http://localhost:5050")
    print("=" * 50)
    app.run(debug=True, host="0.0.0.0", port=5050)
