"""
market_data.py  —  AZIM AI TRADER v3

v3 FIXES:
1. fetch_all_usdt_perp_symbols() ab Bitget API se LIVE symbols fetch karta hai
   — pehle sirf static list tha, ab 200+ real pairs milte hain
2. build_scan_universe() config ka symbol_mode check karta hai:
   - "ALL"    → Bitget se fetch kiye sab symbols
   - "CUSTOM" → sirf config["custom_symbols"] list
3. REST rate-limiter + fallback to static list if API fails
"""
import json
import logging
import threading
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import websocket as _wslib
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False

from config import BITGET_REST_URL, BITGET_WS_URL, FEAR_GREED_URL, SCAN_SYMBOLS

logger = logging.getLogger("azim-trader.market")

# ── REST rate limiter (max 18 req/s) ─────────────────────────────────────────
_rl_lock   = threading.Lock()
_rl_times  = deque()
_MAX_RPS   = 18

def _throttle():
    with _rl_lock:
        now = time.monotonic()
        while _rl_times and now - _rl_times[0] > 1.0:
            _rl_times.popleft()
        if len(_rl_times) >= _MAX_RPS:
            sleep = 1.0 - (now - _rl_times[0]) + 0.01
            if sleep > 0:
                time.sleep(sleep)
        _rl_times.append(time.monotonic())

# ── Tick price store ──────────────────────────────────────────────────────────
_tick_prices: Dict[str, float] = {}
_tick_ts:     Dict[str, float] = {}
_tick_lock    = threading.Lock()
TICK_STALE    = 10.0  # 10s — faster refresh for accurate live PnL

def _get_tick(symbol: str) -> Optional[float]:
    with _tick_lock:
        ts = _tick_ts.get(symbol)
        if ts and (time.time() - ts) < TICK_STALE:
            return _tick_prices.get(symbol)
    return None

def get_ws_price_count() -> int:
    with _tick_lock:
        return len(_tick_prices)

# ── Live symbols cache ────────────────────────────────────────────────────────
_live_symbols:      List[str] = []
_live_symbols_ts:   float     = 0
_live_symbols_lock  = threading.Lock()
_SYMBOLS_TTL        = 3600  # refresh every 1 hour

def fetch_all_usdt_perp_symbols() -> List[str]:
    """
    Fetch ALL active USDT-futures symbols from Bitget API.
    Cached for 1 hour. Falls back to static SCAN_SYMBOLS if API fails.
    """
    global _live_symbols, _live_symbols_ts
    with _live_symbols_lock:
        now = time.time()
        if _live_symbols and (now - _live_symbols_ts) < _SYMBOLS_TTL:
            return list(_live_symbols)

    try:
        _throttle()
        r = requests.get(
            f"{BITGET_REST_URL}/api/v2/mix/market/tickers",
            params={"productType": "USDT-FUTURES"},
            timeout=15,
            verify=False,
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        syms = []
        for item in data:
            sym = item.get("symbol", "")
            # Only active USDT pairs
            if sym.endswith("USDT") and item.get("open24h"):
                syms.append(sym)

        if len(syms) >= 10:
            # Sort by 24h volume descending (most liquid first)
            def vol_key(s):
                for item in data:
                    if item.get("symbol") == s:
                        try: return float(item.get("usdtVolume", 0))
                        except: return 0
                return 0
            syms.sort(key=vol_key, reverse=True)
            with _live_symbols_lock:
                _live_symbols    = syms
                _live_symbols_ts = time.time()
            logger.info(f"Fetched {len(syms)} live USDT-FUTURES symbols from Bitget")
            return list(syms)
    except Exception as e:
        logger.warning(f"fetch_all_usdt_perp_symbols failed: {e} — using static list")

    # Fallback to static list
    return list(SCAN_SYMBOLS)


def get_all_symbols_cached() -> List[str]:
    """Return cached live symbols (no network call if cache is fresh)."""
    return fetch_all_usdt_perp_symbols()


# ── Low-level HTTP ────────────────────────────────────────────────────────────
TIMEOUT    = 12
SSL_VERIFY = False

def _get(url: str, params=None, timeout: int = TIMEOUT):
    _throttle()
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=timeout, verify=SSL_VERIFY)
            r.raise_for_status()
            return r
        except Exception as exc:
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))

# ── Candles ───────────────────────────────────────────────────────────────────
_GRAN = {
    "1m":"1min","3m":"3min","5m":"5min","15m":"15min",
    "30m":"30min","1H":"1H","2H":"2H","4H":"4H","1D":"1Dutc",
}

def get_candles(symbol: str, timeframe: str = "15m", limit: int = 150) -> List[Dict]:
    try:
        gran = _GRAN.get(timeframe, "15min")
        r    = _get(f"{BITGET_REST_URL}/api/v2/mix/market/candles", params={
            "symbol": symbol, "productType": "USDT-FUTURES",
            "granularity": gran, "limit": str(limit),
        })
        raw = r.json().get("data") or []
        candles = []
        for c in raw:
            if not c or len(c) < 6:
                continue
            try:
                candles.append({
                    "time":   int(c[0]),
                    "open":   float(c[1]),
                    "high":   float(c[2]),
                    "low":    float(c[3]),
                    "close":  float(c[4]),
                    "volume": float(c[5]),
                })
            except (ValueError, TypeError):
                continue
        return sorted(candles, key=lambda x: x["time"])
    except Exception as e:
        logger.debug(f"get_candles {symbol}/{timeframe}: {e}")
        return []

# ── Prices ────────────────────────────────────────────────────────────────────
def get_current_price(symbol: str) -> float:
    p = _get_tick(symbol)
    if p:
        return p
    try:
        r = _get(f"{BITGET_REST_URL}/api/v2/mix/market/ticker",
                 params={"symbol": symbol, "productType": "USDT-FUTURES"})
        items = r.json().get("data", [])
        if items:
            p = float(items[0].get("lastPr", 0))
            if p > 0:
                with _tick_lock:
                    _tick_prices[symbol] = p
                    _tick_ts[symbol]     = time.time()
            return p
    except Exception as e:
        logger.debug(f"get_price {symbol}: {e}")
    return 0.0

def get_current_prices_batch(symbols: List[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    missing: List[str]    = []
    with _tick_lock:
        now = time.time()
        for s in symbols:
            ts = _tick_ts.get(s)
            if ts and (now - ts) < TICK_STALE and _tick_prices.get(s, 0) > 0:
                out[s] = _tick_prices[s]
            else:
                missing.append(s)
    for sym in missing:
        p = get_current_price(sym)
        if p > 0:
            out[sym] = p
    return out

# ── Market helpers ────────────────────────────────────────────────────────────
def get_orderbook(symbol: str, limit: int = 5) -> Dict:
    try:
        r    = _get(f"{BITGET_REST_URL}/api/v2/mix/market/merge-depth",
                    params={"symbol": symbol, "productType": "USDT-FUTURES", "limit": str(limit)})
        data = r.json().get("data", {})
        return {
            "bids": [[float(x[0]), float(x[1])] for x in data.get("bids", [])[:limit]],
            "asks": [[float(x[0]), float(x[1])] for x in data.get("asks", [])[:limit]],
        }
    except Exception as e:
        logger.debug(f"orderbook {symbol}: {e}")
        return {"bids": [], "asks": []}

def get_funding_rate(symbol: str) -> float:
    try:
        r    = _get(f"{BITGET_REST_URL}/api/v2/mix/market/current-fund-rate",
                    params={"symbol": symbol, "productType": "USDT-FUTURES"})
        data = r.json().get("data", [])
        return float(data[0].get("fundingRate", 0)) if data else 0.0
    except Exception as e:
        logger.debug(f"funding {symbol}: {e}")
        return 0.0

def get_fear_greed_index() -> Dict:
    try:
        r    = _get(FEAR_GREED_URL, timeout=8)
        item = r.json().get("data", [{}])[0]
        return {
            "value":          int(item.get("value", 50)),
            "classification": item.get("value_classification", "Neutral"),
        }
    except Exception:
        return {"value": 50, "classification": "Neutral"}

def build_scan_universe(config: Dict = None) -> List[Tuple[str, float]]:
    """
    Returns symbols to scan based on config:
    - symbol_mode = "ALL"    → All live Bitget USDT-futures (fetched from API)
    - symbol_mode = "CUSTOM" → Only custom_symbols from config
    - default                → All live symbols (same as ALL)
    """
    if config:
        mode = config.get("symbol_mode", "ALL")
        if mode == "CUSTOM":
            custom = config.get("custom_symbols", [])
            if custom:
                syms = [s.strip().upper() for s in custom if s.strip()]
                logger.info(f"Custom scan mode: {len(syms)} symbols")
                return [(sym, 1000 - i) for i, sym in enumerate(syms)]

    # ALL mode — fetch live from Bitget
    syms = fetch_all_usdt_perp_symbols()
    return [(sym, 1000 - i) for i, sym in enumerate(syms)]


# ── WebSocket ─────────────────────────────────────────────────────────────────
_ws_thread:  Optional[threading.Thread] = None
_ws_running: bool                       = False
_ws_obj                                 = None

def start_websocket(symbols: List[str]):
    global _ws_thread, _ws_running
    if not WS_AVAILABLE:
        logger.warning("websocket-client not installed — price updates via REST only")
        return
    _ws_running = True
    _ws_thread  = threading.Thread(target=_ws_loop, args=(symbols,), daemon=True)
    _ws_thread.start()
    logger.info(f"WebSocket thread started ({len(symbols)} symbols)")

def stop_websocket():
    global _ws_running, _ws_obj
    _ws_running = False
    if _ws_obj:
        try: _ws_obj.close()
        except: pass

def _ws_loop(symbols: List[str]):
    global _ws_obj
    while _ws_running:
        try:
            ws = _wslib.WebSocketApp(
                BITGET_WS_URL,
                on_open    = lambda w: _on_open(w, symbols),
                on_message = _on_message,
                on_error   = lambda w, e: logger.debug(f"WS error: {e}"),
                on_close   = lambda w, c, m: logger.debug("WS closed"),
            )
            _ws_obj = ws
            ws.run_forever(ping_interval=25, ping_timeout=15, reconnect=5)
        except Exception as e:
            logger.debug(f"WS loop: {e}")
        if _ws_running:
            time.sleep(5)

def _on_open(ws, symbols: List[str]):
    # Subscribe in chunks of 50 (Bitget limit per message)
    for i in range(0, len(symbols), 50):
        chunk = symbols[i:i+50]
        args  = [{"instType": "USDT-FUTURES", "channel": "ticker", "instId": s} for s in chunk]
        ws.send(json.dumps({"op": "subscribe", "args": args}))
    logger.info(f"WS subscribed {len(symbols)} symbols")

def _on_message(ws, message: str):
    try:
        data   = json.loads(message)
        action = data.get("action", "")
        if action in ("snapshot", "update"):
            for item in data.get("data", []):
                sym   = item.get("instId", "")
                price = float(item.get("lastPr", 0) or 0)
                if sym and price > 0:
                    with _tick_lock:
                        _tick_prices[sym] = price
                        _tick_ts[sym]     = time.time()
    except Exception:
        pass