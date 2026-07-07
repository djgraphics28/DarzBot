"""Interactive Streamlit dashboard — run with: streamlit run dashboard/app.py"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from bot.broker import (
    cancel_pending,
    close_position,
    get_account,
    get_pending,
    get_positions,
    get_rates,
    get_tick,
    place_scaled_orders,
)
from bot.config import SL_DISTANCE, SYMBOL, TP_LEVELS, VOLUME
from bot.db import init_db, is_auto_trade_on, recent_trades, set_state
from bot.strategy import add_indicators

st.set_page_config(page_title="XAUUSD Bot", layout="wide", page_icon="📈",
                   initial_sidebar_state="expanded")

# ── Compact styling: smaller buttons, tighter spacing, condensed metrics ────
st.markdown("""
<style>
  .block-container { padding-top: 1.2rem; padding-bottom: 1rem; }
  .stButton button {
      padding: 0.15rem 0.4rem; font-size: 0.78rem; min-height: 0; line-height: 1.1;
  }
  section[data-testid="stSidebar"] .stButton button { width: 100%; }
  div[data-testid="stMetric"] { padding: 2px 0; }
  div[data-testid="stMetricValue"] { font-size: 1.05rem; }
  div[data-testid="stMetricLabel"] { font-size: 0.7rem; }
  div[data-testid="stMetricDelta"] { font-size: 0.75rem; }
  .stNumberInput input { padding: 0.15rem 0.4rem; }
  section[data-testid="stSidebar"] { width: 320px !important; }
  h1 { font-size: 1.4rem; margin-bottom: 0.2rem; }
  .row-widget.stRadio > div { gap: 0.4rem; }
  hr { margin: 0.5rem 0; }
</style>
""", unsafe_allow_html=True)

if "db_ready" not in st.session_state:
    init_db()
    st.session_state.db_ready = True


def _safe(fn, fallback):
    try:
        return fn()
    except Exception:
        return fallback


def _manual_order(side: str, vol: float, sl_dist: float, tp_levels: list,
                  entry_price: float = 0.0, order_kind: str = "Market"):
    pending = order_kind in ("Limit", "Stop")
    if pending:
        if entry_price <= 0:
            st.session_state.flash = f"Enter a valid {order_kind} price first"
            st.rerun()
            return
        entry = entry_price
        order_type = f"{side}_{order_kind.lower()}"
    else:
        tick = get_tick()
        entry = tick["ask"] if side == "buy" else tick["bid"]
        order_type = ""

    results = place_scaled_orders(side, entry, sl_dist, tp_levels,
                                  volume=vol, pending=pending, order_type=order_type)
    ok = sum(1 for _, r in results if r.get("retcode") == 10009)
    fail = len(results) - ok
    label = f"{side.upper()} {order_kind}"
    if fail == 0:
        st.session_state.flash = f"{label} — {ok} leg(s) @ {entry:.2f}"
    else:
        err = next((r.get("comment") for _, r in results if r.get("retcode") != 10009), "")
        st.session_state.flash = f"{label} — {ok} placed, {fail} failed ({err})"
    st.rerun()


# ── Sidebar: all controls (no auto-refresh here) ────────────────────────────
def sidebar_controls():
    sb = st.sidebar
    sb.title(f"{SYMBOL} Bot")

    # Auto-trade toggle
    auto_on = is_auto_trade_on()
    sb.markdown(f"**Auto-Trading:** {'🟢 ON' if auto_on else '🔴 OFF'}")
    if auto_on:
        if sb.button("⏸ Stop Auto-Trade", type="secondary"):
            set_state("auto_trade", "off"); st.rerun()
    else:
        if sb.button("▶ Start Auto-Trade", type="primary"):
            set_state("auto_trade", "on"); st.rerun()

    sb.divider()

    # Manual entry
    sb.markdown("**Manual Entry**")
    order_kind = sb.radio("Order type", ["Market", "Limit", "Stop"],
                          horizontal=True, key="man_kind", label_visibility="collapsed")

    col_v, col_s = sb.columns(2)
    vol = col_v.number_input("Lot", min_value=0.01, value=float(VOLUME), step=0.01, key="man_vol")
    sl_dist = col_s.number_input("SL $", min_value=0.0, value=float(SL_DISTANCE), step=0.5, key="man_sl")

    if order_kind == "Market":
        entry_price = 0.0
    else:
        entry_price = sb.number_input(f"{order_kind} entry price", min_value=0.0,
                                      value=0.0, step=0.1, key="man_entry")

    # Dynamic TP list
    if "tp_list" not in st.session_state:
        st.session_state.tp_list = list(TP_LEVELS) or [6.0]
    sb.caption("Take-Profit levels ($)")
    tp_levels = []
    for i, val in enumerate(st.session_state.tp_list):
        row, rm = sb.columns([4, 1])
        tp_levels.append(row.number_input(f"TP{i+1}", min_value=0.5, value=float(val),
                                          step=0.5, key=f"tp_{i}", label_visibility="collapsed"))
        if rm.button("✖", key=f"tp_rm_{i}"):
            st.session_state.tp_list.pop(i); st.rerun()
    st.session_state.tp_list = tp_levels
    if sb.button("➕ Add TP"):
        last = tp_levels[-1] if tp_levels else 0.0
        st.session_state.tp_list.append(round(last + 6.0, 1)); st.rerun()

    desc = "market" if order_kind == "Market" else f"{order_kind.lower()} @ {entry_price:.2f}"
    sb.caption(f"→ {len(tp_levels)} {desc} trade(s), {vol} lots each")

    b, s = sb.columns(2)
    if b.button(f"🟢 BUY", key="man_buy", type="primary"):
        _manual_order("buy", vol, sl_dist, tp_levels, entry_price, order_kind)
    if s.button(f"🔴 SELL", key="man_sell"):
        _manual_order("sell", vol, sl_dist, tp_levels, entry_price, order_kind)

    sb.divider()
    if sb.button("✖ Close ALL positions"):
        closed = failed = 0
        for p in _safe(get_positions, []):
            if close_position(p["ticket"]).get("retcode") == 10009:
                closed += 1
            else:
                failed += 1
        st.session_state.flash = f"Closed {closed}" + (f", {failed} failed" if failed else "")
        st.rerun()


# ── Main area: live data (auto-refreshes every 5s) ──────────────────────────
@st.fragment(run_every="1s")
def live_view():
    try:
        acct = get_account()
        tick = get_tick()
    except Exception as e:
        st.error(f"Bridge unreachable: {e}")
        return

    # Compact top metric strip: account + price all in one row
    m = st.columns(6)
    m[0].metric("Balance", f"{acct['balance']:,.0f}")
    m[1].metric("Equity", f"{acct['equity']:,.2f}")
    m[2].metric("Open P&L", f"{acct['profit']:+.2f}", delta=f"{acct['profit']:+.2f}")
    m[3].metric("Free Margin", f"{acct['free_margin']:,.0f}")
    m[4].metric("Bid", f"{tick['bid']:.2f}")
    m[5].metric("Ask", f"{tick['ask']:.2f}")
    st.caption(f"Live · updates every 1s · {pd.Timestamp.now().strftime('%H:%M:%S')} · "
               f"spread {round((tick['ask'] - tick['bid']) * 10, 1)} pts")

    chart_col, side_col = st.columns([2.4, 1])

    # ── Chart (main focus) ──
    with chart_col:
        df = add_indicators(get_rates(count=120))
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df["time"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
            name=SYMBOL, increasing_line_color="#26a69a", decreasing_line_color="#ef5350"))
        fig.add_trace(go.Scatter(x=df["time"], y=df["ema"], name="EMA50",
                                 line=dict(color="#ff9800", width=1.3)))
        for p in _safe(get_positions, []):
            color = "#26a69a" if p.get("type") == 0 else "#ef5350"
            fig.add_hline(y=p["price_open"], line_dash="dot", line_color=color, line_width=1)
        for o in _safe(get_pending, []):
            fig.add_hline(y=o["price_open"], line_dash="dash", line_color="#9e9e9e", line_width=1)
        fig.update_layout(height=340, margin=dict(l=0, r=0, t=6, b=0),
                          xaxis_rangeslider_visible=False, template="plotly_dark",
                          showlegend=False)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        with st.expander("Stochastic %K / %D"):
            sfig = go.Figure()
            sfig.add_trace(go.Scatter(x=df["time"], y=df["%K"], name="%K", line=dict(color="#42a5f5")))
            sfig.add_trace(go.Scatter(x=df["time"], y=df["%D"], name="%D", line=dict(color="#ab47bc")))
            sfig.add_hline(y=80, line_dash="dash", line_color="gray")
            sfig.add_hline(y=20, line_dash="dash", line_color="gray")
            sfig.update_layout(height=160, margin=dict(l=0, r=0, t=4, b=0),
                               template="plotly_dark", yaxis_range=[0, 100], showlegend=False)
            st.plotly_chart(sfig, use_container_width=True, config={"displayModeBar": False})

    # ── Positions + pending (compact list, close/cancel buttons) ──
    with side_col:
        st.markdown("**Open Positions**")
        positions = get_positions()
        if positions:
            for p in positions:
                t = p["ticket"]
                side = "BUY" if p.get("type") == 0 else "SELL"
                profit = p.get("profit", 0.0)
                dot = "🟢" if profit >= 0 else "🔴"
                info, btn = st.columns([3, 1])
                info.markdown(
                    f"<span style='font-size:0.8rem'>{dot} <b>{side}</b> {p['volume']} "
                    f"@ {p['price_open']:.2f} · <b>{profit:+.2f}</b></span>",
                    unsafe_allow_html=True)
                if btn.button("✖", key=f"close_{t}"):
                    res = close_position(t)
                    st.session_state.flash = (f"Closed #{t}" if res.get("retcode") == 10009
                                              else f"Close failed: {res.get('comment')}")
                    st.rerun()
        else:
            st.caption("None")

        pending = get_pending()
        if pending:
            st.markdown("**Pending**")
            _pt = {2: "BUY LMT", 3: "SELL LMT", 4: "BUY STP", 5: "SELL STP"}
            for o in pending:
                t = o["ticket"]
                info, btn = st.columns([3, 1])
                info.markdown(
                    f"<span style='font-size:0.8rem'>⏳ <b>{_pt.get(o.get('type'), '?')}</b> "
                    f"{o['volume_current']} @ {o['price_open']:.2f}</span>",
                    unsafe_allow_html=True)
                if btn.button("✖", key=f"cancel_{t}"):
                    res = cancel_pending(t)
                    st.session_state.flash = (f"Cancelled #{t}" if res.get("retcode") == 10009
                                              else f"Cancel failed: {res.get('comment')}")
                    st.rerun()


# ── Render ──────────────────────────────────────────────────────────────────
sidebar_controls()

if st.session_state.get("flash"):
    st.toast(st.session_state.pop("flash"))

live_view()

with st.expander("📜 Trade History"):
    trades = recent_trades(50)
    if trades:
        dft = pd.DataFrame(trades)
        if "final_profit" in dft.columns:
            closed = dft["final_profit"].dropna()
            h = st.columns(3)
            h[0].metric("Total P&L", f"{closed.sum():+.2f}")
            h[1].metric("Closed", int(closed.count()))
            h[2].metric("Win Rate", f"{(closed > 0).mean() * 100:.0f}%" if len(closed) else "—")
        st.dataframe(dft, use_container_width=True, hide_index=True, height=220)
    else:
        st.caption("No trades logged yet")
