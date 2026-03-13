# AZIM AI TRADER v3 — Setup Guide

## Pehle Yeh Karein (Setup)

### 1. Python Install
- Python 3.9 ya usse upar: https://python.org/downloads
- Install karte waqt ✅ "Add Python to PATH" check karein

### 2. .env File Mein API Keys Daalein
`.env` file kholo (Notepad se) aur apni keys daalein:
```
CRYPTOPANIC_API_KEY=apni_key_yahan
DISCORD_WEBHOOK_URL=apna_webhook_yahan
```

### 3. Wallet Balance Set Karein
`config.py` file mein:
```python
"wallet_balance": 1000.0,  # Apna actual balance daalein
```

### 4. Bot Chalayein
- **Windows**: `start.bat` double-click karein
- **Mac/Linux**: Terminal mein `./start.sh` chalayein

### 5. Dashboard Kholein
Browser mein jaaein: **http://localhost:8000**

---

## v3 Main Kya Improve Hua (v2 se)

| Setting | v2 | v3 | Faida |
|---------|-----|-----|-------|
| Signal quality gate | 35 | 42 | Sirf best signals trade |
| ADX minimum | 5 | 12 | Ranging market mein entry nahi |
| Direction gap | 4 | 8 | Direction clear hone par hi entry |
| Volume filter | 0.6 | 0.8 | Low volume fakeouts se bachao |
| Risk per trade | 2% | 2.5% | Zyada compounding |
| Max open trades | 5 | 3 | Capital focused rahega |
| TP2 target | 3.5x ATR | 4.0x ATR | Bigger wins |
| SL distance | 1.5x ATR | 1.4x ATR | Tighter risk |
| Funding filter | OFF | ON | Funding costs se bachao |
| Daily loss limit | None | -5% | Drawdown protection |
| Scan interval | 90s | 60s | Faster signal detection |

---

## 30% PnL Kaise Milega

Bot in strategies se 30%+ target karta hai:
1. **Quality over Quantity**: Sirf high-score (42+) trades
2. **Better R:R**: ~2.8:1 (4x ATR TP2 vs 1.4x ATR SL)
3. **Dynamic Sizing**: Winning streak mein zyada, losing mein kum
4. **Trailing Stop**: TP1 hit hone ke baad SL move hota hai
5. **Compound Growth**: Har trade ke baad wallet update hota hai

---

## Dashboard Features
- **Start/Stop** bot button
- **Live signals** with score and R:R ratio
- **Open trades** with real-time PnL
- **30% target progress** bar
- **Strategy performance** breakdown
- **Daily PnL** chart

---

## Masail (Issues) Aur Hal

**Bot scan kar raha hai lekin trade nahi?**
→ Signals ka score 42+ nahi ho raha — yeh theek hai, quality control hai

**"Safe Mode" aa gaya?**
→ /api/exit_safe_mode call karein ya dashboard mein "Exit Safe Mode" button

**Discord notifications nahi aa rahe?**
→ .env mein DISCORD_WEBHOOK_URL check karein

**API rate limit error?**
→ Scan interval 90 kar dein: config mein `"scan_interval": 90`
