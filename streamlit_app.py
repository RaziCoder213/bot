import streamlit as st
import pandas as pd
import time
from datetime import datetime, timezone
import plotly.graph_objects as go
import plotly.express as px

# IMPORTANT: Import from core_engine now
from core_engine import engine, _log_buffer
from market_data import get_fear_greed_index, get_ws_price_count

# Page Configuration
st.set_page_config(
    page_title="AZIM AI TRADER v3",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for dark theme aesthetics
st.markdown("""
<style>
    [data-testid="stMetricValue"] {
        font-size: 28px;
        font-weight: 800;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: transparent;
        border-radius: 4px 4px 0px 0px;
        gap: 1px;
        padding-top: 10px;
        padding-bottom: 10px;
    }
    .stTabs [aria-selected="true"] {
        background-color: rgba(59, 130, 246, 0.1);
        border-bottom: 2px solid rgb(59, 130, 246);
    }
    .status-running {
        color: #22c55e;
        font-weight: bold;
    }
    .status-stopped {
        color: #ef4444;
        font-weight: bold;
    }
    .log-entry {
        font-family: 'Courier New', monospace;
        font-size: 0.8rem;
        padding: 2px 0;
        border-bottom: 1px solid rgba(255,255,255,0.05);
    }
</style>
""", unsafe_allow_html=True)

# --- Helper Functions ---

def fmt_pnl(val):
    color = "green" if val >= 0 else "red"
    return f":{color}[${val:,.2f}]"

def get_status_data():
    s = engine.snapshot()
    total = s["stats"]["wins"] + s["stats"]["losses"]
    wr = round(s["stats"]["wins"] / total * 100, 1) if total else 0
    wallet = float(s["config"].get("wallet_balance", 1000))
    initial_wallet = 1000.0
    net_pnl = s["stats"].get("net_pnl", 0)
    pnl_pct = round(net_pnl / initial_wallet * 100, 2) if initial_wallet > 0 else 0
    
    return {
        "running": engine.running,
        "safe_mode": s["safe_mode"],
        "open_count": len(s["open_trades"]),
        "closed_count": len(s["closed_trades"]),
        "stats": s["stats"],
        "win_rate": wr,
        "pnl_pct": pnl_pct,
        "wallet": wallet,
        "scanner": {
            "last_scan": engine.scanner.last_scan,
            "symbols_scanned": engine.scanner.symbols_scanned,
        },
        "last_error": engine._last_error,
    }

# --- Sidebar ---

with st.sidebar:
    st.title("⚡ AZIM AI v3")
    
    status_data = get_status_data()
    
    # Run Status
    if status_data["running"]:
        st.markdown(f"Status: <span class='status-running'>● RUNNING</span>", unsafe_allow_html=True)
    else:
        st.markdown(f"Status: <span class='status-stopped'>● STOPPED</span>", unsafe_allow_html=True)
        
    # Controls
    col1, col2 = st.columns(2)
    with col1:
        if st.button("▶ Start", use_container_width=True, disabled=status_data["running"]):
            engine.start()
            st.rerun()
    with col2:
        if st.button("⏹ Stop", use_container_width=True, disabled=not status_data["running"]):
            engine.stop()
            st.rerun()
            
    if st.button("⚡ Close All Trades", use_container_width=True, type="secondary"):
        with engine.lock:
            trades = [dict(t) for t in engine.open_trades]
        from trade_executor import close_trade
        from notifier import notify_trade_closed
        for t in trades:
            use_price = float(t.get("current_price") or t["entry_price"])
            c = close_trade(t, use_price, "MANUAL_ALL_ST")
            engine._on_trade_closed(c)
            notify_trade_closed(c)
        st.success(f"Closed {len(trades)} trades")
        st.rerun()

    st.divider()
    
    # Fear & Greed
    fg = get_fear_greed_index()
    fg_val = int(fg.get("value", 50))
    st.subheader(f"Fear & Greed: {fg_val}")
    st.progress(fg_val / 100)
    st.caption(f"Classification: {fg.get('classification', 'Neutral')}")
    
    st.divider()
    
    # System Health
    st.subheader("🛡 Health")
    st.text(f"Scanner: {'✅' if status_data['running'] else '❌'}")
    ls = status_data["scanner"]["last_scan"]
    ls_str = datetime.fromtimestamp(ls).strftime("%H:%M:%S") if ls else "—"
    st.text(f"Last Scan: {ls_str}")
    st.text(f"Symbols: {status_data['scanner']['symbols_scanned']}")
    st.text(f"WS Prices: {get_ws_price_count()}")
    
    st.divider()
    
    # Top Scan Symbols
    from scanner import build_scan_universe
    universe = build_scan_universe()[:10]
    st.subheader("📈 Top Scan Symbols")
    for i, (sym, score) in enumerate(universe):
        st.caption(f"#{i+1} **{sym}**: {score:.1f}")

    if status_data["safe_mode"]:
        st.error(f"SAFE MODE ACTIVE\n{status_data['last_error']}")
        if st.button("Reset Safe Mode"):
            with engine.lock:
                engine.safe_mode = False
                engine._last_error = ""
                engine._zero_price_count = 0
            st.rerun()

# --- Main Tabs ---

tab_dash, tab_open, tab_sig, tab_history, tab_perf, tab_cfg, tab_logs = st.tabs([
    "📊 Dashboard", "📈 Open Trades", "🔍 Signals", "📁 History", "🏆 Performance", "⚙ Config", "🖥 Logs"
])

# Refresh logic
auto_refresh = st.sidebar.toggle("Auto-refresh (5s)", value=True)

# --- Tab 1: Dashboard ---
with tab_dash:
    s = engine.snapshot()
    stats = s["stats"]
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Net PnL", f"${stats['net_pnl']:,.2f}", f"{status_data['pnl_pct']}%")
    col2.metric("Win Rate", f"{status_data['win_rate']}%", f"{stats['wins']}W / {stats['losses']}L")
    col3.metric("Open Trades", len(s["open_trades"]))
    
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_pnl = stats.get("daily_pnl", {}).get(today, 0.0)
    col4.metric("Today PnL", f"${today_pnl:,.2f}")

    st.divider()

    # Target Progress
    initial_wallet = 1000.0
    net_pnl = stats.get("net_pnl", 0)
    target = initial_wallet * 0.30
    progress = min(net_pnl / target, 1.0) if net_pnl > 0 else 0.0
    
    st.subheader(f"Monthly Target Progress (30% = ${target:,.2f})")
    st.progress(progress)
    st.caption(f"Current PnL: ${net_pnl:,.2f} | Progress: {progress*100:.1f}% | Remaining: ${max(target-net_pnl, 0):,.2f}")
    
    # Daily PnL Chart
    daily_data = stats.get("daily_pnl", {})
    if daily_data:
        df_daily = pd.DataFrame(list(daily_data.items()), columns=["Date", "PnL"])
        df_daily = df_daily.sort_values("Date")
        df_daily["Cumulative PnL"] = df_daily["PnL"].cumsum()
        
        fig = px.line(df_daily, x="Date", y="Cumulative PnL", title="Cumulative PnL Growth")
        fig.update_layout(template="plotly_dark", height=400)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No trade data yet to show charts.")

# --- Tab 2: Open Trades ---
with tab_open:
    from market_data import get_current_prices_batch
    trades = s["open_trades"]
    
    if not trades:
        st.info("No open trades at the moment.")
    else:
        symbols = list({t["symbol"] for t in trades})
        prices = get_current_prices_batch(symbols)
        
        display_trades = []
        for t in trades:
            trade = dict(t)
            cur = prices.get(t["symbol"], 0)
            trade["Current"] = cur
            if cur > 0 and t.get("entry_price", 0) > 0:
                entry = float(t["entry_price"])
                margin = float(t.get("size", 0))
                leverage = float(t.get("leverage", 10))
                contracts = float(t.get("contracts", 0))
                dirn = 1 if t["direction"] == "LONG" else -1
                if contracts <= 0: contracts = (margin * leverage) / entry
                raw_pnl = (cur - entry) * contracts * dirn
                pnl_pct = (raw_pnl / margin * 100) if margin > 0 else 0
                trade["PnL $"] = round(raw_pnl, 2)
                trade["PnL %"] = round(pnl_pct, 2)
            else:
                trade["PnL $"] = 0
                trade["PnL %"] = 0
            
            display_trades.append({
                "ID": trade["id"], "Symbol": trade["symbol"], "Dir": trade["direction"],
                "Entry": trade["entry_price"], "Current": trade.get("Current", 0),
                "PnL $": trade["PnL $"], "PnL %": trade["PnL %"], "Margin": trade.get("size", 0),
                "Lev": trade.get("leverage", 10), "SL": trade.get("sl", 0),
                "TP1": trade.get("tp1", 0), "TP2": trade.get("tp2", 0),
                "Strategy": trade.get("strategy", ""), "Time": trade.get("open_time", "")[:19]
            })
            
        df_open = pd.DataFrame(display_trades)
        st.dataframe(df_open, use_container_width=True, hide_index=True)
        
        with st.expander("Close Trade"):
            selected_id = st.selectbox("Select Trade to Close", options=[t["id"] for t in trades])
            if st.button("Close Selected Trade", type="primary"):
                from trade_executor import close_trade
                from notifier import notify_trade_closed
                found = next((t for t in trades if t["id"] == selected_id), None)
                if found:
                    use_price = prices.get(found["symbol"], found["entry_price"])
                    c = close_trade(found, use_price, "MANUAL_ST")
                    engine._on_trade_closed(c)
                    notify_trade_closed(c)
                    st.success(f"Closed {found['symbol']}")
                    st.rerun()

# --- Tab 3: Signals ---
with tab_sig:
    signals = s["signals"]
    if not signals: st.info("No signals detected yet.")
    else:
        df_sig = pd.DataFrame(signals)
        cols = ["symbol", "direction", "score", "price", "sl", "tp1", "tp2", "strategy", "executed", "time"]
        st.dataframe(df_sig[cols], use_container_width=True, hide_index=True)

# --- Tab 4: History ---
with tab_history:
    closed = s["closed_trades"]
    if not closed: st.info("No trade history yet.")
    else:
        df_closed = pd.DataFrame(closed)
        df_closed = df_closed.sort_values("close_time", ascending=False)
        cols = ["symbol", "direction", "entry_price", "exit_price", "net_pnl", "close_reason", "strategy", "close_time"]
        st.dataframe(df_closed[cols], use_container_width=True, hide_index=True)

# --- Tab 5: Performance ---
with tab_perf:
    perf = stats.get("strategy_performance", {})
    if not perf: st.info("No performance data yet.")
    else:
        perf_data = []
        for name, d in perf.items():
            total = d.get("trades", 0)
            wins = d.get("wins", 0)
            wr = round(wins / total * 100, 1) if total else 0
            avg_pnl = round(d.get("net_pnl", 0) / total, 2) if total else 0
            perf_data.append({"Strategy": name, "Trades": total, "Win Rate": f"{wr}%", "Net PnL": d.get("net_pnl", 0), "Avg PnL": avg_pnl})
        st.table(pd.DataFrame(perf_data))

# --- Tab 6: Config ---
with tab_cfg:
    st.subheader("⚙ Bot Configuration")
    cfg = engine.config
    with st.form("config_form"):
        c1, c2, c3 = st.columns(3)
        new_mode = c1.selectbox("Trade Mode", ["AUTO", "MANUAL"], index=0 if cfg.get("mode")=="AUTO" else 1)
        new_wallet = c2.number_input("Wallet Balance ($)", value=float(cfg.get("wallet_balance", 1000)), step=100.0)
        new_risk = c3.number_input("Risk % (AUTO)", value=float(cfg.get("risk_pct", 2.5)), step=0.1)
        c4, c5, c6 = st.columns(3)
        new_lev = c4.number_input("Leverage", value=int(cfg.get("leverage", 10)), min_value=1, max_value=125)
        new_max_trades = c5.number_input("Max Open Trades", value=int(cfg.get("max_trades", 3)), min_value=1)
        new_interval = c6.number_input("Scan Interval (s)", value=int(cfg.get("scan_interval", 60)), min_value=30)
        st.divider()
        c7, c8, c9 = st.columns(3)
        new_min_score = c7.number_input("Min Decision Score", value=float(cfg.get("min_score", 42)), min_value=10.0)
        new_adx_min = c8.number_input("Min ADX", value=float(cfg.get("adx_min", 12)), min_value=5.0)
        new_vol_ratio = c9.number_input("Min Vol Ratio", value=float(cfg.get("vol_ratio_min", 0.8)), step=0.1)
        if st.form_submit_button("Save Configuration", type="primary"):
            updates = {"mode": new_mode, "wallet_balance": new_wallet, "risk_pct": new_risk, "leverage": new_lev, "max_trades": new_max_trades, "scan_interval": new_interval, "min_score": new_min_score, "adx_min": new_adx_min, "vol_ratio_min": new_vol_ratio}
            with engine.lock: engine.config.update(updates)
            engine.db.save_state(engine.snapshot())
            st.success("Config saved!")
            st.rerun()

# --- Tab 7: Logs ---
with tab_logs:
    st.subheader("🖥 Live Logs")
    logs = list(_log_buffer)[:200]
    log_html = ""
    for line in logs:
        color = "#e2e8f0"
        if "ERROR" in line: color = "#ef4444"
        elif "Trade opened" in line or "✅" in line: color = "#22c55e"
        log_html += f"<div class='log-entry' style='color: {color}'>{line}</div>"
    st.markdown(f"<div style='background-color: #0e1117; padding: 15px; border-radius: 5px; height: 500px; overflow-y: auto;'>{log_html}</div>", unsafe_allow_html=True)

# Auto-refresh logic (at the end)
if auto_refresh:
    time.sleep(5)
    st.rerun()
