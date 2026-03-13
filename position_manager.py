"""
position_manager.py  —  AZIM AI TRADER v3

v3 FIXES:
1. TP2 = 4x ATR (tha 3.5x) → better R:R → 30%+ PnL target
2. SL = 1.4x ATR (tha 1.5x) → tighter risk
3. Daily loss limit check ADDED (new)
4. Dynamic risk scaling improved: win streak par zyada risk, loss par kum
"""
from typing import Dict, List


def capital_tier_cap(wallet: float) -> int:
    if wallet < 500:   return 2
    if wallet <= 2000: return 3   # v3: 5→3 (focused trades)
    return 5                      # v3: 10→5


def compute_position_size(config: Dict, stats: Dict,
                           open_trades: List[Dict], signal: Dict) -> float:
    wallet = float(config.get("wallet_balance", 1000))
    mode   = config.get("mode", "AUTO")

    if mode == "MANUAL":
        return float(config.get("trade_amount_manual", 100))

    risk_pct = float(config.get("risk_pct", 2.5)) / 100
    net_pnl  = stats.get("net_pnl", 0)
    wins     = stats.get("wins", 0)
    losses   = stats.get("losses", 0)

    # v3: Improved dynamic risk scaling
    if net_pnl > wallet * 0.10:   # >10% profit → scale up
        risk_pct *= 1.15
    elif net_pnl > 0:
        risk_pct *= 1.05
    elif net_pnl < -wallet * 0.05:  # >5% drawdown → cut size
        risk_pct *= 0.70
    elif net_pnl < 0:
        risk_pct *= 0.85

    # v3: Daily loss limit check
    max_daily_loss = float(config.get("max_daily_loss_pct", 5.0)) / 100
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_pnl = stats.get("daily_pnl", {}).get(today, 0.0)
    if daily_pnl < -(wallet * max_daily_loss):
        return 0.0  # Daily loss limit hit — no more trades today

    # Bucket correlation cap (30% of wallet per group)
    exp    = _bucket_exposure(open_trades, wallet)
    bucket = _bucket(signal.get("symbol", ""))
    if exp.get(bucket, 0) > 0.30:
        return 0.0

    # v3: Score-based size scaling (high confidence = bigger position)
    score = float(signal.get("score", 50))
    if score >= 70:
        risk_pct *= 1.20
    elif score >= 60:
        risk_pct *= 1.10

    return round(max(wallet * risk_pct, 1.0), 2)


def _bucket(symbol: str) -> str:
    if symbol in {"BTCUSDT", "ETHUSDT"}:
        return "majors"
    if symbol in {"SOLUSDT","AVAXUSDT","ADAUSDT","DOTUSDT","NEARUSDT","ATOMUSDT","APTUSDT","SUIUSDT"}:
        return "layer1"
    if symbol in {"UNIUSDT","AAVEUSDT","COMPUSDT","MKRUSDT","CRVUSDT","SUSHIUSDT","GMXUSDT"}:
        return "defi"
    return "alts"


def _bucket_exposure(open_trades: List[Dict], wallet: float) -> Dict[str, float]:
    exp: Dict[str, float] = {}
    for t in open_trades:
        b = _bucket(t.get("symbol", ""))
        exp[b] = exp.get(b, 0) + float(t.get("size", 0))
    return {k: v / wallet for k, v in exp.items()} if wallet > 0 else {}


def compute_sl_tp(price: float, direction: str,
                  atr_val: float, tick_size: float, config: Dict) -> Dict:
    mode = config.get("mode", "AUTO")

    if mode == "MANUAL":
        sl_pct  = float(config.get("sl_pct_manual",  1.8)) / 100
        tp1_pct = float(config.get("tp1_pct_manual", 3.5)) / 100
        tp2_pct = float(config.get("tp2_pct_manual", 6.0)) / 100
        if direction == "LONG":
            sl  = price * (1 - sl_pct)
            tp1 = price * (1 + tp1_pct)
            tp2 = price * (1 + tp2_pct)
        else:
            sl  = price * (1 + sl_pct)
            tp1 = price * (1 - tp1_pct)
            tp2 = price * (1 - tp2_pct)
    else:
        atr_val = atr_val or price * 0.012
        # v3: SL=1.4x ATR, TP1=2.2x, TP2=4.0x → R:R ~2.86
        sl_d  = max(atr_val * 1.4, price * 0.011)   # v2: 1.5x → v3: 1.4x (tighter)
        tp1_d = max(atr_val * 2.2, price * 0.024)   # v2: 2.0x → v3: 2.2x
        tp2_d = max(atr_val * 4.0, price * 0.055)   # v2: 3.5x → v3: 4.0x (bigger target)
        if direction == "LONG":
            sl  = price - sl_d
            tp1 = price + tp1_d
            tp2 = price + tp2_d
        else:
            sl  = price + sl_d
            tp1 = price - tp1_d
            tp2 = price - tp2_d

    def snap(p: float) -> float:
        if tick_size > 0:
            return round(round(p / tick_size) * tick_size, 8)
        return round(p, 8)

    return {"sl": snap(sl), "tp1": snap(tp1), "tp2": snap(tp2)}
