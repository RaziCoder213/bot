"""
core_engine.py — Centralized Engine and Logging for AZIM AI TRADER
This allows both Flask and Streamlit to share the same bot instance.
"""
import logging
import threading
import time
import collections
import re as _re
from datetime import datetime, timezone
from typing import Dict, List

from config import get_default_config
from database import StateDatabase
from market_data import (
    start_websocket, stop_websocket,
    fetch_all_usdt_perp_symbols, get_ws_price_count,
)
from monitor import TradeMonitor
from position_manager import capital_tier_cap, compute_position_size, compute_sl_tp
from scanner import MarketScanner
from trade_executor import simulate_entry
from notifier import notify_trade_open

# ── Logging Setup ─────────────────────────────────────────────────────────────
_log_buffer: collections.deque = collections.deque(maxlen=500)
_ANSI_RE = _re.compile(r'\[[0-9;]*m|\[[0-9;]*[A-Za-z]')

class _BufferHandler(logging.Handler):
    def emit(self, record):
        line = self.format(record)
        line = _ANSI_RE.sub('', line)   # strip ANSI color codes
        _log_buffer.appendleft(line)

_buf_handler = _BufferHandler()
_buf_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logging.getLogger().addHandler(_buf_handler)
logger = logging.getLogger("azim-trader")

# ── Engine Class ─────────────────────────────────────────────────────────────
class Engine:
    def __init__(self):
        self.lock           = threading.Lock()
        self.running        = False
        self.safe_mode      = False
        self.open_trades:   List[Dict] = []
        self.closed_trades: List[Dict] = []
        self.signals:       List[Dict] = []
        self.stats: Dict = {
            "net_pnl": 0.0, "signals_seen": 0,
            "wins": 0, "losses": 0,
            "strategy_performance": {}, "daily_pnl": {},
            "signals_rejected": 0, "signals_executed": 0,
        }
        self.config        = get_default_config()
        self.db            = StateDatabase()
        self._last_error   = ""
        self._zero_price_count = 0

        saved = self.db.load_state()
        self.open_trades   = saved.get("open_trades",   [])
        self.closed_trades = saved.get("closed_trades", [])
        self.signals       = saved.get("signals",       [])
        self.stats.update(saved.get("stats", {}))
        if saved.get("config"):
            self.config.update(saved["config"])
        self.safe_mode = saved.get("safe_mode", False)

        self.scanner = MarketScanner(self.get_config, self._on_signal, self.can_open_trade)
        self.monitor = TradeMonitor(self.get_open_trades_copy, self._on_trade_closed, self._on_trade_updated)
        self.db.start_autosave(self.snapshot)

    def snapshot(self) -> Dict:
        with self.lock:
            return {
                "open_trades":   list(self.open_trades),
                "closed_trades": list(self.closed_trades),
                "signals":       list(self.signals),
                "stats":         dict(self.stats),
                "config":        dict(self.config),
                "safe_mode":     self.safe_mode,
            }

    def get_config(self) -> Dict:
        with self.lock:
            return dict(self.config)

    def get_open_trades_copy(self) -> List[Dict]:
        with self.lock:
            return [dict(t) for t in self.open_trades]

    def _get_today_trades(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        count = 0
        for t in self.closed_trades:
            if t.get("open_time", "").startswith(today):
                count += 1
        for t in self.open_trades:
            if t.get("open_time", "").startswith(today):
                count += 1
        return count

    def can_open_trade(self) -> bool:
        with self.lock:
            return self._can_open_trade_nolock()

    def start(self):
        if self.running:
            return
        self.running = True
        self.scanner.start()
        self.monitor.start()
        if self.config.get("websocket_enabled", True):
            start_websocket(fetch_all_usdt_perp_symbols())
        logger.info("Engine started ✓")

    def stop(self):
        self.running = False
        self.scanner.stop()
        self.monitor.stop()
        stop_websocket()
        self.db.save_state(self.snapshot())
        logger.info("Engine stopped")

    def _can_open_trade_nolock(self) -> bool:
        if self.safe_mode or not self.running:
            return False
        wallet = float(self.config.get("wallet_balance", 0))
        cap    = min(int(self.config.get("max_trades", 3)), capital_tier_cap(wallet))
        if len(self.open_trades) >= cap:
            return False
        max_daily = int(self.config.get("max_daily_trades", 10))
        if self._get_today_trades() >= max_daily:
            return False
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_pnl = self.stats.get("daily_pnl", {}).get(today, 0.0)
        max_daily_loss = float(self.config.get("max_daily_loss_pct", 5.0)) / 100 * wallet
        if daily_pnl < -max_daily_loss:
            return False
        return True

    def _on_signal(self, signal: Dict):
        with self.lock:
            self.stats["signals_seen"] += 1
            price = float(signal.get("price", 0))

            if price > 0:
                sltp = compute_sl_tp(
                    price, signal["direction"],
                    float(signal.get("atr") or price * 0.012),
                    0.0001, self.config,
                )
                signal.update(sltp)
                if signal.get("tp2") and signal.get("sl"):
                    tp2, sl = signal["tp2"], signal["sl"]
                    if signal["direction"] == "LONG" and price > sl:
                        rr = (tp2 - price) / (price - sl)
                    elif signal["direction"] == "SHORT" and sl > price:
                        rr = (price - tp2) / (sl - price)
                    else:
                        rr = 0
                    signal["risk_reward"] = round(rr, 2)

            rec = {**signal, "time": datetime.now(timezone.utc).isoformat(), "executed": False}
            self.signals.insert(0, rec)
            if len(self.signals) > 500:
                self.signals = self.signals[:500]

            can_trade = self._can_open_trade_nolock()
            if not self.running or not can_trade:
                self.stats["signals_rejected"] = self.stats.get("signals_rejected", 0) + 1
                return

            if price <= 0:
                self._zero_price_count += 1
                if self._zero_price_count >= 5:
                    self.safe_mode = True
                    self._last_error = "Safe mode: 5 consecutive zero-price events"
                return
            else:
                self._zero_price_count = 0

            size = compute_position_size(self.config, self.stats, self.open_trades, signal)
            if size <= 0:
                self.stats["signals_rejected"] = self.stats.get("signals_rejected", 0) + 1
                return
            wallet_balance = self.config.get("wallet_balance", 0)
            rec_time = rec["time"]
            signal["leverage"] = int(self.config.get("leverage", 10))

        trade = simulate_entry(signal, size=size, wallet_balance=wallet_balance)
        if trade["entry_price"] <= 0:
            return

        with self.lock:
            for s in self.signals:
                if s.get("symbol") == signal.get("symbol") and s.get("time") == rec_time:
                    s["executed"] = True; break
            self.open_trades.append(trade)
            self.stats["signals_executed"] = self.stats.get("signals_executed", 0) + 1

        notify_trade_open(trade)
        logger.info(f"✅ Trade opened: {trade['symbol']} {trade['direction']} @ {trade['entry_price']}")

    def _on_trade_updated(self, trade: Dict):
        with self.lock:
            for i, t in enumerate(self.open_trades):
                if t["id"] == trade["id"]:
                    self.open_trades[i] = trade; break

    def _on_trade_closed(self, trade: Dict):
        with self.lock:
            self.open_trades   = [t for t in self.open_trades if t["id"] != trade["id"]]
            self.closed_trades.append(trade)
            pnl = float(trade.get("net_pnl", 0))
            self.stats["net_pnl"] += pnl
            if pnl >= 0: self.stats["wins"]   += 1
            else:        self.stats["losses"] += 1

            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            self.stats.setdefault("daily_pnl", {})
            self.stats["daily_pnl"][today] = self.stats["daily_pnl"].get(today, 0) + pnl
            self.config["wallet_balance"] = float(self.config.get("wallet_balance", 1000)) + pnl

            sp = self.stats["strategy_performance"]
            st = trade.get("strategy", "unknown")
            sp.setdefault(st, {"trades": 0, "net_pnl": 0.0, "wins": 0})
            sp[st]["trades"]  += 1
            sp[st]["net_pnl"] += pnl
            if pnl >= 0: sp[st]["wins"] += 1

# Shared instance
engine = Engine()
