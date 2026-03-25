"""
Firestore Service — centralized CRUD for all Firestore collections.
All 19 features write/read through this module.

Collections:
  users/{uid}/settings/exchange        — exchange config
  users/{uid}/settings/alerts          — alert preferences (Telegram/Email)
  users/{uid}/settings/paper_trading   — paper trading toggle
  users/{uid}/trades                   — real trade history
  users/{uid}/paper_trades             — paper (simulated) trade history
  users/{uid}/backtests                — backtest results
  users/{uid}/bots                     — bot configurations
  users/{uid}/journal                  — trade journal entries
  users/{uid}/strategies               — custom (no-code) strategies
  users/{uid}/scanner_watchlist        — multi-pair scanner watchlist
  users/{uid}/webhooks                 — TradingView webhook configs
  users/{uid}/pnl_snapshots            — daily equity/P&L snapshots
  users/{uid}/dca_configs              — DCA bot configs
  users/{uid}/grid_configs             — Grid bot configs
  leaderboard                          — aggregated strategy performance
  backtest_logs                        — server-side backtest logs
"""
import os
import json
from datetime import datetime

_firestore_db = None


def _get_db():
    """Lazy-init Firestore client."""
    global _firestore_db
    if _firestore_db is not None:
        return _firestore_db
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore as fs

        sa_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "service_account.json",
        )

        if not firebase_admin._apps:
            if os.path.isfile(sa_path):
                cred = credentials.Certificate(sa_path)
            elif os.environ.get("FIREBASE_SA_JSON"):
                sa_dict = json.loads(os.environ["FIREBASE_SA_JSON"])
                cred = credentials.Certificate(sa_dict)
            else:
                return None
            firebase_admin.initialize_app(cred)

        _firestore_db = fs.client()
        return _firestore_db
    except Exception as e:
        print(f"[FirestoreService] init failed: {e}")
        return None


def _now_iso():
    return datetime.utcnow().isoformat() + "Z"


# ──────────────────────────────────────────────────────────────
# Generic helpers
# ──────────────────────────────────────────────────────────────

def _user_col(uid, collection):
    """Return a reference to users/{uid}/{collection}."""
    db = _get_db()
    if not db:
        return None
    return db.collection("users").document(uid).collection(collection)


def save_doc(uid, collection, data, doc_id=None):
    """Save a document to users/{uid}/{collection}. Auto-generates ID if none given."""
    col = _user_col(uid, collection)
    if not col:
        return None
    data["updated_at"] = _now_iso()
    if doc_id:
        col.document(doc_id).set(data, merge=True)
        return doc_id
    else:
        ref = col.add(data)
        return ref[1].id


def get_doc(uid, collection, doc_id):
    """Get a single document."""
    col = _user_col(uid, collection)
    if not col:
        return None
    doc = col.document(doc_id).get()
    if doc.exists:
        d = doc.to_dict()
        d["id"] = doc.id
        return d
    return None


def list_docs(uid, collection, order_by=None, direction="DESCENDING", limit=50):
    """List documents from users/{uid}/{collection}."""
    col = _user_col(uid, collection)
    if not col:
        return []
    query = col
    if order_by:
        from google.cloud.firestore_v1 import Query
        dir_enum = Query.DESCENDING if direction == "DESCENDING" else Query.ASCENDING
        query = query.order_by(order_by, direction=dir_enum)
    query = query.limit(limit)
    docs = query.stream()
    results = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        results.append(d)
    return results


def delete_doc(uid, collection, doc_id):
    """Delete a document."""
    col = _user_col(uid, collection)
    if not col:
        return False
    col.document(doc_id).delete()
    return True


def update_doc(uid, collection, doc_id, data):
    """Partial update (merge) a document."""
    col = _user_col(uid, collection)
    if not col:
        return False
    data["updated_at"] = _now_iso()
    col.document(doc_id).set(data, merge=True)
    return True


# ──────────────────────────────────────────────────────────────
# Alert Settings
# ──────────────────────────────────────────────────────────────

def save_alert_settings(uid, settings):
    """Save alert preferences (Telegram token, chat ID, email, toggles)."""
    return save_doc(uid, "settings", settings, doc_id="alerts")


def get_alert_settings(uid):
    """Load alert preferences."""
    return get_doc(uid, "settings", "alerts")


# ──────────────────────────────────────────────────────────────
# P&L Snapshots (equity curve)
# ──────────────────────────────────────────────────────────────

def save_pnl_snapshot(uid, snapshot):
    """Save a daily P&L snapshot for equity curve."""
    snapshot["created_at"] = _now_iso()
    return save_doc(uid, "pnl_snapshots", snapshot)


def get_pnl_history(uid, limit=365):
    """Get P&L history for equity chart."""
    return list_docs(uid, "pnl_snapshots", order_by="created_at", direction="ASCENDING", limit=limit)


# ──────────────────────────────────────────────────────────────
# Trade Journal
# ──────────────────────────────────────────────────────────────

def save_journal_entry(uid, entry):
    """Save a trade journal entry."""
    entry["created_at"] = _now_iso()
    return save_doc(uid, "journal", entry)


def get_journal(uid, limit=100):
    """Get journal entries."""
    return list_docs(uid, "journal", order_by="created_at", direction="DESCENDING", limit=limit)


def update_journal_entry(uid, doc_id, data):
    return update_doc(uid, "journal", doc_id, data)


def delete_journal_entry(uid, doc_id):
    return delete_doc(uid, "journal", doc_id)


# ──────────────────────────────────────────────────────────────
# Custom Strategies (No-Code Builder)
# ──────────────────────────────────────────────────────────────

def save_custom_strategy(uid, strategy):
    """Save a user-built strategy from the no-code builder."""
    strategy["created_at"] = strategy.get("created_at", _now_iso())
    return save_doc(uid, "strategies", strategy)


def get_custom_strategies(uid, limit=50):
    return list_docs(uid, "strategies", order_by="created_at", direction="DESCENDING", limit=limit)


def delete_custom_strategy(uid, doc_id):
    return delete_doc(uid, "strategies", doc_id)


# ──────────────────────────────────────────────────────────────
# Scanner Watchlist
# ──────────────────────────────────────────────────────────────

def save_watchlist(uid, watchlist):
    """Save the multi-pair scanner watchlist."""
    return save_doc(uid, "settings", {"pairs": watchlist}, doc_id="scanner_watchlist")


def get_watchlist(uid):
    doc = get_doc(uid, "settings", "scanner_watchlist")
    return doc.get("pairs", []) if doc else []


# ──────────────────────────────────────────────────────────────
# Webhook Configs
# ──────────────────────────────────────────────────────────────

def save_webhook_config(uid, config):
    config["created_at"] = config.get("created_at", _now_iso())
    return save_doc(uid, "webhooks", config)


def get_webhook_configs(uid, limit=20):
    return list_docs(uid, "webhooks", order_by="created_at", direction="DESCENDING", limit=limit)


def delete_webhook_config(uid, doc_id):
    return delete_doc(uid, "webhooks", doc_id)


# ──────────────────────────────────────────────────────────────
# DCA Bot Configs
# ──────────────────────────────────────────────────────────────

def save_dca_config(uid, config):
    config["created_at"] = config.get("created_at", _now_iso())
    return save_doc(uid, "dca_configs", config)


def get_dca_configs(uid, limit=20):
    return list_docs(uid, "dca_configs", order_by="created_at", direction="DESCENDING", limit=limit)


def delete_dca_config(uid, doc_id):
    return delete_doc(uid, "dca_configs", doc_id)


# ──────────────────────────────────────────────────────────────
# Grid Bot Configs
# ──────────────────────────────────────────────────────────────

def save_grid_config(uid, config):
    config["created_at"] = config.get("created_at", _now_iso())
    return save_doc(uid, "grid_configs", config)


def get_grid_configs(uid, limit=20):
    return list_docs(uid, "grid_configs", order_by="created_at", direction="DESCENDING", limit=limit)


def delete_grid_config(uid, doc_id):
    return delete_doc(uid, "grid_configs", doc_id)


# ──────────────────────────────────────────────────────────────
# Leaderboard (global collection, not per-user)
# ──────────────────────────────────────────────────────────────

def save_leaderboard_entry(entry):
    """Save/update a strategy performance entry to global leaderboard."""
    db = _get_db()
    if not db:
        return None
    entry["updated_at"] = _now_iso()
    doc_id = f"{entry.get('uid','anon')}_{entry.get('strategy','unknown')}"
    db.collection("leaderboard").document(doc_id).set(entry, merge=True)
    return doc_id


def get_leaderboard(limit=100, sort_by="total_pnl"):
    """Get the global strategy leaderboard sorted by performance."""
    db = _get_db()
    if not db:
        return []
    from google.cloud.firestore_v1 import Query
    docs = (
        db.collection("leaderboard")
        .order_by(sort_by, direction=Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    results = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        results.append(d)
    return results


# ──────────────────────────────────────────────────────────────
# Paper Trading
# ──────────────────────────────────────────────────────────────

def save_paper_trade(uid, trade):
    """Save a simulated paper trade."""
    trade["created_at"] = _now_iso()
    return save_doc(uid, "paper_trades", trade)


def get_paper_trades(uid, limit=100):
    return list_docs(uid, "paper_trades", order_by="created_at", direction="DESCENDING", limit=limit)


def get_paper_trading_enabled(uid):
    doc = get_doc(uid, "settings", "paper_trading")
    return doc.get("enabled", False) if doc else False


def set_paper_trading_enabled(uid, enabled):
    return save_doc(uid, "settings", {"enabled": enabled}, doc_id="paper_trading")
