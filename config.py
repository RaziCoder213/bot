"""
config.py  —  AZIM AI TRADER v3
=================================
Includes Streamlit Cloud Secrets support.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Streamlit Cloud helper
def get_secret(key, default=""):
    try:
        import streamlit as st
        if key in st.secrets:
            return st.secrets[key]
    except:
        pass
    return os.getenv(key, default)

APP_HOST = "0.0.0.0"
APP_PORT = 8000

BITGET_REST_URL  = "https://api.bitget.com"
BITGET_WS_URL    = "wss://ws.bitget.com/v2/ws/public"
FEAR_GREED_URL   = "https://api.alternative.me/fng/"
CRYPTOPANIC_URL  = "https://cryptopanic.com/api/v1/posts/"

CRYPTOPANIC_API_KEY = get_secret("CRYPTOPANIC_API_KEY", "")
DISCORD_WEBHOOK_URL = get_secret("DISCORD_WEBHOOK_URL", "")

TAKER_FEE        = 0.0006
FUNDING_RATE_8H  = 0.0001
SLIPPAGE_MIN_BPS = 2
SLIPPAGE_MAX_BPS = 8

# ── quality gates ──────────────────────────────────────────────────
MIN_TECH_SCORE = 38   
DECISION_MIN   = 42   
ADX_MIN        = 12   
SCORE_GAP      = 8    
VOL_RATIO_MIN  = 0.8  

SCAN_SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","BNBUSDT","ADAUSDT","DOGEUSDT",
    "AVAXUSDT","DOTUSDT","LINKUSDT","UNIUSDT","NEARUSDT","ATOMUSDT","LTCUSDT",
    "BCHUSDT","AAVEUSDT","MATICUSDT","APTUSDT","ARBUSDT","OPUSDT",
    "INJUSDT","SUIUSDT","TIAUSDT","SEIUSDT","STXUSDT","RUNEUSDT","LDOUSDT",
    "GMXUSDT","WLDUSDT","RENDERUSDT","FETUSDT","IMXUSDT","GRTUSDT",
    "ENAUSDT","JUPUSDT","ONDOUSDT","WIFUSDT","BONKUSDT","PEPEUSDT",
    "ETCUSDT","VETUSDT","ALGOUSDT","ICPUSDT","HBARUSDT","XLMUSDT","TRXUSDT",
    "CRVUSDT","COMPUSDT","MKRUSDT","FILUSDT","DYDXUSDT","ORDIUSDT",
    "1000PEPEUSDT","FLOKIUSDT","FTMUSDT","SANDUSDT","AXSUSDT","APEUSDT",
]

DEFAULT_CONFIG = {
    "mode":                  "AUTO",
    "leverage":              10,
    "wallet_balance":        1000.0,
    "risk_pct":              2.5,
    "min_score":             DECISION_MIN,
    "adx_min":               ADX_MIN,
    "score_gap":             SCORE_GAP,
    "vol_ratio_min":         VOL_RATIO_MIN,
    "max_trades":            3,
    "scan_interval":         60,
    "trade_amount_manual":   100.0,
    "sl_pct_manual":         1.8,
    "tp1_pct_manual":        3.5,
    "tp2_pct_manual":        6.0,
    "max_trade_hours":       36,
    "funding_filter":        True,
    "orderbook_filter":      False,
    "fear_greed_filter":     False,
    "discord_notifications": True,
    "websocket_enabled":     True,
    "min_rr":                2.0,
    "max_daily_loss_pct":    5.0,
    "max_daily_trades":      10,
    "symbol_mode":           "ALL",
    "custom_symbols":        [],
    "cryptopanic_api_key":   CRYPTOPANIC_API_KEY,
    "discord_webhook_url":   DISCORD_WEBHOOK_URL,
}

def get_default_config():
    return dict(DEFAULT_CONFIG)
