"""
app.py — AZIM AI TRADER v3 (Flask Entry Point)
"""
import os
import time
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from config import APP_HOST, APP_PORT
from core_engine import engine, _log_buffer
from market_data import (
    build_scan_universe, get_orderbook,
    get_fear_greed_index, get_ws_price_count,
    get_current_prices_batch, get_all_symbols_cached,
)
from trade_executor import close_trade
from notifier import notify_trade_closed

app = Flask(__name__)
CORS(app)
START_TIME = time.time()

@app.get("/")
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")

@app.get("/api/status")
def status():
    s = engine.snapshot()
    total = s["stats"]["wins"] + s["stats"]["losses"]
    wr = round(s["stats"]["wins"] / total * 100, 1) if total else 0
    wallet = float(s["config"].get("wallet_balance", 1000))
    net_pnl = s["stats"].get("net_pnl", 0)
    pnl_pct = round(net_pnl / 1000 * 100, 2)
    return jsonify({
        "running": engine.running,
        "safe_mode": s["safe_mode"],
        "open": len(s["open_trades"]),
        "closed": len(s["closed_trades"]),
        "stats": s["stats"],
        "win_rate": wr,
        "uptime": round(time.time() - START_TIME),
        "pnl_pct": pnl_pct,
        "wallet": round(wallet, 2),
        "scanner": {
            "last_scan": engine.scanner.last_scan,
            "symbols_scanned": engine.scanner.symbols_scanned,
        },
        "ws_prices": get_ws_price_count(),
        "sentiment_ok": bool(__import__("config").CRYPTOPANIC_API_KEY),
        "last_error": engine._last_error,
        "signals_rejected": s["stats"].get("signals_rejected", 0),
        "signals_executed": s["stats"].get("signals_executed", 0),
    })

@app.post("/api/start")
def start_bot():
    engine.start()
    return jsonify({"ok": True, "running": True})

@app.post("/api/stop")
def stop_bot():
    engine.stop()
    return jsonify({"ok": True, "running": False})

@app.get("/api/open_trades")
def get_open_trades():
    return jsonify(engine.snapshot()["open_trades"])

@app.get("/api/closed_trades")
def get_closed_trades():
    return jsonify(engine.snapshot()["closed_trades"])

@app.get("/api/signals")
def get_signals():
    return jsonify(engine.snapshot()["signals"][:200])

@app.post("/api/close_trade")
def close_single():
    d = request.get_json(force=True)
    trade_id = d.get("trade_id")
    found = None
    with engine.lock:
        for t in engine.open_trades:
            if t["id"] == trade_id:
                found = dict(t)
                break
    if not found:
        return jsonify({"ok": False, "error": "not found"}), 404
    use_price = float(d.get("price", 0)) or found.get("current_price", found["entry_price"])
    c = close_trade(found, use_price, "MANUAL")
    engine._on_trade_closed(c)
    notify_trade_closed(c)
    return jsonify({"ok": True, "trade": c})

@app.post("/api/close_all_trades")
def close_all():
    with engine.lock:
        trades = [dict(t) for t in engine.open_trades]
    closed = []
    for t in trades:
        use_price = float(t.get("current_price") or t["entry_price"])
        c = close_trade(t, use_price, "MANUAL_ALL")
        engine._on_trade_closed(c)
        notify_trade_closed(c)
        closed.append(c)
    return jsonify({"ok": True, "closed": len(closed)})

@app.get("/api/config")
def get_config_ep():
    return jsonify(engine.get_config())

@app.post("/api/config")
def update_config():
    updates = request.get_json(force=True)
    with engine.lock:
        engine.config.update(updates)
    engine.db.save_state(engine.snapshot())
    return jsonify({"ok": True, "config": engine.get_config()})

@app.get("/api/logs")
def get_logs():
    n = int(request.args.get("n", 200))
    return jsonify(list(_log_buffer)[:n])

@app.get("/api/open_trades_with_pnl")
def get_open_trades_with_pnl():
    trades = engine.snapshot()["open_trades"]
    if not trades: return jsonify([])
    symbols = list({t["symbol"] for t in trades})
    prices = get_current_prices_batch(symbols)
    result = []
    for t in trades:
        trade = dict(t)
        cur = prices.get(t["symbol"], 0)
        trade["current_price"] = cur
        if cur > 0 and t.get("entry_price", 0) > 0:
            entry = float(t["entry_price"])
            margin = float(t.get("size", 0))
            leverage = float(t.get("leverage", 10))
            contracts = float(t.get("contracts", 0))
            dirn = 1 if t["direction"] == "LONG" else -1
            if contracts <= 0: contracts = (margin * leverage) / entry
            raw_pnl = (cur - entry) * contracts * dirn
            pnl_pct = (raw_pnl / margin * 100) if margin > 0 else 0
            trade["unrealized_pnl"] = round(raw_pnl, 4)
            trade["unrealized_pnl_pct"] = round(pnl_pct, 2)
        result.append(trade)
    return jsonify(result)

@app.get("/api/strategy_performance")
def strategy_perf():
    perf = engine.snapshot()["stats"].get("strategy_performance", {})
    result = {}
    for name, d in perf.items():
        total = d.get("trades", 0)
        wins = d.get("wins", 0)
        result[name] = {
            **d,
            "win_rate": round(wins / total * 100, 1) if total else 0,
            "avg_pnl": round(d.get("net_pnl", 0) / total, 2) if total else 0,
        }
    return jsonify(result)

@app.get("/api/fear_greed")
def fear_greed():
    return jsonify(get_fear_greed_index())

if __name__ == "__main__":
    app.run(host=APP_HOST, port=APP_PORT, debug=False, threaded=True)
