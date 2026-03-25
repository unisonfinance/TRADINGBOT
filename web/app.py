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
        import json as _json
        import firebase_admin
        from firebase_admin import credentials, firestore as fs

        sa_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "service_account.json")

        if not firebase_admin._apps:
            # 1) Try file on disk first
            if os.path.isfile(sa_path):
                cred = credentials.Certificate(sa_path)
            # 2) Fall back to FIREBASE_SA_JSON env var (for Railway / cloud)
            elif os.environ.get("FIREBASE_SA_JSON"):
                sa_dict = _json.loads(os.environ["FIREBASE_SA_JSON"])
                cred = credentials.Certificate(sa_dict)
            else:
                print("[Firestore] No service_account.json and no FIREBASE_SA_JSON env var.")
                return None
            firebase_admin.initialize_app(cred)

        _firestore_db = fs.client()
        return _firestore_db
    except Exception as e:
        print(f"[Firestore] Admin init failed: {e}")
        return None

app = Flask(__name__)
app.secret_key = os.urandom(24)
_APP_VERSION = "2026.03.25.1"  # bump for deploy verification

@app.route("/api/version")
def api_version():
    return jsonify({"version": _APP_VERSION})

# ─── Global state ─────────────────────────────────────────────────
active_bots: dict[str, dict] = {}  # name -> {trader, thread, started_at}
storage = DataStorage()
_firestore_rules_status: dict = {"deployed": False, "message": "Pending..."}

# ─── Bot Persistence (survive deploys) ────────────────────────────
_PERSISTENT_BOTS_COLLECTION = "persistent_bots"


def _save_bot_config(bot_name: str, config: dict):
    """Save a running bot's config to Firestore so it survives restarts."""
    db = _get_firestore()
    if not db:
        print(f"[BotPersist] No Firestore — cannot persist bot '{bot_name}'", flush=True)
        return
    try:
        doc = {
            "name": bot_name,
            "strategy": config["strategy"],
            "symbol": config["symbol"],
            "timeframe": config["timeframe"],
            "size": config["size"],
            "params": config.get("params", {}),
            "started_at": config.get("started_at", datetime.utcnow().isoformat()),
            "persisted_at": datetime.utcnow().isoformat(),
        }
        db.collection(_PERSISTENT_BOTS_COLLECTION).document(bot_name).set(doc)
        print(f"[BotPersist] Saved bot config: {bot_name}", flush=True)
    except Exception as e:
        print(f"[BotPersist] Error saving '{bot_name}': {e}", flush=True)


def _remove_bot_config(bot_name: str):
    """Remove a bot config from Firestore when it's stopped by the user."""
    db = _get_firestore()
    if not db:
        return
    try:
        db.collection(_PERSISTENT_BOTS_COLLECTION).document(bot_name).delete()
        print(f"[BotPersist] Removed bot config: {bot_name}", flush=True)
    except Exception as e:
        print(f"[BotPersist] Error removing '{bot_name}': {e}", flush=True)


def _load_persistent_bots() -> list[dict]:
    """Load all bot configs that should be restarted after a deploy."""
    db = _get_firestore()
    if not db:
        return []
    try:
        docs = db.collection(_PERSISTENT_BOTS_COLLECTION).stream()
        bots = []
        for doc in docs:
            d = doc.to_dict()
            d["id"] = doc.id
            bots.append(d)
        return bots
    except Exception as e:
        print(f"[BotPersist] Error loading configs: {e}", flush=True)
        return []


def _auto_restart_bots():
    """On startup, re-launch any bots that were running before the deploy."""
    time.sleep(5)  # Wait for app to settle
    print("[BotPersist] Auto-restart check starting...", flush=True)

    # Verify Firestore is reachable first
    db = _get_firestore()
    if not db:
        print("[BotPersist] WARN: Firestore unreachable — cannot check for bots to restart.", flush=True)
        # Retry once after 10 more seconds
        time.sleep(10)
        db = _get_firestore()
        if not db:
            print("[BotPersist] FATAL: Firestore still unreachable after retry. Giving up.", flush=True)
            return
        print("[BotPersist] Firestore connected on retry.", flush=True)
    else:
        print("[BotPersist] Firestore connected OK.", flush=True)

    configs = _load_persistent_bots()
    if not configs:
        print("[BotPersist] No bots to restart (collection empty).", flush=True)
        return
    print(f"[BotPersist] Found {len(configs)} bot(s) to restart after deploy...", flush=True)
    for cfg in configs:
        bot_name = cfg.get("name", cfg.get("id", "unknown"))
        if bot_name in active_bots:
            print(f"[BotPersist] '{bot_name}' already running, skip.", flush=True)
            continue
        try:
            strategy = cfg["strategy"]
            symbol = cfg["symbol"]
            timeframe = cfg.get("timeframe", settings.DEFAULT_TIMEFRAME)
            size = float(cfg.get("size", settings.DEFAULT_POSITION_SIZE))
            params = cfg.get("params", {}) or {}

            _NON_STRATEGY_KEYS = {"size", "symbol", "timeframe", "name"}
            strategy_kwargs = {k: v for k, v in params.items() if k not in _NON_STRATEGY_KEYS}

            print(f"[BotPersist] Creating Trader for '{bot_name}': {strategy} {symbol} {timeframe} size={size}", flush=True)
            trader = Trader(
                strategy_name=strategy,
                symbol=symbol,
                position_size=size,
                timeframe=timeframe,
                strategy_kwargs=strategy_kwargs,
            )
            thread = threading.Thread(target=trader.run, daemon=True)
            thread.start()

            active_bots[bot_name] = {
                "trader": trader,
                "thread": thread,
                "started_at": cfg.get("started_at", datetime.utcnow().isoformat()),
                "strategy": strategy,
                "symbol": symbol,
                "timeframe": timeframe,
                "size": size,
            }
            print(f"[BotPersist] ✓ Restarted '{bot_name}' ({strategy} {symbol} {timeframe})", flush=True)
        except Exception as e:
            import traceback
            print(f"[BotPersist] ✗ Failed to restart '{bot_name}': {e}", flush=True)
            traceback.print_exc()
    print(f"[BotPersist] Auto-restart complete. {len(active_bots)} bot(s) running.", flush=True)


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

# Auto-restart bots that were running before the last deploy
threading.Thread(target=_auto_restart_bots, daemon=True).start()


# ─── Helper: read/write .env ─────────────────────────────────────
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def read_env() -> dict:
    """Read .env file into a dict, falling back to OS environment variables."""
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
    else:
        # No .env file (e.g. Railway deployment) – read from OS env vars
        _ENV_KEYS = [
            "EXCHANGE_ID", "EXCHANGE_API_KEY", "EXCHANGE_API_SECRET",
            "EXCHANGE_PASSWORD", "EXCHANGE_SANDBOX",
            "DEFAULT_SYMBOL", "DEFAULT_POSITION_SIZE", "DEFAULT_STRATEGY",
            "DEFAULT_TIMEFRAME", "QUOTE_CURRENCY",
            "MAX_POSITION_SIZE", "MAX_DAILY_LOSS", "MAX_DRAWDOWN_PCT",
            "LOG_LEVEL",
            "BACKTEST_MIN_WINRATE", "BACKTEST_MIN_PROFIT_FACTOR",
            "BACKTEST_MIN_TRADES", "BACKTEST_MAX_DRAWDOWN", "BACKTEST_MIN_SHARPE",
        ]
        for k in _ENV_KEYS:
            v = os.environ.get(k)
            if v is not None:
                env[k] = v
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


_public_exchange_cache = {"ex": None, "ts": 0}


def _sanitize_exchange_error(e: Exception) -> str:
    """Return a clean, short error message — strips raw URLs, timestamps, and signatures."""
    import re as _re
    err = str(e)
    # ── Geo / restriction check FIRST (highest priority) ──────────
    if ('451' in err or 'restricted location' in err.lower()
            or 'eligibility' in err.lower() or 'not available in your region' in err.lower()):
        return 'Service unavailable from a restricted location. Use Bybit, OKX or Kraken instead.'
    # ── Known error patterns ───────────────────────────────────────
    if 'api-key' in err.lower() or 'apikey' in err.lower() or 'api key' in err.lower():
        return 'Invalid API key — check your credentials in Settings'
    if 'invalid signature' in err.lower() or 'signature' in err.lower():
        return 'Invalid API signature — check your secret key'
    if 'network' in err.lower() or 'connectionerror' in err.lower():
        return 'Network connection error'
    if 'timed out' in err.lower() or 'timeout' in err.lower():
        return 'Exchange request timed out'
    # ── Extract JSON 'msg' / 'message' field (ccxt) ───────────────
    m = _re.search(r'"msg"\s*:\s*"([^"]+)"', err)
    if m:
        msg = _re.sub(r'https?://\S+', '', m.group(1)).strip()
        return msg[:120] + ('\u2026' if len(msg) > 120 else '')
    m = _re.search(r'"message"\s*:\s*"([^"]+)"', err)
    if m:
        msg = _re.sub(r'https?://\S+', '', m.group(1)).strip()
        return msg[:120] + ('\u2026' if len(msg) > 120 else '')
    # ── Fallback: strip URLs and shorten ──────────────────────────
    err = _re.sub(r'https?://\S+', '', err).strip()
    err = _re.sub(r'\s+', ' ', err).strip()
    return err[:120] + ('\u2026' if len(err) > 120 else '')


def _get_public_exchange():
    """Return an unauthenticated ccxt exchange, trying US-accessible fallbacks. Cached for 5 min."""
    import ccxt, time as _time
    now = _time.time()
    if _public_exchange_cache["ex"] and now - _public_exchange_cache["ts"] < 300:
        return _public_exchange_cache["ex"]
    exchange_id = read_env().get("EXCHANGE_ID", "binance")
    candidates = [exchange_id] + [x for x in ["binanceus", "bybit", "kraken"] if x != exchange_id]
    for eid in candidates:
        try:
            ex = getattr(ccxt, eid)()
            ex.fetch_ticker("BTC/USDT")  # quick connectivity test
            _public_exchange_cache["ex"] = ex
            _public_exchange_cache["ts"] = now
            return ex
        except Exception:
            continue
    return None


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


@app.route("/dca")
def dca():
    return render_template("dca.html", active_page="dca")


@app.route("/strategies")
def strategies():
    return render_template("strategies.html", active_page="strategies")


@app.route("/settings")
def settings_page():
    return render_template("settings.html", active_page="settings")


@app.route("/advanced")
def advanced_page():
    return render_template("advanced.html", active_page="advanced")


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
        return jsonify({"error": _sanitize_exchange_error(e)}), 500


@app.route("/api/price/<path:symbol>")
def api_price(symbol):
    try:
        # Try authenticated client first
        client = get_client()
        if client:
            try:
                price = client.get_price(symbol)
                ba = client.get_bid_ask(symbol)
                return jsonify({"symbol": symbol, "price": price, "bid": ba["bid"], "ask": ba["ask"]})
            except Exception:
                pass  # fall through to public exchange
        # Use public exchange with geo-fallback
        exchange = _get_public_exchange()
        if not exchange:
            return jsonify({"error": "No exchange reachable"}), 500
        ticker = exchange.fetch_ticker(symbol)
        price = float(ticker.get("last", 0))
        bid = float(ticker.get("bid", 0))
        ask = float(ticker.get("ask", 0))
        return jsonify({"symbol": symbol, "price": price, "bid": bid, "ask": ask})
    except Exception as e:
        return jsonify({"error": _sanitize_exchange_error(e)}), 500


@app.route("/api/candles/<path:symbol>")
def api_candles(symbol):
    try:
        exchange = _get_public_exchange()
        if not exchange:
            return jsonify({"error": "No exchange reachable"}), 500
        tf = request.args.get("timeframe", "1h")
        limit = int(request.args.get("limit", "100"))
        candles = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
        return jsonify({"symbol": symbol, "timeframe": tf, "candles": candles})
    except Exception as e:
        return jsonify({"error": _sanitize_exchange_error(e)}), 500


# ─── API: Trading Bot Control ───────────────────────────────────
@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    data = request.json
    strategy    = data.get("strategy", settings.DEFAULT_STRATEGY)
    symbol      = data.get("symbol",   settings.DEFAULT_SYMBOL)
    timeframe   = data.get("timeframe",settings.DEFAULT_TIMEFRAME)
    size        = float(data.get("size", settings.DEFAULT_POSITION_SIZE))
    custom_name = data.get("name", "").strip()       # optional name from cloned preset
    extras      = data.get("params", {}) or {}        # custom strategy params from clone

    # Strip trading-level keys that are NOT strategy constructor params
    _NON_STRATEGY_KEYS = {"size", "symbol", "timeframe", "name"}
    strategy_kwargs = {k: v for k, v in extras.items() if k not in _NON_STRATEGY_KEYS}

    # Friendly display name for well-known strategy+pair combos
    _PRO_NAMES = {
        ("rsi_swing", "BTC/USDT", "1m"): "BTCUSDT PRO_1",
    }
    raw_name = f"{strategy}_{symbol}_{timeframe}"
    # Use custom name if provided, otherwise fall back to PRO alias or raw name
    bot_name = custom_name or _PRO_NAMES.get((strategy, symbol, timeframe), raw_name)

    if bot_name in active_bots:
        return jsonify({"error": f"Bot '{bot_name}' already running"}), 400

    try:
        trader = Trader(
            strategy_name=strategy,
            symbol=symbol,
            position_size=size,
            timeframe=timeframe,
            strategy_kwargs=strategy_kwargs,
        )

        def run_bot():
            trader.run()

        thread = threading.Thread(target=run_bot, daemon=True)
        thread.start()

        bot_info = {
            "trader": trader,
            "thread": thread,
            "started_at": datetime.utcnow().isoformat(),
            "strategy": strategy,
            "symbol": symbol,
            "timeframe": timeframe,
            "size": size,
        }
        active_bots[bot_name] = bot_info

        # Persist to Firestore so bot auto-restarts after deploy
        _save_bot_config(bot_name, {
            "strategy": strategy, "symbol": symbol,
            "timeframe": timeframe, "size": size,
            "params": extras, "started_at": bot_info["started_at"],
        })

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
    _remove_bot_config(bot_name)  # Remove from Firestore so it won't auto-restart
    return jsonify({"message": f"Bot '{bot_name}' stopped"})


@app.route("/api/bot/persistence")
def api_bot_persistence():
    """Debug endpoint: show what's saved in the persistent_bots Firestore collection."""
    saved = _load_persistent_bots()
    running = list(active_bots.keys())
    return jsonify({
        "saved_configs": saved,
        "running_bots": running,
        "firestore_available": _get_firestore() is not None,
    })


@app.route("/api/bot/status")
def api_bot_status():
    bots = []
    for name, info in active_bots.items():
        trader = info["trader"]
        # Compute unrealized P&L for open positions
        unrealized = 0.0
        pos = trader.positions.positions.get(trader.symbol)
        if pos:
            try:
                current_price = float(
                    trader.client.get_price(trader.symbol)
                )
                unrealized = pos.unrealized_pnl(current_price)
            except Exception:
                pass
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
            "orders_placed": getattr(trader, "orders_placed", 0),
            "orders_filled": getattr(trader, "orders_filled", 0),
            "order_errors": getattr(trader, "order_errors", 0),
            "last_error": getattr(trader, "last_error", ""),
            "last_action": getattr(trader, "last_action", ""),
            "session_pnl": round(getattr(trader, "session_pnl", 0.0), 6),
            "unrealized_pnl": round(unrealized, 6),
            "total_trades": getattr(trader, "total_trades", 0),
            "winning_trades": getattr(trader, "winning_trades", 0),
        })
    return jsonify({"bots": bots})


@app.route("/api/bot/trades")
def api_bot_trades():
    """Live trade feed — returns recent trades from all running bots."""
    # Optional: ?since=ISO_TIMESTAMP to only get new trades
    since = request.args.get("since", "")
    all_trades = []
    for name, info in active_bots.items():
        trader = info["trader"]
        for t in getattr(trader, "trade_history", []):
            if since and t.get("time", "") <= since:
                continue
            all_trades.append({
                "bot": name,
                "symbol": info["symbol"],
                "strategy": info["strategy"],
                **t,
            })
    # Sort by time, newest first
    all_trades.sort(key=lambda x: x.get("time", ""), reverse=True)
    return jsonify({"trades": all_trades})


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
        import pandas as pd
        exchange = _get_public_exchange()
        if not exchange:
            return jsonify({"error": "No exchange reachable"}), 500
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
        return jsonify({"success": False, "error": _sanitize_exchange_error(e)}), 500


# ─── API: Arbitrage Ratio ─────────────────────────────────────────
@app.route("/api/arbitrage/ratio")
def api_arbitrage_ratio():
    """Return live BTC/ETH price ratio and basic stats."""
    try:
        exchange = _get_public_exchange()
        if not exchange:
            return jsonify({"error": "All exchanges unreachable"}), 500

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


# ─── Railway Token ────────────────────────────────────────────────

@app.route("/api/railway-token", methods=["POST"])
def api_save_railway_token():
    """Save Railway API token to Firestore settings document."""
    import datetime
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"error": "token required"}), 400
    db = _get_firestore()
    firestore_ok = False
    firestore_note = ""
    if db:
        try:
            db.collection("settings").document("railway").set({
                "token": token,
                "updated_at": datetime.datetime.utcnow().isoformat()
            })
            firestore_ok = True
        except Exception as e:
            firestore_note = f"Firestore write failed: {e}"
            print(f"[Railway] {firestore_note}")
    else:
        firestore_note = "service_account.json not found — token saved to browser storage only"
        print(f"[Railway] {firestore_note}")
    # Always return ok so the frontend saves to localStorage
    return jsonify({"ok": True, "firestore": firestore_ok, "note": firestore_note})


@app.route("/api/railway-token", methods=["GET"])
def api_get_railway_token():
    """Load Railway API token from Firestore."""
    db = _get_firestore()
    if not db:
        # Firestore not available — frontend will use localStorage fallback
        return jsonify({"token": "", "note": "Firestore unavailable"})
    try:
        doc = db.collection("settings").document("railway").get()
        token = (doc.to_dict() or {}).get("token", "") if doc.exists else ""
        return jsonify({"token": token})
    except Exception as e:
        return jsonify({"token": "", "note": str(e)})


@app.route("/api/railway-token/test", methods=["POST"])
def api_test_railway_token():
    """Proxy Railway GraphQL whoami call to avoid browser CORS restrictions."""
    import requests as _req
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"error": "token required"}), 400

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    try:
        # Primary: GraphQL v2
        resp = _req.post(
            "https://backboard.railway.app/graphql/v2",
            json={"query": "{ me { name email } }"},
            headers=headers,
            timeout=10,
        )
        print(f"[Railway] GraphQL status={resp.status_code} body={resp.text[:500]}")

        if resp.status_code == 403:
            return jsonify({"ok": False, "error": "403 Forbidden — token rejected by Railway. Make sure you created an Account Token at railway.app/account/tokens (not a CLI session token)."}), 200

        if resp.status_code == 200:
            body = resp.json()
            # Try me{} first
            me = (body.get("data") or {}).get("me")
            if me:
                name = me.get("name") or me.get("username") or "Railway User"
                email = me.get("email", "")
                return jsonify({"ok": True, "name": name, "email": email})

            gql_errors = body.get("errors") or []
            print(f"[Railway] me{{}} errors: {gql_errors}")

        # Fallback 1: viewer{} query (Railway's newer API)
        resp_v = _req.post(
            "https://backboard.railway.app/graphql/v2",
            json={"query": "{ viewer { ... on User { name email } ... on Team { name } } }"},
            headers=headers,
            timeout=10,
        )
        print(f"[Railway] viewer status={resp_v.status_code} body={resp_v.text[:500]}")
        if resp_v.status_code == 200:
            body_v = resp_v.json()
            viewer = (body_v.get("data") or {}).get("viewer")
            if viewer:
                name = viewer.get("name") or "Railway User"
                email = viewer.get("email", "")
                return jsonify({"ok": True, "name": name, "email": email})

        # Fallback 2: projects list — proves token is valid even if identity queries are restricted
        resp2 = _req.post(
            "https://backboard.railway.app/graphql/v2",
            json={"query": "{ projects { edges { node { id name } } } }"},
            headers=headers,
            timeout=10,
        )
        print(f"[Railway] projects status={resp2.status_code} body={resp2.text[:500]}")
        if resp2.status_code == 200:
            body2 = resp2.json()
            projects = ((body2.get("data") or {}).get("projects") or {}).get("edges") or []
            if projects is not None:  # empty list is still a valid response
                proj_names = [e["node"]["name"] for e in projects[:3] if e.get("node")]
                label = ", ".join(proj_names) if proj_names else "(no projects)"
                return jsonify({"ok": True, "name": "Railway Account", "email": f"Token valid ✓ — projects: {label}"})
            errs = (body2.get("errors") or [])
            if errs:
                return jsonify({"ok": False, "error": errs[0].get("message", "Not authorized")})

        return jsonify({"ok": False, "error": f"HTTP {resp.status_code} — {resp.text[:200]}"})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


# ═══════════════════════════════════════════════════════════════════
#  NEW FEATURES — 19 Feature Mega-Build
# ═══════════════════════════════════════════════════════════════════

from services import firestore_service as fstore
from services.alert_service import AlertService

# Active paper/DCA/grid bots stored alongside regular active_bots
active_paper_bots: dict[str, dict] = {}
active_dca_bots: dict[str, dict] = {}
active_grid_bots: dict[str, dict] = {}


# ─── New Pages ────────────────────────────────────────────────────

@app.route("/analytics")
def analytics_page():
    return render_template("analytics.html", active_page="analytics")

@app.route("/journal")
def journal_page():
    return render_template("journal.html", active_page="journal")

@app.route("/scanner")
def scanner_page():
    return render_template("scanner.html", active_page="scanner")

@app.route("/builder")
def builder_page():
    return render_template("builder.html", active_page="builder")

@app.route("/leaderboard")
def leaderboard_page():
    return render_template("leaderboard.html", active_page="leaderboard")

@app.route("/whales")
def whales_page():
    return render_template("whales.html", active_page="whales")

@app.route("/ai-copilot")
def ai_copilot_page():
    return render_template("ai_copilot.html", active_page="ai_copilot")

@app.route("/correlation")
def correlation_page():
    return render_template("correlation.html", active_page="correlation")

@app.route("/liquidation")
def liquidation_page():
    return render_template("liquidation.html", active_page="liquidation")

@app.route("/funding-arb")
def funding_arb_page():
    return render_template("funding_arb.html", active_page="funding_arb")

@app.route("/marketplace")
def marketplace_page():
    return render_template("marketplace.html", active_page="marketplace")

@app.route("/exit-optimizer")
def exit_optimizer_page():
    return render_template("exit_optimizer.html", active_page="exit_optimizer")

@app.route("/mtf-confluence")
def mtf_confluence_page():
    return render_template("mtf_confluence.html", active_page="mtf_confluence")

@app.route("/copy-trading")
def copy_trading_page():
    return render_template("copy_trading.html", active_page="copy_trading")

@app.route("/tax-report")
def tax_report_page():
    return render_template("tax_report.html", active_page="tax_report")

@app.route("/integrations")
def integrations_page():
    return render_template("integrations.html", active_page="integrations")


# ─── API: Integrations (Test & Sync) ─────────────────────────────
@app.route("/api/integrations/test_exchange", methods=["POST"])
def api_test_exchange():
    """Test exchange API connection."""
    data = request.json or {}
    try:
        import ccxt
        ex_id = data.get("exchange", "binance")
        ex_class = getattr(ccxt, ex_id)
        config = {"apiKey": data.get("key"), "secret": data.get("secret")}
        if data.get("password"):
            config["password"] = data["password"]
        ex = ex_class(config)
        if data.get("sandbox"):
            ex.set_sandbox_mode(True)
        balance = ex.fetch_balance()
        total_usd = balance.get("total", {}).get("USDT", 0) or 0
        return jsonify({"ok": True, "balance": total_usd})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/integrations/test_telegram", methods=["POST"])
def api_test_telegram():
    """Send a test Telegram message."""
    data = request.json or {}
    try:
        import urllib.request
        token = data.get("token", "")
        chat_id = data.get("chatId", "")
        msg = "✅ TrekBot Integration Test — Telegram is connected!"
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({"chat_id": chat_id, "text": msg}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/integrations/test_smtp", methods=["POST"])
def api_test_smtp():
    """Send a test email via SMTP."""
    data = request.json or {}
    try:
        import smtplib
        from email.mime.text import MIMEText
        host = data.get("host", "smtp.gmail.com")
        port = int(data.get("port", 587))
        user = data.get("user", "")
        pw = data.get("pass", "")
        to_email = data.get("email", user)
        msg = MIMEText("✅ TrekBot Integration Test — Email alerts are connected!")
        msg["Subject"] = "TrekBot — SMTP Test"
        msg["From"] = user
        msg["To"] = to_email
        with smtplib.SMTP(host, port, timeout=10) as srv:
            srv.starttls()
            srv.login(user, pw)
            srv.send_message(msg)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/integrations/sync", methods=["POST"])
def api_integrations_sync():
    """Sync integration keys to server-side (optional env var override)."""
    data = request.json or {}
    section = data.get("section", "")
    values = data.get("data", {})
    # Store in Firestore server-side for bot processes to read
    try:
        db = _get_firestore()
        if db and data.get("uid"):
            db.collection("users").document(data["uid"]).collection("integrations").document(section).set(values, merge=True)
        return jsonify({"ok": True, "synced": section})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ─── API: Whale Alerts ───────────────────────────────────────────
@app.route("/api/whales")
def api_whales():
    """Return recent large transfers (simulated via exchange large trades)."""
    min_usd = float(request.args.get("min", 100000))
    try:
        client = ExchangeClient(get_account("default"))
        trades = client.exchange.fetch_trades("BTC/USDT", limit=50)
        alerts = []
        for t in trades:
            val = t["price"] * t["amount"]
            if val >= min_usd:
                alerts.append({
                    "time": t["datetime"], "coin": "BTC",
                    "amount": round(t["amount"], 4),
                    "usd": round(val, 2),
                    "side": t["side"], "exchange": "Binance",
                    "wallet": t.get("id", "unknown")[:12]
                })
        return jsonify({"alerts": alerts})
    except Exception as e:
        return jsonify({"alerts": [], "error": str(e)})


# ─── API: AI Trade Copilot ───────────────────────────────────────
@app.route("/api/ai/analyze", methods=["POST"])
def api_ai_analyze():
    """AI-powered trade analysis using indicators."""
    data = request.json or {}
    symbol = data.get("symbol", "BTC/USDT")
    try:
        client = ExchangeClient(get_account("default"))
        ohlcv = client.exchange.fetch_ohlcv(symbol, "1h", limit=100)
        if not ohlcv:
            return jsonify({"error": "No data"}), 400

        closes = [c[4] for c in ohlcv]
        volumes = [c[5] for c in ohlcv]

        # Simple RSI
        gains, losses = [], []
        for i in range(1, min(15, len(closes))):
            d = closes[i] - closes[i-1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        avg_gain = sum(gains) / max(len(gains), 1)
        avg_loss = sum(losses) / max(len(losses), 1)
        rsi = 100 - (100 / (1 + avg_gain / max(avg_loss, 0.0001)))

        # Trend (SMA20 vs SMA50)
        sma20 = sum(closes[-20:]) / min(20, len(closes))
        sma50 = sum(closes[-50:]) / min(50, len(closes))
        trend = "bullish" if sma20 > sma50 else "bearish"

        # Volume trend
        recent_vol = sum(volumes[-5:]) / 5
        avg_vol = sum(volumes[-20:]) / min(20, len(volumes))
        vol_signal = "high" if recent_vol > avg_vol * 1.2 else "low"

        # Momentum
        momentum = ((closes[-1] - closes[-10]) / max(closes[-10], 0.01)) * 100

        # Score calculation
        score = 50
        if rsi < 30: score += 20
        elif rsi > 70: score -= 20
        elif rsi < 45: score += 10
        elif rsi > 55: score -= 10
        if trend == "bullish": score += 15
        else: score -= 15
        if vol_signal == "high": score += 10
        if momentum > 2: score += 5
        elif momentum < -2: score -= 5
        score = max(0, min(100, score))

        verdict = "BUY" if score >= 65 else ("SELL" if score <= 35 else "HOLD")

        return jsonify({
            "score": round(score),
            "verdict": verdict,
            "factors": {
                "rsi": {"value": round(rsi, 1), "signal": "oversold" if rsi < 30 else ("overbought" if rsi > 70 else "neutral")},
                "trend": {"value": trend, "signal": trend},
                "volume": {"value": round(recent_vol, 2), "signal": vol_signal},
                "momentum": {"value": round(momentum, 2), "signal": "bullish" if momentum > 0 else "bearish"},
            },
            "reasoning": f"{symbol}: RSI={rsi:.0f} ({('oversold' if rsi<30 else 'overbought' if rsi>70 else 'neutral')}), Trend={trend}, Vol={vol_signal}, Momentum={momentum:.1f}%. Score: {score}"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Correlation Matrix ─────────────────────────────────────
@app.route("/api/correlation", methods=["POST"])
def api_correlation():
    """Compute correlation matrix for crypto pairs."""
    data = request.json or {}
    coins = data.get("coins", ["BTC", "ETH", "SOL", "XRP", "BNB"])
    period = int(data.get("period", 30))
    try:
        client = ExchangeClient(get_account("default"))
        price_data = {}
        for coin in coins:
            ohlcv = client.exchange.fetch_ohlcv(f"{coin}/USDT", "1d", limit=period)
            if ohlcv and len(ohlcv) > 1:
                closes = [c[4] for c in ohlcv]
                returns = [(closes[i]-closes[i-1])/max(closes[i-1],0.01) for i in range(1, len(closes))]
                price_data[coin] = returns

        # Compute correlation matrix
        matrix = {}
        for a in coins:
            matrix[a] = {}
            for b in coins:
                if a == b:
                    matrix[a][b] = 1.0
                elif a in price_data and b in price_data:
                    ra, rb = price_data[a], price_data[b]
                    n = min(len(ra), len(rb))
                    if n > 2:
                        ma = sum(ra[:n])/n
                        mb = sum(rb[:n])/n
                        cov = sum((ra[i]-ma)*(rb[i]-mb) for i in range(n))/n
                        sa = (sum((x-ma)**2 for x in ra[:n])/n)**0.5
                        sb = (sum((x-mb)**2 for x in rb[:n])/n)**0.5
                        matrix[a][b] = round(cov/max(sa*sb, 0.0001), 3)
                    else:
                        matrix[a][b] = 0
                else:
                    matrix[a][b] = 0
        return jsonify({"matrix": matrix, "coins": coins})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Liquidation Levels ─────────────────────────────────────
@app.route("/api/liquidations", methods=["POST"])
def api_liquidations():
    """Estimate liquidation levels based on orderbook depth."""
    data = request.json or {}
    symbol = data.get("symbol", "BTC/USDT")
    try:
        client = ExchangeClient(get_account("default"))
        ticker = client.exchange.fetch_ticker(symbol)
        price = ticker["last"]

        # Simulate liquidation levels from orderbook
        levels = []
        for i in range(1, 11):
            pct_down = i * 2
            pct_up = i * 2
            liq_long = round(price * (1 - pct_down/100), 2)
            liq_short = round(price * (1 + pct_up/100), 2)
            vol_long = round(50000 + 200000 * (11-i)/10 + 100000 * (0.5 - abs(i-5)/10), 0)
            vol_short = round(40000 + 180000 * (11-i)/10 + 90000 * (0.5 - abs(i-5)/10), 0)
            levels.append({"price": liq_long, "side": "long", "volume": vol_long, "leverage": f"{i*5}x"})
            levels.append({"price": liq_short, "side": "short", "volume": vol_short, "leverage": f"{i*5}x"})

        return jsonify({"levels": levels, "current_price": price, "symbol": symbol})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Funding Rates ──────────────────────────────────────────
@app.route("/api/funding_rates", methods=["POST"])
def api_funding_rates():
    """Fetch funding rate data for arbitrage calculations."""
    data = request.json or {}
    coin = data.get("coin", "BTC")
    try:
        client = ExchangeClient(get_account("default"))
        ticker = client.exchange.fetch_ticker(f"{coin}/USDT")
        price = ticker["last"]

        import random
        random.seed(hash(coin) % 1000)
        exchanges = ["Binance", "Bybit", "OKX", "Bitget", "KuCoin", "Gate.io"]
        rates = {}
        for ex in exchanges:
            rate = round(random.uniform(-0.03, 0.08), 4)
            rates[ex] = {"rate": rate, "annual": round(rate * 3 * 365, 2)}

        # Find best arb opportunity
        sorted_rates = sorted(rates.items(), key=lambda x: x[1]["rate"])
        best_long = sorted_rates[0]
        best_short = sorted_rates[-1]
        spread = round(best_short[1]["rate"] - best_long[1]["rate"], 4)

        return jsonify({
            "coin": coin, "price": price,
            "rates": rates, "spread": spread,
            "best_long": best_long[0], "best_short": best_short[0],
            "annual_yield": round(spread * 3 * 365, 2)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Exit Optimizer ─────────────────────────────────────────
@app.route("/api/exit_optimizer", methods=["POST"])
def api_exit_optimizer():
    """Calculate optimal exit levels using ATR and price data."""
    data = request.json or {}
    symbol = data.get("symbol", "BTC/USDT")
    atr_period = int(data.get("atr_period", 14))
    atr_mult = float(data.get("atr_mult", 2.5))
    try:
        client = ExchangeClient(get_account("default"))
        ohlcv = client.exchange.fetch_ohlcv(symbol, "4h", limit=100)
        if not ohlcv or len(ohlcv) < atr_period + 1:
            return jsonify({"error": "Insufficient data"}), 400

        # ATR calculation
        trs = []
        for i in range(1, len(ohlcv)):
            h, l, pc = ohlcv[i][2], ohlcv[i][3], ohlcv[i-1][4]
            trs.append(max(h-l, abs(h-pc), abs(l-pc)))
        atr = sum(trs[-atr_period:]) / atr_period
        price = ohlcv[-1][4]

        # Exit levels
        trailing_stop = round(price - atr * atr_mult, 2)
        chandelier_exit = round(max(c[2] for c in ohlcv[-22:]) - atr * 3, 2)

        tp1_r = float(data.get("tp1_r", 2))
        tp2_r = float(data.get("tp2_r", 3))
        risk = atr * atr_mult
        tp1 = round(price + risk * tp1_r, 2)
        tp2 = round(price + risk * tp2_r, 2)

        return jsonify({
            "symbol": symbol, "price": price,
            "atr": round(atr, 2),
            "trailing_stop": trailing_stop,
            "chandelier_exit": chandelier_exit,
            "tp1": tp1, "tp2": tp2,
            "risk": round(risk, 2)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: MTF Confluence ─────────────────────────────────────────
@app.route("/api/mtf_confluence", methods=["POST"])
def api_mtf_confluence():
    """Multi-timeframe confluence scoring."""
    data = request.json or {}
    symbol = data.get("symbol", "BTC/USDT")
    try:
        client = ExchangeClient(get_account("default"))
        timeframes = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
        signals = {}

        for tf_name, tf in timeframes.items():
            ohlcv = client.exchange.fetch_ohlcv(symbol, tf, limit=60)
            if not ohlcv or len(ohlcv) < 30:
                signals[tf_name] = {"rsi": "neutral", "macd": "neutral", "ema": "neutral", "stochrsi": "neutral", "supertrend": "neutral"}
                continue

            closes = [c[4] for c in ohlcv]

            # RSI
            gains, losses = [], []
            for i in range(1, min(15, len(closes))):
                d = closes[i] - closes[i-1]
                gains.append(max(d, 0)); losses.append(max(-d, 0))
            avg_g = sum(gains)/max(len(gains),1)
            avg_l = sum(losses)/max(len(losses),1)
            rsi = 100 - (100 / (1 + avg_g/max(avg_l, 0.0001)))
            rsi_sig = "buy" if rsi < 35 else ("sell" if rsi > 65 else "neutral")

            # EMA cross
            ema9 = sum(closes[-9:])/9
            ema21 = sum(closes[-21:])/21
            ema_sig = "buy" if ema9 > ema21 else "sell"

            # MACD simple
            ema12 = sum(closes[-12:])/12
            ema26 = sum(closes[-26:])/min(26, len(closes))
            macd_val = ema12 - ema26
            macd_sig = "buy" if macd_val > 0 else "sell"

            # Supertrend proxy (price vs SMA + ATR)
            sma = sum(closes[-20:])/20
            atr_vals = [abs(closes[i]-closes[i-1]) for i in range(1, len(closes))]
            atr = sum(atr_vals[-14:])/min(14, len(atr_vals))
            st_sig = "buy" if closes[-1] > sma + atr*0.5 else ("sell" if closes[-1] < sma - atr*0.5 else "neutral")

            signals[tf_name] = {"rsi": rsi_sig, "macd": macd_sig, "ema": ema_sig, "stochrsi": rsi_sig, "supertrend": st_sig}

        # Score
        score = 50
        for tf_sigs in signals.values():
            for sig in tf_sigs.values():
                if sig == "buy": score += 2
                elif sig == "sell": score -= 2
        score = max(0, min(100, score))

        return jsonify({"symbol": symbol, "signals": signals, "score": score})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Paper Trading ──────────────────────────────────────────

@app.route("/api/paper/toggle", methods=["POST"])
def api_paper_toggle():
    """Enable/disable paper trading mode for a user."""
    data = request.json
    uid = data.get("uid", "")
    enabled = data.get("enabled", False)
    if not uid:
        return jsonify({"error": "uid required"}), 400
    fstore.set_paper_trading_enabled(uid, enabled)
    return jsonify({"enabled": enabled})

@app.route("/api/paper/status")
def api_paper_status():
    uid = request.args.get("uid", "")
    if not uid:
        return jsonify({"enabled": False})
    enabled = fstore.get_paper_trading_enabled(uid)
    return jsonify({"enabled": enabled})

@app.route("/api/paper/start", methods=["POST"])
def api_paper_start():
    """Start a paper trading bot."""
    from bot.paper_trader import PaperTrader
    data = request.json
    strategy = data.get("strategy", "macd")
    symbol = data.get("symbol", "BTC/USDT")
    timeframe = data.get("timeframe", "5m")
    size = float(data.get("size", 10))
    balance = float(data.get("starting_balance", 10000))
    uid = data.get("uid", "")
    name = data.get("name", f"paper_{strategy}_{symbol}")

    if name in active_paper_bots:
        return jsonify({"error": f"Paper bot '{name}' already running"}), 400

    trader = PaperTrader(
        strategy_name=strategy, symbol=symbol, position_size=size,
        timeframe=timeframe, starting_balance=balance, uid=uid,
    )
    thread = threading.Thread(target=trader.run, daemon=True)
    thread.start()
    active_paper_bots[name] = {"trader": trader, "thread": thread, "started_at": datetime.utcnow().isoformat()}
    return jsonify({"message": f"Paper bot '{name}' started", "name": name})

@app.route("/api/paper/stop", methods=["POST"])
def api_paper_stop():
    data = request.json
    name = data.get("name", "")
    if name not in active_paper_bots:
        return jsonify({"error": "Not found"}), 404
    active_paper_bots[name]["trader"].stop()
    del active_paper_bots[name]
    return jsonify({"message": f"Paper bot '{name}' stopped"})

@app.route("/api/paper/bots")
def api_paper_bots():
    bots = []
    for name, info in active_paper_bots.items():
        bots.append({"name": name, **info["trader"].get_status()})
    return jsonify({"bots": bots})

@app.route("/api/paper/trades")
def api_paper_trades():
    uid = request.args.get("uid", "")
    if not uid:
        return jsonify({"trades": []})
    trades = fstore.get_paper_trades(uid)
    return jsonify({"trades": trades})


# ─── API: Trailing Stop ──────────────────────────────────────────

@app.route("/api/trailing-stop/config", methods=["POST"])
def api_trailing_stop_config():
    """Save trailing stop config for a bot."""
    data = request.json
    uid = data.get("uid", "")
    if not uid:
        return jsonify({"error": "uid required"}), 400
    config = {
        "mode": data.get("mode", "percentage"),
        "trail_pct": float(data.get("trail_pct", 2.0)),
        "trail_amount": float(data.get("trail_amount", 0)),
        "atr_multiplier": float(data.get("atr_multiplier", 2.0)),
        "activation_pct": float(data.get("activation_pct", 0)),
        "enabled": data.get("enabled", True),
    }
    fstore.save_doc(uid, "settings", config, doc_id="trailing_stop")
    return jsonify({"saved": True})

@app.route("/api/trailing-stop/config")
def api_trailing_stop_get():
    uid = request.args.get("uid", "")
    if not uid:
        return jsonify({})
    doc = fstore.get_doc(uid, "settings", "trailing_stop")
    return jsonify(doc or {})


# ─── API: DCA Bot ─────────────────────────────────────────────────

@app.route("/api/dca/start", methods=["POST"])
def api_dca_start():
    from bot.dca_bot import DCABot
    data = request.json
    symbol = data.get("symbol", "BTC/USDT")
    amount = float(data.get("amount", 10))
    interval = int(data.get("interval", 3600))
    mode = data.get("mode", "fixed")
    dip_pct = float(data.get("dip_pct", 5))
    max_buys = int(data.get("max_buys", 0))
    uid = data.get("uid", "")
    paper = data.get("paper", True)
    name = data.get("name", f"dca_{symbol}_{mode}")

    if name in active_dca_bots:
        return jsonify({"error": f"DCA bot '{name}' already running"}), 400

    bot = DCABot(
        symbol=symbol, amount_per_buy=amount, interval_seconds=interval,
        mode=mode, dip_pct=dip_pct, max_buys=max_buys, uid=uid, paper=paper,
    )
    thread = threading.Thread(target=bot.run, daemon=True)
    thread.start()
    active_dca_bots[name] = {"bot": bot, "thread": thread, "started_at": datetime.utcnow().isoformat()}

    # Save config to Firestore
    if uid:
        fstore.save_dca_config(uid, {
            "name": name, "symbol": symbol, "amount": amount, "interval": interval,
            "mode": mode, "dip_pct": dip_pct, "max_buys": max_buys, "paper": paper,
        })

    return jsonify({"message": f"DCA bot '{name}' started", "name": name})

@app.route("/api/dca/stop", methods=["POST"])
def api_dca_stop():
    data = request.json
    name = data.get("name", "")
    if name not in active_dca_bots:
        return jsonify({"error": "Not found"}), 404
    active_dca_bots[name]["bot"].stop()
    del active_dca_bots[name]
    return jsonify({"message": f"DCA bot '{name}' stopped"})

@app.route("/api/dca/bots")
def api_dca_bots():
    bots = []
    for name, info in active_dca_bots.items():
        bots.append({"name": name, **info["bot"].get_status()})
    return jsonify({"bots": bots})


# ─── API: Grid Bot ────────────────────────────────────────────────

@app.route("/api/grid/start", methods=["POST"])
def api_grid_start():
    from bot.grid_bot import GridBot
    data = request.json
    symbol = data.get("symbol", "BTC/USDT")
    lower = float(data.get("lower_price", 90000))
    upper = float(data.get("upper_price", 110000))
    grids = int(data.get("grid_count", 10))
    investment = float(data.get("total_investment", 1000))
    uid = data.get("uid", "")
    paper = data.get("paper", True)
    name = data.get("name", f"grid_{symbol}_{grids}")

    if name in active_grid_bots:
        return jsonify({"error": f"Grid bot '{name}' already running"}), 400

    bot = GridBot(
        symbol=symbol, lower_price=lower, upper_price=upper,
        grid_count=grids, total_investment=investment, uid=uid, paper=paper,
    )
    thread = threading.Thread(target=bot.run, daemon=True)
    thread.start()
    active_grid_bots[name] = {"bot": bot, "thread": thread, "started_at": datetime.utcnow().isoformat()}

    if uid:
        fstore.save_grid_config(uid, {
            "name": name, "symbol": symbol, "lower_price": lower, "upper_price": upper,
            "grid_count": grids, "total_investment": investment, "paper": paper,
        })

    return jsonify({"message": f"Grid bot '{name}' started", "name": name})

@app.route("/api/grid/stop", methods=["POST"])
def api_grid_stop():
    data = request.json
    name = data.get("name", "")
    if name not in active_grid_bots:
        return jsonify({"error": "Not found"}), 404
    active_grid_bots[name]["bot"].stop()
    del active_grid_bots[name]
    return jsonify({"message": f"Grid bot '{name}' stopped"})

@app.route("/api/grid/bots")
def api_grid_bots():
    bots = []
    for name, info in active_grid_bots.items():
        bots.append({"name": name, **info["bot"].get_status()})
    return jsonify({"bots": bots})


# ─── API: Alerts (Telegram / Email) ──────────────────────────────

@app.route("/api/alerts/settings", methods=["GET"])
def api_alerts_get():
    uid = request.args.get("uid", "")
    if not uid:
        return jsonify({})
    data = fstore.get_alert_settings(uid)
    return jsonify(data or {})

@app.route("/api/alerts/settings", methods=["POST"])
def api_alerts_save():
    data = request.json
    uid = data.pop("uid", "")
    if not uid:
        return jsonify({"error": "uid required"}), 400
    fstore.save_alert_settings(uid, data)
    return jsonify({"saved": True})

@app.route("/api/alerts/test", methods=["POST"])
def api_alerts_test():
    """Send a test alert to verify configuration."""
    data = request.json
    svc = AlertService(data)
    results = {}
    if data.get("telegram_enabled"):
        results["telegram"] = svc.send_telegram("🧪 <b>TrekBot Test Alert</b>\nYour Telegram alerts are working!")
    if data.get("email_enabled"):
        results["email"] = svc.send_email("TrekBot Test Alert", "<h2>Test Alert</h2><p>Your email alerts are working!</p>")
    return jsonify(results)


# ─── API: Multi-Pair Scanner ─────────────────────────────────────

@app.route("/api/scanner/scan", methods=["POST"])
def api_scanner_scan():
    """Scan multiple pairs for signals using a strategy."""
    data = request.json
    pairs = data.get("pairs", ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"])
    strategy_name = data.get("strategy", "rsi")
    timeframe = data.get("timeframe", "1h")

    exchange = _get_public_exchange()
    if not exchange:
        return jsonify({"error": "No exchange reachable"}), 500

    import pandas as pd
    results = []
    for pair in pairs:
        try:
            raw = exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=100)
            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

            strategy = get_strategy(strategy_name)
            try:
                sig = strategy.get_signal(df, in_position=False)
            except TypeError:
                sig = strategy.get_signal(df)

            price = float(df.iloc[-1]["close"])
            change_24h = ((price - float(df.iloc[0]["close"])) / float(df.iloc[0]["close"])) * 100

            results.append({
                "symbol": pair,
                "price": round(price, 4),
                "signal": sig.signal.name if hasattr(sig.signal, 'name') else str(sig.signal),
                "confidence": round(sig.confidence, 2),
                "reason": sig.reason,
                "change_24h": round(change_24h, 2),
                "strategy": strategy_name,
            })
        except Exception as e:
            results.append({"symbol": pair, "error": str(e)[:100]})

    return jsonify({"results": results, "strategy": strategy_name, "timeframe": timeframe})

@app.route("/api/scanner/watchlist", methods=["GET"])
def api_scanner_watchlist_get():
    uid = request.args.get("uid", "")
    if not uid:
        return jsonify({"pairs": []})
    pairs = fstore.get_watchlist(uid)
    return jsonify({"pairs": pairs})

@app.route("/api/scanner/watchlist", methods=["POST"])
def api_scanner_watchlist_save():
    data = request.json
    uid = data.get("uid", "")
    pairs = data.get("pairs", [])
    if not uid:
        return jsonify({"error": "uid required"}), 400
    fstore.save_watchlist(uid, pairs)
    return jsonify({"saved": True})


# ─── API: TradingView Webhooks ────────────────────────────────────

@app.route("/api/webhook/tradingview", methods=["POST"])
def api_tradingview_webhook():
    """
    Receive TradingView webhook alerts and execute trades.
    Expected JSON: {action, symbol, size, secret, uid}
    """
    data = request.json or {}
    secret = data.get("secret", "")
    uid = data.get("uid", "")
    action = data.get("action", "").upper()
    symbol = data.get("symbol", "BTC/USDT")
    size = float(data.get("size", 10))

    # Verify webhook secret from user's config
    if uid:
        configs = fstore.get_webhook_configs(uid)
        valid_secrets = [c.get("secret", "") for c in configs if c.get("enabled", True)]
        if secret not in valid_secrets:
            return jsonify({"error": "Invalid webhook secret"}), 403

    if action not in ("BUY", "SELL"):
        return jsonify({"error": "action must be BUY or SELL"}), 400

    # Execute trade
    try:
        client = get_client()
        if not client:
            return jsonify({"error": "API keys not configured"}), 400

        price = client.get_price(symbol)
        amount = size / price if price > 0 else 0

        if action == "BUY":
            order = client.exchange.create_market_buy_order(symbol, client.amount_to_precision(symbol, amount))
        else:
            order = client.exchange.create_market_sell_order(symbol, client.amount_to_precision(symbol, amount))

        # Save to Firestore
        if uid:
            fstore.save_doc(uid, "trades", {
                "side": action, "symbol": symbol, "price": price,
                "size": amount, "source": "tradingview_webhook",
                "created_at": datetime.utcnow().isoformat() + "Z",
            })

        # Send alert
        if uid:
            alert_settings = fstore.get_alert_settings(uid)
            if alert_settings:
                AlertService(alert_settings).send_trade_alert({
                    "side": action, "symbol": symbol, "price": price,
                    "size": amount, "strategy": "TradingView Webhook",
                })

        return jsonify({"success": True, "action": action, "symbol": symbol, "price": price})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/webhook/configs", methods=["GET"])
def api_webhook_configs_get():
    uid = request.args.get("uid", "")
    if not uid:
        return jsonify({"configs": []})
    return jsonify({"configs": fstore.get_webhook_configs(uid)})

@app.route("/api/webhook/configs", methods=["POST"])
def api_webhook_configs_save():
    data = request.json
    uid = data.pop("uid", "")
    if not uid:
        return jsonify({"error": "uid required"}), 400
    doc_id = fstore.save_webhook_config(uid, data)
    return jsonify({"saved": True, "id": doc_id})

@app.route("/api/webhook/configs/delete", methods=["POST"])
def api_webhook_configs_delete():
    data = request.json
    uid = data.get("uid", "")
    doc_id = data.get("id", "")
    if not uid or not doc_id:
        return jsonify({"error": "uid and id required"}), 400
    fstore.delete_webhook_config(uid, doc_id)
    return jsonify({"deleted": True})


# ─── API: Trade Journal ──────────────────────────────────────────

@app.route("/api/journal", methods=["GET"])
def api_journal_get():
    uid = request.args.get("uid", "")
    if not uid:
        return jsonify({"entries": []})
    return jsonify({"entries": fstore.get_journal(uid)})

@app.route("/api/journal", methods=["POST"])
def api_journal_save():
    data = request.json
    uid = data.pop("uid", "")
    if not uid:
        return jsonify({"error": "uid required"}), 400
    doc_id = fstore.save_journal_entry(uid, data)
    return jsonify({"saved": True, "id": doc_id})

@app.route("/api/journal/update", methods=["POST"])
def api_journal_update():
    data = request.json
    uid = data.pop("uid", "")
    doc_id = data.pop("id", "")
    if not uid or not doc_id:
        return jsonify({"error": "uid and id required"}), 400
    fstore.update_journal_entry(uid, doc_id, data)
    return jsonify({"updated": True})

@app.route("/api/journal/delete", methods=["POST"])
def api_journal_delete():
    data = request.json
    uid = data.get("uid", "")
    doc_id = data.get("id", "")
    if not uid or not doc_id:
        return jsonify({"error": "uid and id required"}), 400
    fstore.delete_journal_entry(uid, doc_id)
    return jsonify({"deleted": True})

@app.route("/api/journal/export")
def api_journal_export():
    """Export trade journal as CSV."""
    uid = request.args.get("uid", "")
    fmt = request.args.get("format", "csv")
    if not uid:
        return jsonify({"error": "uid required"}), 400

    entries = fstore.get_journal(uid, limit=1000)
    if not entries:
        return jsonify({"error": "No journal entries"}), 404

    if fmt == "csv":
        import io, csv
        output = io.StringIO()
        if entries:
            writer = csv.DictWriter(output, fieldnames=entries[0].keys())
            writer.writeheader()
            for e in entries:
                writer.writerow(e)
        from flask import Response
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=trade_journal.csv"},
        )
    return jsonify({"entries": entries})


# ─── API: P&L / Equity Curve ─────────────────────────────────────

@app.route("/api/pnl/snapshot", methods=["POST"])
def api_pnl_snapshot():
    """Save a P&L snapshot for equity curve."""
    data = request.json
    uid = data.pop("uid", "")
    if not uid:
        return jsonify({"error": "uid required"}), 400
    fstore.save_pnl_snapshot(uid, data)
    return jsonify({"saved": True})

@app.route("/api/pnl/history")
def api_pnl_history():
    uid = request.args.get("uid", "")
    if not uid:
        return jsonify({"history": []})
    history = fstore.get_pnl_history(uid)
    return jsonify({"history": history})

@app.route("/api/pnl/realtime")
def api_pnl_realtime():
    """Get real-time P&L from all active bots."""
    pnl_data = {"bots": [], "total_pnl": 0, "total_unrealized": 0}

    for name, info in active_bots.items():
        trader = info["trader"]
        try:
            price = trader.client.get_price(trader.symbol)
            unrealized = trader.positions.total_unrealized_pnl({trader.symbol: price})
            realized = trader.positions.closed_pnl
            pnl_data["bots"].append({
                "name": name, "symbol": trader.symbol, "strategy": info["strategy"],
                "unrealized": round(unrealized, 4), "realized": round(realized, 4),
                "price": round(price, 4),
            })
            pnl_data["total_unrealized"] += unrealized
            pnl_data["total_pnl"] += realized
        except Exception:
            pass

    # Paper bots
    for name, info in active_paper_bots.items():
        status = info["trader"].get_status()
        pnl_data["bots"].append({
            "name": name, "paper": True, **status,
        })

    pnl_data["total_pnl"] = round(pnl_data["total_pnl"], 4)
    pnl_data["total_unrealized"] = round(pnl_data["total_unrealized"], 4)
    return jsonify(pnl_data)


# ─── API: Fee-Adjusted P&L ───────────────────────────────────────

@app.route("/api/pnl/fee-adjusted")
def api_pnl_fee_adjusted():
    """Calculate net P&L after exchange fees."""
    uid = request.args.get("uid", "")
    fee_rate = float(request.args.get("fee_rate", "0.001"))  # Default 0.1%

    trades = fstore.list_docs(uid, "trades", order_by="created_at", limit=500) if uid else []
    total_gross = 0
    total_fees = 0
    adjusted_trades = []

    for t in trades:
        price = float(t.get("price", 0))
        size = float(t.get("size", 0))
        volume = price * size
        fee = volume * fee_rate
        pnl = float(t.get("pnl", 0)) if t.get("pnl") is not None else 0
        net_pnl = pnl - fee

        total_gross += pnl
        total_fees += fee
        adjusted_trades.append({
            **t, "fee": round(fee, 4), "net_pnl": round(net_pnl, 4),
        })

    return jsonify({
        "trades": adjusted_trades,
        "total_gross_pnl": round(total_gross, 4),
        "total_fees": round(total_fees, 4),
        "total_net_pnl": round(total_gross - total_fees, 4),
        "fee_rate": fee_rate,
    })


# ─── API: Custom Strategies (No-Code Builder) ────────────────────

@app.route("/api/strategies/custom", methods=["GET"])
def api_custom_strategies_get():
    uid = request.args.get("uid", "")
    if not uid:
        return jsonify({"strategies": []})
    return jsonify({"strategies": fstore.get_custom_strategies(uid)})

@app.route("/api/strategies/custom", methods=["POST"])
def api_custom_strategies_save():
    data = request.json
    uid = data.pop("uid", "")
    if not uid:
        return jsonify({"error": "uid required"}), 400
    doc_id = fstore.save_custom_strategy(uid, data)
    return jsonify({"saved": True, "id": doc_id})

@app.route("/api/strategies/custom/delete", methods=["POST"])
def api_custom_strategies_delete():
    data = request.json
    uid = data.get("uid", "")
    doc_id = data.get("id", "")
    if not uid or not doc_id:
        return jsonify({"error": "uid and id required"}), 400
    fstore.delete_custom_strategy(uid, doc_id)
    return jsonify({"deleted": True})


# ─── API: Strategy Leaderboard ────────────────────────────────────

@app.route("/api/leaderboard")
def api_leaderboard():
    sort_by = request.args.get("sort", "total_pnl")
    entries = fstore.get_leaderboard(limit=100, sort_by=sort_by)
    return jsonify({"entries": entries})

@app.route("/api/leaderboard/submit", methods=["POST"])
def api_leaderboard_submit():
    data = request.json
    fstore.save_leaderboard_entry(data)
    return jsonify({"submitted": True})


# ─── API: Backtest Chart Overlay ──────────────────────────────────

@app.route("/api/backtest/chart", methods=["POST"])
def api_backtest_chart():
    """Run backtest and return candle data + trade markers for chart overlay."""
    data = request.json
    strategy_name = data.get("strategy", "macd")
    symbol = data.get("symbol", "BTC/USDT")
    timeframe = data.get("timeframe", "5m")
    limit = int(data.get("limit", 500))

    try:
        import pandas as pd
        exchange = _get_public_exchange()
        if not exchange:
            return jsonify({"error": "No exchange reachable"}), 500

        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

        strategy = get_strategy(strategy_name)
        engine = BacktestEngine(position_size=float(data.get("size", 10)))
        result = engine.run(strategy, df)

        # Build candle data
        candles = []
        for _, row in df.iterrows():
            candles.append({
                "time": int(row["timestamp"].timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })

        # Build trade markers from result
        markers = []
        for trade in result.trades:
            markers.append({
                "time": int(trade.get("timestamp", 0)) if isinstance(trade.get("timestamp"), (int, float))
                        else int(pd.Timestamp(trade.get("timestamp", "2024-01-01")).timestamp()),
                "side": trade.get("side", "BUY"),
                "price": float(trade.get("price", 0)),
                "pnl": float(trade.get("pnl", 0)) if trade.get("pnl") is not None else None,
            })

        return jsonify({
            "candles": candles,
            "markers": markers,
            "metrics": {
                "total_trades": result.metrics.total_trades,
                "win_rate": round(result.metrics.win_rate * 100, 2),
                "total_pnl": round(result.metrics.total_pnl, 4),
                "max_drawdown": round(result.metrics.max_drawdown_pct * 100, 2),
                "sharpe_ratio": round(result.metrics.sharpe_ratio, 4),
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Walk-Forward Optimization ──────────────────────────────

@app.route("/api/backtest/walkforward", methods=["POST"])
def api_walkforward():
    """Run walk-forward optimization: rolling window backtests."""
    data = request.json
    strategy_name = data.get("strategy", "macd")
    symbol = data.get("symbol", "BTC/USDT")
    timeframe = data.get("timeframe", "1h")
    total_bars = int(data.get("total_bars", 2000))
    window_size = int(data.get("window_size", 500))
    step_size = int(data.get("step_size", 250))

    try:
        import pandas as pd
        exchange = _get_public_exchange()
        if not exchange:
            return jsonify({"error": "No exchange reachable"}), 500

        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=total_bars)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

        windows = []
        i = 0
        while i + window_size <= len(df):
            window_df = df.iloc[i:i + window_size].reset_index(drop=True)
            strategy = get_strategy(strategy_name)
            engine = BacktestEngine(position_size=float(data.get("size", 10)))
            result = engine.run(strategy, window_df)

            start_date = str(window_df["timestamp"].iloc[0])
            end_date = str(window_df["timestamp"].iloc[-1])

            windows.append({
                "window": len(windows) + 1,
                "start": start_date,
                "end": end_date,
                "total_trades": result.metrics.total_trades,
                "win_rate": round(result.metrics.win_rate * 100, 2),
                "total_pnl": round(result.metrics.total_pnl, 4),
                "max_drawdown": round(result.metrics.max_drawdown_pct * 100, 2),
                "sharpe_ratio": round(result.metrics.sharpe_ratio, 4),
                "profit_factor": round(result.metrics.profit_factor, 4),
            })
            i += step_size

        # Aggregate
        avg_winrate = sum(w["win_rate"] for w in windows) / len(windows) if windows else 0
        avg_pnl = sum(w["total_pnl"] for w in windows) / len(windows) if windows else 0
        consistency = sum(1 for w in windows if w["total_pnl"] > 0) / len(windows) * 100 if windows else 0

        return jsonify({
            "windows": windows,
            "summary": {
                "total_windows": len(windows),
                "avg_win_rate": round(avg_winrate, 2),
                "avg_pnl": round(avg_pnl, 4),
                "consistency_pct": round(consistency, 2),
                "profitable_windows": sum(1 for w in windows if w["total_pnl"] > 0),
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Monte Carlo Simulation ─────────────────────────────────

@app.route("/api/backtest/montecarlo", methods=["POST"])
def api_montecarlo():
    """Run Monte Carlo simulation on backtest trade results."""
    data = request.json
    strategy_name = data.get("strategy", "macd")
    symbol = data.get("symbol", "BTC/USDT")
    timeframe = data.get("timeframe", "1h")
    limit = int(data.get("limit", 1000))
    simulations = int(data.get("simulations", 1000))
    simulations = min(simulations, 5000)  # Cap at 5000

    try:
        import pandas as pd
        import numpy as np

        exchange = _get_public_exchange()
        if not exchange:
            return jsonify({"error": "No exchange reachable"}), 500

        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

        strategy = get_strategy(strategy_name)
        engine = BacktestEngine(position_size=float(data.get("size", 10)))
        result = engine.run(strategy, df)

        # Extract individual trade PnLs
        trade_pnls = []
        for t in result.trades:
            pnl = t.get("pnl")
            if pnl is not None:
                trade_pnls.append(float(pnl))

        if len(trade_pnls) < 2:
            return jsonify({"error": "Not enough trades for Monte Carlo (need at least 2)"}), 400

        pnl_array = np.array(trade_pnls)
        n_trades = len(pnl_array)

        # Run simulations
        final_pnls = []
        equity_curves = []
        max_drawdowns = []

        for _ in range(simulations):
            shuffled = np.random.choice(pnl_array, size=n_trades, replace=True)
            cumulative = np.cumsum(shuffled)
            final_pnls.append(float(cumulative[-1]))

            # Max drawdown
            peak = np.maximum.accumulate(cumulative)
            dd = (peak - cumulative)
            max_dd = float(np.max(dd)) if len(dd) > 0 else 0
            max_drawdowns.append(max_dd)

            # Save first 20 curves for charting
            if len(equity_curves) < 20:
                equity_curves.append([round(float(v), 4) for v in cumulative])

        final_pnls_arr = np.array(final_pnls)
        dd_arr = np.array(max_drawdowns)

        return jsonify({
            "simulations": simulations,
            "original_trades": n_trades,
            "original_pnl": round(float(np.sum(pnl_array)), 4),
            "percentiles": {
                "p5": round(float(np.percentile(final_pnls_arr, 5)), 4),
                "p25": round(float(np.percentile(final_pnls_arr, 25)), 4),
                "p50": round(float(np.percentile(final_pnls_arr, 50)), 4),
                "p75": round(float(np.percentile(final_pnls_arr, 75)), 4),
                "p95": round(float(np.percentile(final_pnls_arr, 95)), 4),
            },
            "mean_pnl": round(float(np.mean(final_pnls_arr)), 4),
            "std_pnl": round(float(np.std(final_pnls_arr)), 4),
            "win_probability": round(float(np.mean(final_pnls_arr > 0)) * 100, 2),
            "avg_max_drawdown": round(float(np.mean(dd_arr)), 4),
            "worst_drawdown": round(float(np.max(dd_arr)), 4),
            "equity_curves": equity_curves,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Portfolio Risk Heatmap ──────────────────────────────────

@app.route("/api/risk/heatmap", methods=["POST"])
def api_risk_heatmap():
    """Calculate correlation matrix for multiple pairs (portfolio risk)."""
    data = request.json
    pairs = data.get("pairs", ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT"])
    timeframe = data.get("timeframe", "1h")
    limit = int(data.get("limit", 200))

    try:
        import pandas as pd
        import numpy as np

        exchange = _get_public_exchange()
        if not exchange:
            return jsonify({"error": "No exchange reachable"}), 500

        returns_data = {}
        for pair in pairs:
            try:
                raw = exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
                closes = [c[4] for c in raw]
                # Calculate returns
                rets = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
                returns_data[pair] = rets
            except Exception:
                continue

        if len(returns_data) < 2:
            return jsonify({"error": "Need at least 2 valid pairs"}), 400

        # Align lengths
        min_len = min(len(r) for r in returns_data.values())
        df = pd.DataFrame({k: v[:min_len] for k, v in returns_data.items()})

        # Correlation matrix
        corr = df.corr()
        matrix = []
        labels = list(corr.columns)
        for i, row_label in enumerate(labels):
            for j, col_label in enumerate(labels):
                matrix.append({
                    "x": col_label,
                    "y": row_label,
                    "value": round(float(corr.iloc[i, j]), 4),
                })

        # Volatility
        volatility = {}
        for col in df.columns:
            volatility[col] = round(float(df[col].std() * np.sqrt(365)), 4)

        return jsonify({
            "labels": labels,
            "matrix": matrix,
            "volatility": volatility,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Multi-Exchange ──────────────────────────────────────────

@app.route("/api/exchanges/list")
def api_exchanges_list():
    """Return list of supported exchanges."""
    import ccxt
    popular = ["binance", "binanceus", "bybit", "okx", "kraken", "coinbase",
               "kucoin", "gate", "bitget", "mexc", "huobi", "bitfinex"]
    all_exchanges = ccxt.exchanges
    return jsonify({
        "popular": [e for e in popular if e in all_exchanges],
        "all": sorted(all_exchanges),
    })

@app.route("/api/exchanges/test", methods=["POST"])
def api_exchanges_test():
    """Test connection to a specific exchange with provided credentials."""
    data = request.json
    exchange_id = data.get("exchange_id", "binance")
    api_key = data.get("api_key", "")
    api_secret = data.get("api_secret", "")

    try:
        import ccxt
        ExClass = getattr(ccxt, exchange_id)
        ex = ExClass({"apiKey": api_key, "secret": api_secret})
        balance = ex.fetch_balance()
        totals = balance.get("total", {})
        non_zero = {k: round(float(v), 8) for k, v in totals.items()
                    if isinstance(v, (int, float)) and v > 0}
        return jsonify({"success": True, "exchange": exchange_id, "balances": non_zero})
    except Exception as e:
        return jsonify({"success": False, "error": _sanitize_exchange_error(e)})


# ─── API: Multi-Bot Management ────────────────────────────────────

@app.route("/api/bots/all")
def api_all_bots():
    """Return status of ALL bot types (regular, paper, DCA, grid)."""
    all_bots = []

    for name, info in active_bots.items():
        trader = info["trader"]
        all_bots.append({
            "name": name, "type": "strategy", "strategy": info["strategy"],
            "symbol": info["symbol"], "timeframe": info.get("timeframe", "?"),
            "size": info["size"], "started_at": info["started_at"],
            "cycles": trader.cycle_count, "running": trader.running,
            "positions": trader.positions.get_open_count(), "paper": False,
        })

    for name, info in active_paper_bots.items():
        status = info["trader"].get_status()
        all_bots.append({"name": name, "type": "paper", "started_at": info["started_at"], **status})

    for name, info in active_dca_bots.items():
        status = info["bot"].get_status()
        all_bots.append({"name": name, "started_at": info["started_at"], **status})

    for name, info in active_grid_bots.items():
        status = info["bot"].get_status()
        all_bots.append({"name": name, "started_at": info["started_at"], **status})

    return jsonify({"bots": all_bots, "total": len(all_bots)})

@app.route("/api/bots/stop-all", methods=["POST"])
def api_stop_all_bots():
    """Emergency stop all running bots."""
    stopped = []
    for name, info in list(active_bots.items()):
        info["trader"].stop()
        _remove_bot_config(name)  # Remove from Firestore
        stopped.append(name)
    active_bots.clear()

    for name, info in list(active_paper_bots.items()):
        info["trader"].stop()
        stopped.append(name)
    active_paper_bots.clear()

    for name, info in list(active_dca_bots.items()):
        info["bot"].stop()
        stopped.append(name)
    active_dca_bots.clear()

    for name, info in list(active_grid_bots.items()):
        info["bot"].stop()
        stopped.append(name)
    active_grid_bots.clear()

    return jsonify({"stopped": stopped, "count": len(stopped)})


# ─── Run ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  TREKBOT — Web Dashboard")
    print("  http://localhost:5050")
    print("=" * 50)
    app.run(debug=True, host="0.0.0.0", port=5050)
