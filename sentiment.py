"""
sentiment.py  —  Informational only. Never blocks signals.
Cached 5 minutes per symbol to avoid hammering CryptoPanic API.
"""
import logging
import threading
import time
from typing import Dict

import requests
from config import CRYPTOPANIC_API_KEY, CRYPTOPANIC_URL

logger = logging.getLogger("azim-trader.sentiment")

BULL = ["surge","rally","adoption","etf","breakout","bullish","moon","pump",
        "growth","buy","accumulate","positive","gains","ath","upgrade","launch"]
BEAR = ["crash","ban","hack","lawsuit","dump","bearish","scam","sell",
        "fear","negative","decline","drop","warning","exploit","delisted","fraud"]

_cache: Dict[str, Dict] = {}
_lock   = threading.Lock()
CACHE_TTL = 300  # 5 min


def _cached(key: str, fn):
    with _lock:
        e = _cache.get(key)
        if e and time.time() - e["ts"] < CACHE_TTL:
            return e["data"]
    data = fn()
    with _lock:
        _cache[key] = {"ts": time.time(), "data": data}
    return data


def _neutral():
    return {"score": 0.0, "direction": "neutral", "bull": 0, "bear": 0}


def get_combined_sentiment(symbol: str) -> Dict:
    def _fetch():
        if not CRYPTOPANIC_API_KEY:
            return _neutral()
        try:
            coin = symbol.replace("USDT", "").upper()
            r    = requests.get(CRYPTOPANIC_URL, params={
                "auth_token": CRYPTOPANIC_API_KEY,
                "currencies": coin, "kind": "news", "public": "true",
            }, timeout=8)
            bull, bear = 0, 0
            for item in r.json().get("results", [])[:20]:
                v     = item.get("votes", {})
                bull += int(v.get("positive", 0)) * 5
                bear += int(v.get("negative", 0)) * 5
                title = item.get("title", "").lower()
                bull += sum(1 for w in BULL if w in title)
                bear += sum(1 for w in BEAR if w in title)
            tot = bull + bear
            sc  = (bull - bear) / tot if tot else 0.0
            return {
                "score":     round(sc, 3),
                "direction": "bullish" if sc > 0.1 else "bearish" if sc < -0.1 else "neutral",
                "bull":      bull, "bear": bear,
            }
        except Exception as e:
            logger.debug(f"sentiment {symbol}: {e}")
            return _neutral()

    return _cached(f"sent_{symbol}", _fetch)
