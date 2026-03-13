import random
import uuid
from datetime import datetime, timezone
from typing import Dict

from config import TAKER_FEE, FUNDING_RATE_8H, SLIPPAGE_MIN_BPS, SLIPPAGE_MAX_BPS


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def simulate_entry(signal: Dict, size: float, wallet_balance: float) -> Dict:
    price     = float(signal.get("price", 0))
    direction = signal.get("direction", "LONG")
    bps       = random.uniform(SLIPPAGE_MIN_BPS, SLIPPAGE_MAX_BPS)
    slip      = price * bps / 10_000
    entry     = (price + slip) if direction == "LONG" else (price - slip)
    fee       = size * TAKER_FEE

    # Leverage-aware position sizing
    # size     = margin/capital (USD) e.g. $25
    # leverage = from config (default 10x)
    # contracts = (size * leverage) / entry_price  → how many coins
    # notional  = contracts * entry_price = size * leverage (USD position size)
    leverage     = float(signal.get("leverage", 10))
    contracts    = (size * leverage) / entry if entry > 0 else 0
    notional_val = round(size * leverage, 2)   # total position value in USD

    return {
        "id":               str(uuid.uuid4())[:8],
        "symbol":           signal.get("symbol"),
        "direction":        direction,
        "entry_price":      round(entry, 8),
        "contracts":        round(contracts, 6),  # actual coin qty
        "size":             round(size, 4),        # margin / capital used (USD)
        "notional":         notional_val,          # total position = margin * leverage
        "invested_usd":     round(size, 2),        # capital at risk
        "leverage":         int(leverage),
        "margin_mode":      "CROSS",
        "sl":               signal.get("sl", 0),
        "tp1":              signal.get("tp1", 0),
        "tp2":              signal.get("tp2", 0),
        "entry_fee":        round(fee, 4),
        "funding_paid":     0.0,
        "tp1_hit":          False,
        "tp1_realized":     0.0,
        "strategy":         signal.get("strategy", "unknown"),
        "score":            signal.get("score", 0),
        "timeframe":        f"{signal.get('timeframe_fast','')}/{signal.get('timeframe_slow','')}",
        "open_time":        _now_iso(),
        "status":           "OPEN",
        "wallet_at_open":   wallet_balance,
        "trailing_sl":      None,
        "max_trade_hours":  48,
    }


def apply_funding(trade: Dict, elapsed_seconds: float) -> Dict:
    if elapsed_seconds > 0:
        intervals           = elapsed_seconds / (8 * 3600)
        trade["funding_paid"] += abs(trade["notional"]) * FUNDING_RATE_8H * intervals
    return trade


def close_trade(trade: Dict, exit_price: float, reason: str) -> Dict:
    direction = 1 if trade["direction"] == "LONG" else -1
    entry     = float(trade.get("entry_price", 0))
    margin    = float(trade.get("size", 0))          # USD capital
    leverage  = float(trade.get("leverage", 10))
    contracts = float(trade.get("contracts", 0))

    # Recalculate contracts if not stored (old trades)
    if contracts <= 0 and margin > 0 and entry > 0:
        contracts = (margin * leverage) / entry

    raw_pnl   = (exit_price - entry) * contracts * direction
    # Fee based on notional (contracts * price)
    exit_fee  = abs(exit_price * contracts) * TAKER_FEE
    net_pnl   = (raw_pnl
                 - trade.get("entry_fee",    0)
                 - exit_fee
                 - trade.get("funding_paid", 0)
                 + trade.get("tp1_realized", 0))
    trade.update({
        "status":       "CLOSED",
        "close_time":   _now_iso(),
        "exit_price":   round(exit_price, 8),
        "exit_fee":     round(exit_fee,   4),
        "raw_pnl":      round(raw_pnl,    4),
        "net_pnl":      round(net_pnl,    4),
        "close_reason": reason,
    })
    return trade


def partial_tp1(trade: Dict, price: float) -> Dict:
    if trade.get("tp1_hit"):
        return trade
    half      = trade["size"] * 0.5
    direction = 1 if trade["direction"] == "LONG" else -1
    realized  = (price - trade["entry_price"]) * half * direction
    fee       = abs(price * half) * TAKER_FEE
    trade["tp1_realized"] = round(realized - fee, 4)
    trade["size"]         = round(trade["size"] - half, 4)
    trade["tp1_hit"]      = True
    # Move SL to breakeven + 0.1%
    entry = trade["entry_price"]
    be    = entry * 0.001
    trade["sl"] = round((entry + be) if trade["direction"] == "LONG" else (entry - be), 8)
    return trade