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
from bot.db import get_state, init_db, is_auto_trade_on, recent_trades, set_state
from bot.strategy import add_indicators

st.set_page_config(page_title="XAUUSD Bot", layout="wide", page_icon="📈")
st.title(f"{SYMBOL} Trading Bot — Live Control")

# Ensure tables exist even if the bot container never started (e.g. bridge down)
if "db_ready" not in st.session_state:
    init_db()
    st.session_state.db_ready = True


# ── Control panel (does NOT auto-refresh, so clicks aren't interrupted) ─────
def control_panel():
    auto_on = is_auto_trade_on()

    c1, c2, c3 = st.columns([1.2, 1, 1])

    with c1:
        st.markdown("**Auto-Trading**")
        status = "🟢 ON" if auto_on else "🔴 OFF"
        st.markdown(f"### {status}")
        if auto_on:
            if st.button("⏸ Stop Auto-Trade", use_container_width=True, type="secondary"):
                set_state("auto_trade", "off")
                st.rerun()
        else:
            if st.button("▶ Start Auto-Trade", use_container_width=True, type="primary"):
                set_state("auto_trade", "on")
                st.rerun()

    with c2:
        st.markdown("**Manual Entry**")
        vol = st.number_input("Lot size (per TP leg)", min_value=0.01, value=float(VOLUME),
                              step=0.01, key="man_vol")
        sl_dist = st.number_input("SL $", min_value=0.0, value=float(SL_DISTANCE),
                                  step=0.5, key="man_sl")
        entry_price = st.number_input(
            "Entry price (0 = market now)", min_value=0.0, value=0.0, step=0.1,
            key="man_entry",
            help="Leave 0 for instant market order. Set a price to place a "
                 "pending limit/stop order that fills when the market reaches it.",
        )

        # Dynamic TP list held in session state
        if "tp_list" not in st.session_state:
            st.session_state.tp_list = list(TP_LEVELS) or [6.0]

        st.markdown("**Take-Profit levels**")
        tp_levels = []
        for i, val in enumerate(st.session_state.tp_list):
            row, rm = st.columns([4, 1])
            new_val = row.number_input(f"TP {i + 1} ($)", min_value=0.5, value=float(val),
                                       step=0.5, key=f"tp_{i}")
            tp_levels.append(new_val)
            if rm.button("✖", key=f"tp_rm_{i}", help="Remove this TP"):
                st.session_state.tp_list.pop(i)
                st.rerun()
        st.session_state.tp_list = tp_levels

        add_col, _ = st.columns([1, 1])
        if add_col.button("➕ Add TP", use_container_width=True, key="tp_add"):
            # New level defaults to the last one + 6
            last = st.session_state.tp_list[-1] if st.session_state.tp_list else 0.0
            st.session_state.tp_list.append(round(last + 6.0, 1))
            st.rerun()

        order_kind = "pending @ " + f"{entry_price:.2f}" if entry_price > 0 else "market"
        st.caption(f"→ opens {len(tp_levels)} {order_kind} trade(s) of {vol} lots each")
        bcol, scol = st.columns(2)
        if bcol.button("🟢 BUY", use_container_width=True, key="man_buy"):
            _manual_order("buy", vol, sl_dist, tp_levels, entry_price)
        if scol.button("🔴 SELL", use_container_width=True, key="man_sell"):
            _manual_order("sell", vol, sl_dist, tp_levels, entry_price)

    with c3:
        st.markdown("**Quick Actions**")
        st.caption("Close buttons are on each position below ↓")
        if st.button("✖ Close ALL positions", use_container_width=True, key="close_all"):
            closed, failed = 0, 0
            for p in _safe(get_positions, []):
                if close_position(p["ticket"]).get("retcode") == 10009:
                    closed += 1
                else:
                    failed += 1
            st.session_state.flash = f"Closed {closed} position(s)" + (f", {failed} failed" if failed else "")
            st.rerun()


def _manual_order(side: str, vol: float, sl_dist: float, tp_levels: list, entry_price: float = 0.0):
    pending = entry_price > 0
    if pending:
        entry = entry_price
    else:
        tick = get_tick()
        entry = tick["ask"] if side == "buy" else tick["bid"]
    results = place_scaled_orders(side, entry, sl_dist, tp_levels, volume=vol, pending=pending)
    ok = sum(1 for _, r in results if r.get("retcode") == 10009)
    fail = len(results) - ok
    kind = "pending" if pending else "market"
    if fail == 0:
        st.session_state.flash = f"{side.upper()} — {ok} {kind} leg(s) @ {entry:.2f}"
    else:
        first_err = next((r.get("comment") for _, r in results if r.get("retcode") != 10009), "")
        st.session_state.flash = f"{side.upper()} — {ok} placed, {fail} failed ({first_err})"
    st.rerun()


def _flash_order(res: dict, label: str):
    if res.get("retcode") == 10009:
        st.session_state.flash = f"{label} placed @ {res.get('price'):.2f}"
    else:
        st.session_state.flash = f"{label} failed: {res.get('comment')} (retcode {res.get('retcode')})"
    st.rerun()


def _safe(fn, fallback):
    try:
        return fn()
    except Exception:
        return fallback


control_panel()

# Show the result of the last close/order action (survives one rerun)
if st.session_state.get("flash"):
    st.toast(st.session_state.pop("flash"))

st.divider()


# ── Live data (auto-refreshes every 5s via fragment) ───────────────────────
@st.fragment(run_every="5s")
def live_view():
    st.caption(f"Live · updates every 5s · {pd.Timestamp.now().strftime('%H:%M:%S')}")

    # Account row
    try:
        acct = get_account()
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Balance", f"{acct['currency']} {acct['balance']:,.2f}")
        a2.metric("Equity", f"{acct['currency']} {acct['equity']:,.2f}")
        a3.metric("Open P&L", f"{acct['profit']:+.2f}", delta=f"{acct['profit']:+.2f}")
        a4.metric("Free Margin", f"{acct['currency']} {acct['free_margin']:,.2f}")
    except Exception as e:
        st.error(f"Bridge unreachable: {e}")
        return

    # Tick + positions
    tcol, pcol = st.columns([1, 2])
    with tcol:
        tick = get_tick()
        st.metric("Bid", f"{tick['bid']:.2f}")
        st.metric("Ask", f"{tick['ask']:.2f}")
        st.caption(f"Spread: {round((tick['ask'] - tick['bid']) * 10, 1)} pts")
    with pcol:
        st.markdown("**Open Positions**")
        positions = get_positions()
        if positions:
            for p in positions:
                ticket = p["ticket"]
                side = "BUY" if p.get("type") == 0 else "SELL"
                profit = p.get("profit", 0.0)
                emoji = "🟢" if profit >= 0 else "🔴"
                info_col, btn_col = st.columns([3, 1])
                info_col.markdown(
                    f"**{side}** {p['volume']} @ {p['price_open']:.2f}  ·  "
                    f"now {p.get('price_current', 0):.2f}  ·  "
                    f"SL {p.get('sl', 0):.2f} / TP {p.get('tp', 0):.2f}  ·  "
                    f"{emoji} **{profit:+.2f}**  ·  #{ticket}"
                )
                if btn_col.button("✖ Close", key=f"close_{ticket}", use_container_width=True):
                    res = close_position(ticket)
                    if res.get("retcode") == 10009:
                        st.session_state.flash = f"Closed #{ticket}"
                    else:
                        st.session_state.flash = f"Close failed: {res.get('comment')}"
                    st.rerun()
        else:
            st.info("No open positions")

        # Pending (limit/stop) orders waiting to fill
        pending = get_pending()
        if pending:
            st.markdown("**Pending Orders**")
            _ptype = {2: "BUY LIMIT", 3: "SELL LIMIT", 4: "BUY STOP", 5: "SELL STOP"}
            for o in pending:
                pt = _ptype.get(o.get("type"), str(o.get("type")))
                oticket = o["ticket"]
                info_col, btn_col = st.columns([3, 1])
                info_col.markdown(
                    f"⏳ **{pt}** {o['volume_current']} @ {o['price_open']:.2f}  ·  "
                    f"SL {o.get('sl', 0):.2f} / TP {o.get('tp', 0):.2f}  ·  #{oticket}"
                )
                if btn_col.button("✖ Cancel", key=f"cancel_{oticket}", use_container_width=True):
                    res = cancel_pending(oticket)
                    st.session_state.flash = (
                        f"Cancelled #{oticket}" if res.get("retcode") == 10009
                        else f"Cancel failed: {res.get('comment')}"
                    )
                    st.rerun()

    # ── 5-minute candlestick chart with EMA + trade markers ────────────────
    st.markdown("**5-Minute Candles**")
    df = get_rates(count=120)
    df = add_indicators(df)

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df["time"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name=SYMBOL,
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
    ))
    fig.add_trace(go.Scatter(
        x=df["time"], y=df["ema"], name="EMA50",
        line=dict(color="#ff9800", width=1.5),
    ))

    # Mark open-position entry prices as horizontal lines
    for p in _safe(get_positions, []):
        side = "BUY" if p.get("type") == 0 else "SELL"
        color = "#26a69a" if side == "BUY" else "#ef5350"
        fig.add_hline(y=p["price_open"], line_dash="dot", line_color=color,
                      annotation_text=f"{side} #{p['ticket']}", annotation_position="right")

    fig.update_layout(
        height=460, margin=dict(l=0, r=0, t=10, b=0),
        xaxis_rangeslider_visible=False, template="plotly_dark",
        legend=dict(orientation="h", y=1.02, x=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Stochastic sub-chart
    st.markdown("**Stochastic %K / %D**")
    sfig = go.Figure()
    sfig.add_trace(go.Scatter(x=df["time"], y=df["%K"], name="%K", line=dict(color="#42a5f5")))
    sfig.add_trace(go.Scatter(x=df["time"], y=df["%D"], name="%D", line=dict(color="#ab47bc")))
    sfig.add_hline(y=80, line_dash="dash", line_color="gray")
    sfig.add_hline(y=20, line_dash="dash", line_color="gray")
    sfig.update_layout(height=200, margin=dict(l=0, r=0, t=10, b=0),
                       template="plotly_dark", yaxis_range=[0, 100],
                       legend=dict(orientation="h", y=1.1, x=0))
    st.plotly_chart(sfig, use_container_width=True)


live_view()
st.divider()

# ── Trade history ──────────────────────────────────────────────────────────
st.subheader("Trade History")
trades = recent_trades(50)
if trades:
    dft = pd.DataFrame(trades)
    if "final_profit" in dft.columns:
        closed = dft["final_profit"].dropna()
        m1, m2, m3 = st.columns(3)
        m1.metric("Total P&L", f"{closed.sum():+.2f}")
        m2.metric("Closed Trades", int(closed.count()))
        m3.metric("Win Rate", f"{(closed > 0).mean() * 100:.0f}%" if len(closed) else "—")
    st.dataframe(dft, use_container_width=True, hide_index=True)
else:
    st.info("No trades logged yet")
