"""
monitor.py  —  AZIM AI TRADER v2

FIXES vs original:
1. Prices come from WS tick cache first (truly tick-based) — REST only for stale
2. Trailing stop ATR recalc throttled to max 1x/30s per trade (was every 2s = ~1800 candle calls/hour)
3. Clean separation: _check() only checks prices; candle fetch only in _maybe_trail()
"""
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from market_data import get_current_prices_batch, get_candles
from trade_executor import close_trade, partial_tp1, apply_funding
from indicators import atr
from notifier import notify_trade_closed, notify_tp1

logger = logging.getLogger("azim-trader.monitor")

CHECK_INTERVAL   = 2    # seconds between price checks
TRAIL_INTERVAL   = 30   # seconds between ATR recalculations per trade


class TradeMonitor:
    def __init__(self, get_trades_fn: Callable,
                 on_closed_fn: Callable,
                 on_updated_fn: Callable):
        self._get_trades    = get_trades_fn
        self._on_closed     = on_closed_fn
        self._on_updated    = on_updated_fn
        self._running       = False
        self._thread: Optional[threading.Thread] = None
        self._trail_ts:     Dict[str, float] = {}   # trade_id → last trail update

    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Trade monitor started")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self._check()
            except Exception as e:
                logger.error(f"Monitor loop: {e}")
            time.sleep(CHECK_INTERVAL)

    def _check(self):
        trades = self._get_trades()
        if not trades:
            return

        symbols = list({t["symbol"] for t in trades})
        prices  = get_current_prices_batch(symbols)
        now     = datetime.now(timezone.utc)

        for trade in trades:
            sym   = trade["symbol"]
            price = prices.get(sym, 0)
            if price <= 0:
                continue

            try:
                opened  = datetime.fromisoformat(trade["open_time"])
                elapsed = (now - opened).total_seconds()
            except Exception:
                elapsed = 0

            trade    = apply_funding(trade, elapsed)
            dir_     = trade["direction"]
            sl       = float(trade.get("sl",  0) or 0)
            tp1      = float(trade.get("tp1", 0) or 0)
            tp2      = float(trade.get("tp2", 0) or 0)
            max_secs = float(trade.get("max_trade_hours", 48)) * 3600

            # Time-based exit
            if elapsed > max_secs:
                self._close(trade, price, "TIME_EXIT"); continue

            closed = False
            if dir_ == "LONG":
                if   tp2 > 0 and price >= tp2:                          self._close(trade, price, "TP2");  closed = True
                elif sl  > 0 and price <= sl:                           self._close(trade, price, "SL");   closed = True
                elif tp1 > 0 and price >= tp1 and not trade.get("tp1_hit"):
                    trade = partial_tp1(trade, price); self._on_updated(trade); notify_tp1(trade, price)
                    self._maybe_trail(trade, price); continue
            else:
                if   tp2 > 0 and price <= tp2:                          self._close(trade, price, "TP2");  closed = True
                elif sl  > 0 and price >= sl:                           self._close(trade, price, "SL");   closed = True
                elif tp1 > 0 and price <= tp1 and not trade.get("tp1_hit"):
                    trade = partial_tp1(trade, price); self._on_updated(trade); notify_tp1(trade, price)
                    self._maybe_trail(trade, price); continue

            if not closed:
                if trade.get("tp1_hit"):
                    self._maybe_trail(trade, price)
                self._on_updated(trade)

    def _close(self, trade: Dict, price: float, reason: str):
        c = close_trade(trade, price, reason)
        self._on_closed(c)
        notify_trade_closed(c)

    def _maybe_trail(self, trade: Dict, price: float):
        tid = trade.get("id", "")
        now = time.time()
        if now - self._trail_ts.get(tid, 0) < TRAIL_INTERVAL:
            return
        self._trail_ts[tid] = now
        self._update_trail(trade, price)
        self._on_updated(trade)

    def _update_trail(self, trade: Dict, price: float):
        try:
            candles = get_candles(trade["symbol"], "5m", 50)
            if len(candles) < 15:
                return
            atr_v = atr([c["high"] for c in candles],
                        [c["low"]  for c in candles],
                        [c["close"] for c in candles], 14)
            if not atr_v:
                return
            curr_atr = atr_v[-1]
            if trade["direction"] == "LONG":
                new_sl = price - curr_atr
                if new_sl > float(trade.get("sl", 0) or 0):
                    trade["sl"] = round(new_sl, 8); trade["trailing_sl"] = round(new_sl, 8)
            else:
                new_sl = price + curr_atr
                old_sl = float(trade.get("sl", float("inf")) or float("inf"))
                if new_sl < old_sl:
                    trade["sl"] = round(new_sl, 8); trade["trailing_sl"] = round(new_sl, 8)
        except Exception as e:
            logger.debug(f"trail update: {e}")
