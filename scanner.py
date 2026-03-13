"""
scanner.py  —  AZIM AI TRADER v3

v3 FIXES:
1. build_scan_universe() ko config pass kiya → symbol_mode support
2. MAX_SYMBOLS removed — ALL mode mein sab symbols scan hote hain (batches mein)
3. Batch processing: 200+ symbols ko 8 workers mein efficiently handle kiya
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional

from market_data import get_candles, build_scan_universe
from signals import generate_signal, TIMEFRAME_COMBOS
from sentiment import get_combined_sentiment
from notifier import notify_signal

logger = logging.getLogger("azim-trader.scanner")

MAX_WORKERS  = 8
MIN_CANDLES  = 60


class MarketScanner:
    def __init__(self, get_config_fn: Callable,
                 on_signal_fn: Callable,
                 can_open_fn: Callable):
        self._get_config  = get_config_fn
        self._on_signal   = on_signal_fn
        self._can_open    = can_open_fn
        self._running     = False
        self._thread: Optional[threading.Thread] = None
        self.last_scan:       Optional[float] = None
        self.symbols_scanned: int             = 0

    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Scanner started")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                config   = self._get_config()
                interval = int(config.get("scan_interval", 60))
                self._scan(config)
                self.last_scan = time.time()
            except Exception as e:
                logger.error(f"Scanner loop: {e}")
            deadline = time.time() + interval
            while self._running and time.time() < deadline:
                time.sleep(1)

    def _scan(self, config: Dict):
        # Pass config so build_scan_universe knows symbol_mode
        universe = build_scan_universe(config)
        symbols  = [s[0] for s in universe]
        self.symbols_scanned = len(symbols)
        can_trade = self._can_open()
        logger.info(f"Scanning {len(symbols)} symbols | mode={config.get('symbol_mode','ALL')} | can_trade={can_trade}")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(self._scan_symbol, sym, config): sym for sym in symbols}
            for future in as_completed(futures):
                if not self._running:
                    break
                try:
                    signal = future.result()
                    if signal:
                        logger.info(
                            f"✦ Signal: {signal['symbol']} {signal['direction']} "
                            f"score={signal['score']} [{signal['strategy']}]"
                        )
                        notify_signal(signal)
                        self._on_signal(signal)
                except Exception as e:
                    logger.error(f"Scan future: {e}")

    def _scan_symbol(self, symbol: str, config: Dict) -> Optional[Dict]:
        try:
            sent_score = get_combined_sentiment(symbol).get("score", 0.0)
        except Exception:
            sent_score = 0.0

        best: Optional[Dict] = None

        for tf_fast, tf_slow in TIMEFRAME_COMBOS:
            try:
                cf = get_candles(symbol, tf_fast, 150)
                cs = get_candles(symbol, tf_slow, 150)
                if len(cf) < MIN_CANDLES or len(cs) < MIN_CANDLES:
                    continue
                sig = generate_signal(symbol, cf, cs, tf_fast, tf_slow, config, sent_score)
                if sig and (best is None or sig["score"] > best["score"]):
                    best = sig
            except Exception as e:
                logger.debug(f"scan {symbol} {tf_fast}/{tf_slow}: {e}")

        return best
