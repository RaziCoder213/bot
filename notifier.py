"""
notifier.py  —  AZIM AI TRADER v3

v3 FIXES:
1. notify_signal() aur notify_trade_open() mein SL/TP v3 values use kiye (1.4x/4.0x)
   v2 mein 1.5x/3.5x thay — Discord mein galat levels jate thay
2. Signal message mein "Dashboard par check karein" note add kiya
3. notify_trade_open() mein open_trade_id field save hoti hai (linking ke liye)
"""
import requests
import threading
import logging
from typing import Dict
from config import DISCORD_WEBHOOK_URL

logger = logging.getLogger("azim-trader.notifier")


def _send(payload: dict):
    # Always read latest URL from config module (supports live updates from dashboard)
    import config as _cfg
    url = getattr(_cfg, 'DISCORD_WEBHOOK_URL', '') or DISCORD_WEBHOOK_URL
    if not url:
        return
    try:
        r = requests.post(url, json=payload, timeout=8)
        if r.status_code not in (200, 204):
            logger.warning(f"Discord returned {r.status_code}: {r.text[:100]}")
    except Exception as e:
        logger.error(f"Discord notify error: {e}")


def _async(payload: dict):
    threading.Thread(target=_send, args=(payload,), daemon=True).start()


def _fmt(price: float) -> str:
    if not price or price == 0:
        return "N/A"
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:,.4f}"
    else:
        return f"{price:,.6f}"


def notify_signal(signal: Dict):
    """
    Signal detected by scanner — shown on Discord AND dashboard.
    v3: Uses correct 1.4x/4.0x ATR values. SL/TP from signal if available,
    otherwise computed here for Discord display.
    """
    direction = signal.get("direction", "")
    symbol    = signal.get("symbol", "")
    score     = signal.get("score", 0)
    strategy  = signal.get("strategy", "")
    price     = signal.get("price", 0)
    atr_v     = signal.get("atr", 0) or price * 0.012
    tf_fast   = signal.get("timeframe_fast", signal.get("tf_fast", ""))
    tf_slow   = signal.get("timeframe_slow", signal.get("tf_slow", ""))
    adx       = signal.get("adx", 0)
    rsi_v     = signal.get("rsi", 0)
    regime    = signal.get("regime", "unknown")
    vol_ratio = signal.get("volume_ratio", 1.0)
    patterns  = signal.get("patterns", {})
    rr_given  = signal.get("risk_reward", 0)

    # Use signal's SL/TP if already computed (v3 compute_sl_tp), else calc here
    sl  = signal.get("sl")  or 0
    tp1 = signal.get("tp1") or 0
    tp2 = signal.get("tp2") or 0

    if not sl or not tp2:
        # v3 values: SL=1.4x, TP1=2.2x, TP2=4.0x
        sl_d  = max(atr_v * 1.4, price * 0.011)
        tp1_d = max(atr_v * 2.2, price * 0.024)
        tp2_d = max(atr_v * 4.0, price * 0.055)
        if direction == "LONG":
            sl  = round(price - sl_d, 6)
            tp1 = round(price + tp1_d, 6)
            tp2 = round(price + tp2_d, 6)
        else:
            sl  = round(price + sl_d, 6)
            tp1 = round(price - tp1_d, 6)
            tp2 = round(price - tp2_d, 6)

    sl_pct  = abs(price - sl)  / price * 100 if price and sl  else 0
    tp1_pct = abs(tp1 - price) / price * 100 if price and tp1 else 0
    tp2_pct = abs(tp2 - price) / price * 100 if price and tp2 else 0
    rr      = rr_given if rr_given else (round(tp2_pct / sl_pct, 1) if sl_pct > 0 else 0)

    dir_emoji = "🟢 LONG  ▲" if direction == "LONG" else "🔴 SHORT ▼"
    regime_emoji = {
        "trending": "📈 Trending", "ranging": "↔️ Ranging",
        "volatile": "⚡ Volatile", "mixed":   "〰️ Mixed"
    }.get(regime, "❓ Unknown")

    pat_str = ""
    if patterns.get("bullish_engulfing"): pat_str = " 🕯️ Bullish Engulfing"
    elif patterns.get("bearish_engulfing"): pat_str = " 🕯️ Bearish Engulfing"
    elif patterns.get("hammer"):            pat_str = " 🔨 Hammer"
    elif patterns.get("shooting_star"):     pat_str = " 💫 Shooting Star"

    score_bar = "█" * int(score // 10) + "░" * (10 - int(score // 10))

    msg = (
        f"```\n"
        f"╔══════════════════════════╗\n"
        f"║    🔍 SIGNAL DETECTED     ║\n"
        f"╚══════════════════════════╝\n"
        f"```\n"
        f"**{symbol}**  {dir_emoji}\n"
        f"Timeframe: **{tf_fast}** + **{tf_slow}**{pat_str}\n\n"
        f"```yaml\n"
        f"Entry  : ${_fmt(price)}\n"
        f"SL     : ${_fmt(sl)}  (-{sl_pct:.2f}%) ← STOP LOSS\n"
        f"TP1    : ${_fmt(tp1)}  (+{tp1_pct:.2f}%) ← 50% close here\n"
        f"TP2    : ${_fmt(tp2)}  (+{tp2_pct:.2f}%) ← full close\n"
        f"R:R    : {rr}x\n"
        f"```\n"
        f"```ini\n"
        f"[ANALYSIS]\n"
        f"Strategy = {strategy}\n"
        f"Score    = {score}/100  [{score_bar}]\n"
        f"ADX      = {adx}  (trend strength)\n"
        f"RSI      = {rsi_v}\n"
        f"Volume   = {vol_ratio:.2f}x average\n"
        f"Regime   = {regime_emoji}\n"
        f"```\n"
        f"📊 Dashboard: http://localhost:8000"
    )
    _async({"content": msg})


def notify_trade_open(trade: Dict):
    """
    Trade actually opened — position open ho gayi.
    v3: Correct SL/TP values, dashboard link included.
    """
    direction = trade.get("direction", "")
    symbol    = trade.get("symbol", "")
    price     = trade.get("entry_price", 0)
    score     = trade.get("score", 0)
    strategy  = trade.get("strategy", "")
    sl        = trade.get("sl", 0)
    tp1       = trade.get("tp1", 0)
    tp2       = trade.get("tp2", 0)
    size      = trade.get("size", 0)
    notional  = trade.get("notional", 0)
    trade_id  = trade.get("id", "")
    tf        = trade.get("timeframe", "")

    sl_pct  = abs(price - sl)  / price * 100 if price and sl  else 0
    tp1_pct = abs(tp1 - price) / price * 100 if price and tp1 else 0
    tp2_pct = abs(tp2 - price) / price * 100 if price and tp2 else 0
    rr      = round(tp2_pct / sl_pct, 1) if sl_pct > 0 else 0
    dir_emoji = "🟢 LONG  ▲" if direction == "LONG" else "🔴 SHORT ▼"

    msg = (
        f"```\n"
        f"╔══════════════════════════╗\n"
        f"║    ✅  TRADE OPENED       ║\n"
        f"╚══════════════════════════╝\n"
        f"```\n"
        f"**{symbol}**  {dir_emoji}\n"
        f"TF: **{tf}**  |  ID: `{trade_id}`\n\n"
        f"```yaml\n"
        f"Entry    : ${_fmt(price)}\n"
        f"Size     : {size}  Notional: ${notional:.2f}\n"
        f"SL       : ${_fmt(sl)}  (-{sl_pct:.2f}%)\n"
        f"TP1      : ${_fmt(tp1)}  (+{tp1_pct:.2f}%) — 50% close, SL→BE\n"
        f"TP2      : ${_fmt(tp2)}  (+{tp2_pct:.2f}%) — full close\n"
        f"R:R      : {rr}x\n"
        f"```\n"
        f"`Strategy: {strategy}  |  Score: {score}/100`\n"
        f"📊 Live PnL: http://localhost:8000"
    )
    _async({"content": msg})


def notify_tp1(trade: Dict, price: float):
    symbol    = trade.get("symbol", "")
    direction = trade.get("direction", "")
    entry     = trade.get("entry_price", 0)
    realized  = trade.get("tp1_realized", 0)
    new_sl    = trade.get("sl", 0)
    tp2       = trade.get("tp2", 0)
    trade_id  = trade.get("id", "")

    pct = (price - entry) / entry * 100 if direction == "LONG" else (entry - price) / entry * 100

    msg = (
        f"```\n"
        f"╔══════════════════════════╗\n"
        f"║   🎯  TP1 HIT — 50% out   ║\n"
        f"╚══════════════════════════╝\n"
        f"```\n"
        f"**{symbol}** {direction}  |  ID: `{trade_id}`\n"
        f"```yaml\n"
        f"Price    : ${_fmt(price)}  (+{pct:.2f}%)\n"
        f"Realized : ${realized:+.4f}\n"
        f"New SL   : ${_fmt(new_sl)}  (breakeven+)\n"
        f"TP2 Next : ${_fmt(tp2)}\n"
        f"```\n"
        f"🔄 Trailing stop active — riding to TP2!"
    )
    _async({"content": msg})


def notify_trade_closed(trade: Dict):
    direction  = trade.get("direction", "")
    net_pnl    = float(trade.get("net_pnl", 0))
    symbol     = trade.get("symbol", "")
    entry      = trade.get("entry_price", 0)
    exit_p     = trade.get("exit_price", 0)
    reason     = trade.get("close_reason", "")
    notional   = trade.get("notional", 1)
    strategy   = trade.get("strategy", "")
    open_time  = trade.get("open_time", "")
    close_time = trade.get("close_time", "")
    trade_id   = trade.get("id", "")

    pct   = net_pnl / notional * 100 if notional else 0
    emoji = "✅ WIN" if net_pnl >= 0 else "❌ LOSS"
    reason_emoji = {
        "TP2":    "🚀", "TP1": "🎯", "SL":     "🛑",
        "TRAIL":  "🔄", "MANUAL": "👤", "TIME_EXIT": "⏱"
    }.get(reason, "📌")

    dur_str = "--"
    try:
        from datetime import datetime, timezone
        ot = datetime.fromisoformat(open_time)
        ct = datetime.fromisoformat(close_time) if close_time else datetime.now(timezone.utc)
        secs = int((ct - ot).total_seconds())
        h, rem = divmod(secs, 3600); m, s = divmod(rem, 60)
        dur_str = f"{h}h {m}m" if h > 0 else f"{m}m {s}s"
    except Exception:
        pass

    msg = (
        f"```\n"
        f"╔══════════════════════════╗\n"
        f"║  {emoji:^26}║\n"
        f"╚══════════════════════════╝\n"
        f"```\n"
        f"**{symbol}** {direction}  |  ID: `{trade_id}`\n"
        f"```yaml\n"
        f"Entry    : ${_fmt(entry)}\n"
        f"Exit     : ${_fmt(exit_p)}\n"
        f"Net PnL  : ${net_pnl:+.4f}  ({pct:+.2f}%)\n"
        f"Duration : {dur_str}\n"
        f"Reason   : {reason_emoji} {reason}\n"
        f"Strategy : {strategy}\n"
        f"```"
    )
    _async({"content": msg})
