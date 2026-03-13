"""
strategies.py  —  AZIM AI TRADER v3

v3 FIXES:
1. Trend Continuation: ADX threshold 25→22 (slightly lower for crypto)
2. Volume Breakout: vol_ratio threshold 1.4→1.3 (slight easing)
3. NEW strategy: "Strong Trend" for very high ADX (>35) — highest confidence
4. Confidence values calibrated for better position sizing
"""
from typing import Dict


def select_strategy(indicators: Dict) -> Dict:
    adx_val   = indicators.get("adx",          0)
    macd_hist = indicators.get("macd_hist",    0)
    rsi_val   = indicators.get("rsi",          50)
    stoch_k   = indicators.get("stoch_k",      50)
    vol_ratio = indicators.get("volume_ratio", 1.0)
    regime    = indicators.get("regime",       "unknown")

    # v3 NEW: Strong Trend — highest priority, highest confidence
    if adx_val >= 35 and regime == "trending":
        return {"name": "Strong Trend", "confidence": min(int(adx_val / 40 * 100), 96)}

    if adx_val >= 22:   # v2: 25 → v3: 22
        return {"name": "Trend Continuation", "confidence": min(int(adx_val / 50 * 100), 92)}

    if abs(macd_hist) > 0.0005:
        return {"name": "MACD Momentum", "confidence": min(int(abs(macd_hist) * 8000), 88)}

    if (rsi_val < 30 or rsi_val > 70) and (stoch_k < 20 or stoch_k > 80):
        return {"name": "RSI+Stoch Divergence", "confidence": 82}

    if vol_ratio >= 1.3:   # v2: 1.4 → v3: 1.3
        return {"name": "Volume Breakout", "confidence": min(int(vol_ratio * 52), 90)}

    if adx_val < 18 and regime == "ranging":
        return {"name": "Mean Reversion", "confidence": 65}

    return {"name": "EMA Crossover", "confidence": 60}
