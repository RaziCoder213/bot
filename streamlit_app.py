import streamlit as st
import pandas as pd
import time
from datetime import datetime, timezone
import plotly.graph_objects as go
import plotly.express as px

# IMPORTANT: Import from core_engine
from core_engine import engine, _log_buffer
from market_data import get_fear_greed_index, get_ws_price_count, get_current_prices_batch

# Page Configuration
st.set_page_config(
    page_title="AZIM AI TRADER v3",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 28px; font-weight: 800; }
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .status-running { color: #22c55e; font-weight: bold; }
    .status-stopped { color: #ef4444; font-weight: bold; }
    .log-entry { font-family: 'Courier New', monospace; font-size: 0.8rem; padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
</style>
""", unsafe_allow_html=True)

# --- Helper Functions ---

def get_status_data():
    s = engine.snapshot()
    stats = s["stats"]
    trades = s["open_trades"]
    
    # Calculate Unrealized PnL
    total_unrealized = 0
    if trades:
        symbols = list({t["symbol"] for t in trades})
        prices = get_current_prices_batch(symbols)
        for t in trades:
            cur = prices.get(t["symbol"], 0)
            if cur > 0 and t.get("entry_price", 0) > 0:
                entry = float(t["entry_price"])
                margin = float(t.get("size", 0))
                leverage = float(t.get("leverage", 10))
                contracts = float(t.get("contracts", 0))
                dirn = 1 if t["direction"] == "LONG" else -1
                if contracts <= 0: contracts = (margin * leverage) / entry
                total_unrealized += (cur - entry) * contracts * dirn

    realized_pnl = stats.get("net_pnl", 0)
    total_net_pnl = realized_pnl + total_unrealized
    
    total_trades = stats["wins"] + stats["losses"]
    wr = round(stats["wins"] / total_trades * 100, 1) if total_trades else 0
    wallet = float(s["config"].get("wallet_balance", 1000))
    
    initial_wallet = 1000.0
    pnl_pct = round(total_net_pnl / initial_wallet * 100, 2)
    
    return {
        "running": engine.running,
        "safe_mode": s["safe_mode"],
        "open_count": len(trades),
        "closed_count": len(s["closed_trades"]),
        "stats": stats,
        "win_rate": wr,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": total_unrealized,
        "total_net_pnl": total_net_pnl,
        "pnl_pct": pnl_pct,
        "wallet": wallet,
        "equity": wallet + total_unrealized,
        "scanner": {
            "last_scan": engine.scanner.last_scan,
            "symbols_scanned": engine.scanner.symbols_scanned,
        },
        "last_error": engine._last_error,
        "snapshot": s
    }

# --- Sidebar ---
status_data = get_status_data()

with st.sidebar:
    st.title("⚡ AZIM AI v3")
    
    if status_data["running"]:
        st.markdown(f"Status: <span class='status-running'>● RUNNING</span>", unsafe_allow_html=True)
    else:
        st.markdown(f"Status: <span class='status-stopped'>● STOPPED</span>", unsafe_allow_html=True)
        
    col1, col2 = st.columns(2)
    with col1:
        if st.button("▶ Start", use_container_width=True, disabled=status_data["running"]):
            engine.start(); st.rerun()
    with col2:
        if st.button("⏹ Stop", use_container_width=True, disabled=not status_data["running"]):
            engine.stop(); st.rerun()
            
    if st.button("⚡ Close All Trades", use_container_width=True, type="secondary"):
        from trade_executor import close_trade
        from notifier import notify_trade_closed
        trades = status_data["snapshot"]["open_trades"]
        symbols = list({t["symbol"] for t in trades})
        prices = get_current_prices_batch(symbols)
        for t in trades:
            use_price = prices.get(t["symbol"], t["entry_price"])
            c = close_trade(t, use_price, "MANUAL_ALL_ST")
            engine._on_trade_closed(c); notify_trade_closed(c)
        st.success(f"Closed {len(trades)} trades"); st.rerun()

    st.divider()
    fg = get_fear_greed_index()
    st.subheader(f"Fear & Greed: {fg.get('value', 50)}")
    st.progress(int(fg.get("value", 50)) / 100)
    
    st.divider()
    st.subheader("🛡 Health")
    st.text(f"Scanner: {'✅' if status_data['running'] else '❌'}")
    ls = status_data["scanner"]["last_scan"]
    st.text(f"Last Scan: {datetime.fromtimestamp(ls).strftime('%H:%M:%S') if ls else '—'}")
    st.text(f"WS Prices: {get_ws_price_count()}")
    
    st.divider()
    from scanner import build_scan_universe
    universe = build_scan_universe()[:10]
    st.subheader("📈 Top Scan Symbols")
    for i, (sym, score) in enumerate(universe):
        st.caption(f"#{i+1} **{sym}**: {score:.1f}")

# --- Main Tabs ---
tab_dash, tab_open, tab_sig, tab_history, tab_perf, tab_cfg, tab_logs = st.tabs([
    "📊 Dashboard", "📈 Open Trades", "🔍 Signals", "📁 History", "🏆 Performance", "⚙ Config", "🖥 Logs"
])

auto_refresh = st.sidebar.toggle("Auto-refresh (5s)", value=True)

# --- Tab 1: Dashboard ---
with tab_dash:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Net PnL (Total)", f"${status_data['total_net_pnl']:,.4f}", f"{status_data['pnl_pct']}%")
    col2.metric("Win Rate", f"{status_data['win_rate']}%", f"{status_data['stats']['wins']}W / {status_data['stats']['losses']}L")
    col3.metric("Open Trades", status_data["open_count"])
    
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_pnl = status_data["stats"].get("daily_pnl", {}).get(today, 0.0)
    col4.metric("Today PnL", f"${today_pnl:,.2f}")

    st.divider()
    c1, c2 = st.columns(2)
    c1.metric("Realized PnL", f"${status_data['realized_pnl']:,.4f}")
    c2.metric("Unrealized PnL", f"${status_data['unrealized_pnl']:,.4f}", 
              delta=status_data['unrealized_pnl'], delta_color="normal")

    st.divider()
    initial_wallet = 1000.0
    target = initial_wallet * 0.30
    progress = min(status_data['total_net_pnl'] / target, 1.0) if status_data['total_net_pnl'] > 0 else 0.0
    st.subheader(f"Monthly Target Progress (30% = ${target:,.2f})")
    st.progress(progress)
    st.caption(f"Total PnL: ${status_data['total_net_pnl']:,.2f} | Progress: {progress*100:.1f}% | Remaining: ${max(target-status_data['total_net_pnl'], 0):,.2f}")
    
    daily_data = status_data["stats"].get("daily_pnl", {})
    if daily_data:
        df_daily = pd.DataFrame(list(daily_data.items()), columns=["Date", "PnL"]).sort_values("Date")
        df_daily["Cumulative PnL"] = df_daily["PnL"].cumsum()
        fig = px.line(df_daily, x="Date", y="Cumulative PnL", title="Cumulative PnL Growth (Realized)")
        fig.update_layout(template="plotly_dark", height=400)
        st.plotly_chart(fig, use_container_width=True)

# --- Tab 2: Open Trades ---
with tab_open:
    trades = status_data["snapshot"]["open_trades"]
    if not trades:
        st.info("No open trades at the moment.")
    else:
        symbols = list({t["symbol"] for t in trades})
        prices = get_current_prices_batch(symbols)
        display_trades = []
        for t in trades:
            cur = prices.get(t["symbol"], 0)
            pnl_val, pnl_pct = 0, 0
            if cur > 0 and t.get("entry_price", 0) > 0:
                entry, margin, leverage = float(t["entry_price"]), float(t.get("size", 0)), float(t.get("leverage", 10))
                contracts = float(t.get("contracts", 0))
                if contracts <= 0: contracts = (margin * leverage) / entry
                pnl_val = (cur - entry) * contracts * (1 if t["direction"] == "LONG" else -1)
                pnl_pct = (pnl_val / margin * 100) if margin > 0 else 0
            
            display_trades.append({
                "Symbol": t["symbol"], "Dir": t["direction"], "Entry": t["entry_price"], "Current": cur,
                "PnL $": round(pnl_val, 4), "PnL %": round(pnl_pct, 2), "Margin": t.get("size", 0),
                "Lev": t.get("leverage", 10), "SL": t.get("sl", 0), "TP1": t.get("tp1", 0), "TP2": t.get("tp2", 0),
                "Strategy": t.get("strategy", ""), "Time": t.get("open_time", "")[:19], "ID": t["id"]
            })
        st.dataframe(pd.DataFrame(display_trades), use_container_width=True, hide_index=True)
        
        with st.expander("Close Trade"):
            sid = sid = st.selectbox("Select Trade ID", options=[t["ID"] for t in display_trades])
            if st.button("Close Trade", type="primary"):
                from trade_executor import close_trade
                from notifier import notify_trade_closed
                found = next((t for t in trades if t["id"] == sid), None)
                if found:
                    c = close_trade(found, prices.get(found["symbol"], found["entry_price"]), "MANUAL_ST")
                    engine._on_trade_closed(c); notify_trade_closed(c); st.success(f"Closed {found['symbol']}"); st.rerun()

# --- Tab 3: Signals ---
with tab_sig:
    signals = status_data["snapshot"]["signals"]
    if not signals: st.info("No signals detected yet.")
    else:
        df_sig = pd.DataFrame(signals)
        st.dataframe(df_sig[["symbol", "direction", "score", "price", "sl", "tp1", "tp2", "strategy", "executed", "time"]], use_container_width=True, hide_index=True)

# --- Tab 4: History ---
with tab_history:
    closed = status_data["snapshot"]["closed_trades"]
    if not closed: st.info("No trade history yet.")
    else:
        df_closed = pd.DataFrame(closed).sort_values("close_time", ascending=False)
        st.dataframe(df_closed[["symbol", "direction", "entry_price", "exit_price", "net_pnl", "close_reason", "strategy", "close_time"]], use_container_width=True, hide_index=True)

# --- Tab 5: Performance ---
with tab_perf:
    perf = status_data["stats"].get("strategy_performance", {})
    if not perf: st.info("No performance data yet.")
    else:
        perf_data = []
        for name, d in perf.items():
            t, w = d.get("trades", 0), d.get("wins", 0)
            perf_data.append({"Strategy": name, "Trades": t, "Win Rate": f"{round(w/t*100,1) if t else 0}%", "Net PnL": d.get("net_pnl", 0), "Avg PnL": round(d.get("net_pnl", 0)/t, 2) if t else 0})
        st.table(pd.DataFrame(perf_data))

# --- Tab 6: Config ---
with tab_cfg:
    cfg = engine.config
    with st.form("config_form"):
        c1, c2, c3 = st.columns(3)
        new_mode = c1.selectbox("Trade Mode", ["AUTO", "MANUAL"], index=0 if cfg.get("mode")=="AUTO" else 1)
        new_wallet = c2.number_input("Wallet Balance ($)", value=float(cfg.get("wallet_balance", 1000)), step=100.0)
        new_risk = c3.number_input("Risk % (AUTO)", value=float(cfg.get("risk_pct", 2.5)), step=0.1)
        c4, c5, c6 = st.columns(3)
        new_lev = c4.number_input("Leverage", value=int(cfg.get("leverage", 10)), min_value=1)
        new_max_trades = c5.number_input("Max Open Trades", value=int(cfg.get("max_trades", 3)), min_value=1)
        new_interval = c6.number_input("Scan Interval (s)", value=int(cfg.get("scan_interval", 60)), min_value=30)
        if st.form_submit_button("Save Configuration", type="primary"):
            updates = {"mode": new_mode, "wallet_balance": new_wallet, "risk_pct": new_risk, "leverage": new_lev, "max_trades": new_max_trades, "scan_interval": new_interval}
            with engine.lock: engine.config.update(updates)
            engine.db.save_state(engine.snapshot()); st.success("Config saved!"); st.rerun()

# --- Tab 7: Logs ---
with tab_logs:
    logs = list(_log_buffer)[:200]
    log_html = "".join([f"<div class='log-entry' style='color: {'#ef4444' if 'ERROR' in l else '#22c55e' if 'opened' in l or '✅' in l else '#e2e8f0'}'>{l}</div>" for l in logs])
    st.markdown(f"<div style='background-color: #0e1117; padding: 15px; border-radius: 5px; height: 500px; overflow-y: auto;'>{log_html}</div>", unsafe_allow_html=True)

if auto_refresh:
    time.sleep(5); st.rerun()
