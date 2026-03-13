import math
from typing import List, Tuple, Optional


def ema(prices: List[float], period: int) -> List[float]:
    if len(prices) < period:
        return []
    k      = 2.0 / (period + 1)
    result = [sum(prices[:period]) / period]
    for p in prices[period:]:
        result.append(p * k + result[-1] * (1 - k))
    return result


def sma(prices: List[float], period: int) -> List[float]:
    return [sum(prices[i:i+period]) / period for i in range(len(prices) - period + 1)]


def rsi(prices: List[float], period: int = 14) -> List[float]:
    if len(prices) < period + 1:
        return []
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains  = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]
    ag     = sum(gains[:period])  / period
    al     = sum(losses[:period]) / period
    result = []
    for i in range(period, len(deltas)):
        rs = ag / al if al != 0 else 100.0
        result.append(100.0 - 100.0 / (1 + rs))
        ag = (ag * (period - 1) + gains[i])  / period
        al = (al * (period - 1) + losses[i]) / period
    return result


def stoch_rsi(prices: List[float], period: int = 14,
              smooth_k: int = 3, smooth_d: int = 3) -> Tuple[List[float], List[float]]:
    rsi_v = rsi(prices, period)
    if len(rsi_v) < period:
        return [], []
    k_raw = []
    for i in range(period - 1, len(rsi_v)):
        window = rsi_v[i - period + 1: i + 1]
        lo, hi = min(window), max(window)
        k_raw.append(50.0 if hi == lo else (rsi_v[i] - lo) / (hi - lo) * 100)
    k = sma(k_raw, smooth_k)
    d = sma(k,     smooth_d)
    return k, d


def macd(prices: List[float], fast: int = 12, slow: int = 26,
         signal_p: int = 9) -> Tuple[List[float], List[float], List[float]]:
    ef        = ema(prices, fast)
    es        = ema(prices, slow)
    diff      = len(ef) - len(es)
    macd_line = [f - s for f, s in zip(ef[diff:], es)]
    sig_line  = ema(macd_line, signal_p)
    d2        = len(macd_line) - len(sig_line)
    histogram = [m - s for m, s in zip(macd_line[d2:], sig_line)]
    return macd_line, sig_line, histogram


def bollinger_bands(prices: List[float], period: int = 20,
                    std_dev: float = 2.0) -> Tuple[List[float], List[float], List[float]]:
    mid    = sma(prices, period)
    upper, lower = [], []
    for i, m in enumerate(mid):
        window = prices[i:i+period]
        std    = math.sqrt(sum((p - m)**2 for p in window) / period)
        upper.append(m + std_dev * std)
        lower.append(m - std_dev * std)
    return upper, mid, lower


def atr(highs: List[float], lows: List[float], closes: List[float],
        period: int = 14) -> List[float]:
    if len(closes) < period + 1:
        return []
    trs = [max(highs[i] - lows[i],
               abs(highs[i] - closes[i-1]),
               abs(lows[i]  - closes[i-1])) for i in range(1, len(closes))]
    vals = [sum(trs[:period]) / period]
    for tr in trs[period:]:
        vals.append((vals[-1] * (period - 1) + tr) / period)
    return vals


def adx(highs: List[float], lows: List[float], closes: List[float],
        period: int = 14) -> List[float]:
    if len(closes) < period * 2:
        return []
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(closes)):
        hd = highs[i] - highs[i-1]
        ld = lows[i-1] - lows[i]
        plus_dm.append(hd  if hd > ld  and hd > 0 else 0.0)
        minus_dm.append(ld if ld > hd  and ld > 0 else 0.0)
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i-1]),
                       abs(lows[i]  - closes[i-1])))

    def _smooth(data):
        s = [sum(data[:period])]
        for v in data[period:]:
            s.append(s[-1] - s[-1] / period + v)
        return s

    st  = _smooth(trs)
    sp  = _smooth(plus_dm)
    sm  = _smooth(minus_dm)
    dx  = []
    for i in range(len(st)):
        if st[i] == 0:
            dx.append(0.0); continue
        pdi = 100 * sp[i] / st[i]
        mdi = 100 * sm[i] / st[i]
        den = pdi + mdi
        dx.append(100 * abs(pdi - mdi) / den if den else 0.0)
    if len(dx) < period:
        return []
    adx_v = [sum(dx[:period]) / period]
    for v in dx[period:]:
        adx_v.append((adx_v[-1] * (period - 1) + v) / period)
    return adx_v


def volume_ratio(volumes: List[float], period: int = 20) -> List[float]:
    if len(volumes) < period + 1:
        return []
    result = []
    for i in range(period, len(volumes)):
        avg = sum(volumes[i-period:i]) / period
        result.append(volumes[i] / avg if avg > 0 else 1.0)
    return result


def vwap(candles: List[dict]) -> Optional[float]:
    tv, tp = 0.0, 0.0
    for c in candles:
        typical = (c["high"] + c["low"] + c["close"]) / 3
        tv     += c["volume"]
        tp     += typical * c["volume"]
    return tp / tv if tv > 0 else None
