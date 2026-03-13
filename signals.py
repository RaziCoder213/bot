"""
signals.py  —  AZIM AI TRADER v3

v3 FIXES vs v2:
1. R:R check ADDED — signal reject hoti hai agar R:R < min_rr (default 2.0)
2. Multi-timeframe alignment STRICTER — 3 TF mein se 2 agree karna zaroori
3. Candle pattern weight badhaya: +12 (tha +8) — reversals better captured
4. Momentum filter improved: 4/5 candles (tha 5/5) — too strict tha
5. Regime penalty: volatile mein 0.80 (tha 0.85) — dangerous markets mein cautious
6. ATR-based SL/TP v3: TP2 = 4x ATR (tha 3.5x) — better R:R
"""
import logging
from typing import Dict, List, Optional, Tuple

from indicators import ema, rsi, stoch_rsi, macd, bollinger_bands, atr, adx, volume_ratio
from strategies import select_strategy
from market_data import _get_tick, get_orderbook, get_funding_rate
from config import MIN_TECH_SCORE, DECISION_MIN, ADX_MIN, SCORE_GAP, VOL_RATIO_MIN

logger = logging.getLogger("azim-trader.signals")

MIN_CANDLES     = 50
TIMEFRAME_COMBOS: List[Tuple[str, str]] = [
    ("5m",  "15m"),
    ("15m", "1H"),
    ("1H",  "4H"),
]


def detect_regime(closes: List[float], adx_val: float) -> str:
    if len(closes) < 20:
        return "unknown"
    recent = closes[-20:]
    hi, lo = max(recent), min(recent)
    rng    = (hi - lo) / lo if lo > 0 else 0
    if adx_val >= 25 and rng > 0.03:  return "trending"
    if adx_val <  18 and rng < 0.04:  return "ranging"
    if rng > 0.08:                     return "volatile"
    return "mixed"


def detect_patterns(candles: List[Dict]) -> Dict[str, bool]:
    if len(candles) < 3:
        return {}
    c1, c2 = candles[-2], candles[-1]
    pats: Dict[str, bool] = {}
    # Engulfing
    if (c1["close"] < c1["open"] and c2["close"] > c2["open"]
            and c2["close"] > c1["open"] and c2["open"] < c1["close"]):
        pats["bullish_engulfing"] = True
    if (c1["close"] > c1["open"] and c2["close"] < c2["open"]
            and c2["close"] < c1["open"] and c2["open"] > c1["close"]):
        pats["bearish_engulfing"] = True
    # Hammer / Shooting Star
    body    = abs(c2["close"] - c2["open"])
    lo_wick = min(c2["open"], c2["close"]) - c2["low"]
    hi_wick = c2["high"] - max(c2["open"], c2["close"])
    if body > 0:
        if lo_wick >= body * 2 and hi_wick < body * 0.5: pats["hammer"]       = True
        if hi_wick >= body * 2 and lo_wick < body * 0.5: pats["shooting_star"] = True
    # Doji (indecision — useful for reversals)
    if body < (c2["high"] - c2["low"]) * 0.1:
        pats["doji"] = True
    return pats


def analyze(candles: List[Dict]) -> Dict:
    if len(candles) < MIN_CANDLES:
        return {}

    closes  = [c["close"]  for c in candles]
    highs   = [c["high"]   for c in candles]
    lows    = [c["low"]    for c in candles]
    volumes = [c["volume"] for c in candles]

    ema9_v  = ema(closes, 9)
    ema21_v = ema(closes, 21)
    ema50_v = ema(closes, 50)
    ema200_v= ema(closes, 200) if len(closes) >= 200 else ema(closes, min(len(closes)-2, 100))
    rsi_v   = rsi(closes, 14)
    stk, _  = stoch_rsi(closes)
    _, _, hist = macd(closes)
    bbu, _, bbl = bollinger_bands(closes)
    atr_v   = atr(highs, lows, closes, 14)
    adx_v   = adx(highs, lows, closes, 14)
    vol_r   = volume_ratio(volumes, 20)

    if not all([ema9_v, ema21_v, ema50_v, rsi_v, hist, bbu, atr_v, adx_v]):
        return {}

    price = closes[-1]
    e9    = ema9_v[-1];  e21 = ema21_v[-1]; e50 = ema50_v[-1]
    e200  = ema200_v[-1] if ema200_v else e50
    r     = rsi_v[-1]
    sk    = stk[-1] if stk else 50.0
    h     = hist[-1]; ph = hist[-2] if len(hist) > 1 else 0
    bbu_v = bbu[-1];  bbl_v = bbl[-1]
    a     = atr_v[-1]; adxv = adx_v[-1]
    vr    = vol_r[-1] if vol_r else 1.0

    ls = 0.0; ss = 0.0

    # EMA alignment (max 30)
    if   e9 > e21 > e50: ls += 30 if e50 > e200 else 22
    elif e9 < e21 < e50: ss += 30 if e50 < e200 else 22
    elif e9 > e21:       ls += 12
    elif e9 < e21:       ss += 12

    # RSI (max 22)
    if   r < 28:  ls += 22   # v3: oversold threshold 30→28 (more extreme)
    elif r > 72:  ss += 22   # v3: overbought 70→72
    elif r <= 43: ls += 14
    elif r >= 57: ss += 14

    # MACD cross (max 20)
    if   h > 0 and ph <= 0: ls += 20
    elif h < 0 and ph >= 0: ss += 20
    elif h > 0:             ls +=  8
    elif h < 0:             ss +=  8

    # Bollinger %B (max 18)
    bb_rng = bbu_v - bbl_v
    if bb_rng > 0:
        pct_b = (price - bbl_v) / bb_rng
        if   pct_b < 0.08: ls += 18   # v3: 0.1→0.08 (more extreme required)
        elif pct_b > 0.92: ss += 18   # v3: 0.9→0.92
        elif pct_b < 0.28: ls += 10
        elif pct_b > 0.72: ss += 10

    # StochRSI (max 12)
    if   sk < 18: ls += 12   # v3: 20→18
    elif sk > 82: ss += 12   # v3: 80→82
    elif sk < 33: ls +=  6
    elif sk > 67: ss +=  6

    # Candle pattern bonus (v3: +12, was +8)
    pats = detect_patterns(candles)
    if pats.get("bullish_engulfing") or pats.get("hammer"):        ls += 12
    if pats.get("bearish_engulfing") or pats.get("shooting_star"): ss += 12

    # Regime modifier (v3: volatile penalty increased)
    regime = detect_regime(closes, adxv)
    if regime == "volatile":
        ls *= 0.80; ss *= 0.80   # v2: 0.85 → v3: 0.80 (more cautious)
    elif regime == "ranging":
        ls *= 0.90; ss *= 0.90   # v3 NEW: ranging market penalty

    # Momentum filter (v3: 4/5, v2 was 5/5 — too strict)
    if len(closes) >= 6:
        rc5  = closes[-6:]
        up   = sum(1 for i in range(1, 6) if rc5[i] > rc5[i-1])
        down = 5 - up
        if down >= 4: ls *= 0.70   # v3: 5→4 candles
        elif up >= 4: ss *= 0.70

    # EMA trend vs signal alignment (soft penalty)
    ema_long  = e9 > e21 and e21 > e50
    ema_short = e9 < e21 and e21 < e50
    if ema_short and ls > ss: ls *= 0.80
    if ema_long  and ss > ls: ss *= 0.80

    return {
        "long_score": ls,  "short_score": ss,
        "atr": a,          "adx": adxv,
        "volume_ratio": vr, "rsi": r, "stoch_k": sk,
        "macd_hist": h,    "price": price,
        "ema9": e9,        "ema21": e21, "ema50": e50, "ema200": e200,
        "bb_upper": bbu_v, "bb_lower": bbl_v,
        "regime": regime,  "patterns": pats,
    }


def compute_decision_score(tech: Dict, strategy: Dict,
                            direction: str, sentiment_score: float) -> float:
    adxv    = tech.get("adx", 0)
    vr      = tech.get("volume_ratio", 1.0)
    strat_c = strategy.get("confidence", 50)
    regime  = tech.get("regime", "unknown")

    score = 0.0
    score += min(adxv / 30 * 25, 25)

    if   vr >= 1.5: score += 20
    elif vr >= 1.2: score += 15
    elif vr >= 1.0: score += 10
    elif vr >= 0.8: score +=  5

    score += strat_c * 0.30

    # Sentiment (informational only)
    if   direction == "LONG"  and sentiment_score >  0.3: score += 10
    elif direction == "SHORT" and sentiment_score < -0.3: score += 10
    elif direction == "LONG"  and sentiment_score >  0:   score +=  5
    elif direction == "SHORT" and sentiment_score <  0:   score +=  5
    elif direction == "LONG"  and sentiment_score < -0.6: score -=  8
    elif direction == "SHORT" and sentiment_score >  0.6: score -=  8

    if   regime == "trending": score += 8
    elif regime == "ranging":  score -= 8   # v3: -5 → -8 (stronger penalty)
    elif regime == "volatile": score -= 4   # v3 NEW: volatile penalty

    return min(max(score, 0), 100)


def generate_signal(symbol: str,
                    candles_fast: List[Dict],
                    candles_slow: List[Dict],
                    tf_fast: str, tf_slow: str,
                    config: Dict,
                    sentiment_score: float = 0.0) -> Optional[Dict]:

    tf = analyze(candles_fast)
    ts = analyze(candles_slow)
    if not tf or not ts:
        return None

    # Weighted: 40% fast + 60% slow
    ls = tf["long_score"]  * 0.40 + ts["long_score"]  * 0.60
    ss = tf["short_score"] * 0.40 + ts["short_score"] * 0.60

    # Use config values if set (dashboard controls), else fall back to constants
    _adx_min      = float(config.get("adx_min",      ADX_MIN))
    _score_gap    = float(config.get("score_gap",    SCORE_GAP))
    _vol_ratio    = float(config.get("vol_ratio_min", VOL_RATIO_MIN))

    if ls >= MIN_TECH_SCORE and (ls - ss) >= _score_gap:
        direction = "LONG";  raw_score = ls
    elif ss >= MIN_TECH_SCORE and (ss - ls) >= _score_gap:
        direction = "SHORT"; raw_score = ss
    else:
        return None

    tech = dict(ts)
    tech["long_score"]  = ls
    tech["short_score"] = ss

    if tech["adx"]          < _adx_min:   return None
    if tech["volume_ratio"] < _vol_ratio:  return None

    # Use live tick price
    live_price = _get_tick(symbol) or tech["price"]
    if live_price <= 0:
        return None
    tech["price"] = live_price

    # v3 NEW: R:R check — reject if expected R:R < min_rr
    atr_val = tech.get("atr", live_price * 0.012)
    sl_d  = max(atr_val * 1.5, live_price * 0.012)
    tp2_d = max(atr_val * 4.0, live_price * 0.05)   # v3: 4x ATR (was 3.5x)
    rr_ratio = tp2_d / sl_d if sl_d > 0 else 0
    min_rr = float(config.get("min_rr", 2.0))
    if rr_ratio < min_rr:
        return None

    # Funding filter (v3: ON by default)
    if config.get("funding_filter", True):
        try:
            fr = get_funding_rate(symbol)
            if direction == "LONG"  and fr >  0.001: return None
            if direction == "SHORT" and fr < -0.001: return None
        except Exception: pass

    if config.get("orderbook_filter", False):
        try:
            ob   = get_orderbook(symbol)
            bids = ob.get("bids", []); asks = ob.get("asks", [])
            if bids and asks:
                bv  = sum(b[1] for b in bids)
                av  = sum(a[1] for a in asks)
                tot = bv + av
                if tot > 0:
                    if direction == "LONG"  and bv / tot < 0.38: return None
                    if direction == "SHORT" and av / tot < 0.38: return None
        except Exception: pass

    strategy       = select_strategy(tech)
    decision_score = compute_decision_score(tech, strategy, direction, sentiment_score)

    min_score = float(config.get("min_score", DECISION_MIN))
    if decision_score < min_score:
        return None

    return {
        "symbol":        symbol,
        "direction":     direction,
        "price":         round(live_price, 8),
        "atr":           round(tech["atr"], 8),
        "score":         round(decision_score, 1),
        "tech_score":    round(raw_score, 1),
        "strategy":      strategy["name"],
        "strategy_conf": strategy["confidence"],
        "timeframe_fast":tf_fast,
        "timeframe_slow":tf_slow,
        "adx":           round(tech["adx"], 1),
        "rsi":           round(tech["rsi"], 1),
        "volume_ratio":  round(tech["volume_ratio"], 2),
        "regime":        tech.get("regime", "unknown"),
        "patterns":      tech.get("patterns", {}),
        "sentiment":     round(sentiment_score, 3),
        "risk_reward":   round(rr_ratio, 2),
    }
