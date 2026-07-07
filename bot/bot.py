"""Main bot — signal loop + real-time position monitor, running on Mac inside Docker."""
import logging
import signal
import sys
import threading
import time

from bot import ai_analyst, alerts, broker, db
from bot.config import (
    AI_ENABLED, AI_MIN_CONFIDENCE, MAX_POSITIONS, POLL_INTERVAL, PROFIT_TARGET,
    SCALP_MODE, SL_DISTANCE, SYMBOL, TP_LEVELS, VOLUME,
)
from bot.position_tracker import monitor_loop
from bot import strategy
from bot.strategy import add_indicators, get_signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
_stop = threading.Event()


def _handle_signal(sig, frame):
    logger.info("Shutdown signal received")
    _stop.set()


# XAUUSD standard contract size (oz per 1.00 lot)
_CONTRACT_SIZE = 100


def _ai_approves(side: str) -> bool:
    """Ask Claude to confirm the entry against the last hour's structure.
    Fail-open: if AI is off or unreachable, don't block the technical signal."""
    if not AI_ENABLED:
        return True
    decision = ai_analyst.analyze()
    if decision is None:
        logger.info("AI unavailable — proceeding on technical signal")
        return True
    agree = decision.signal == side and decision.confidence >= AI_MIN_CONFIDENCE
    verdict = "confirms" if agree else "VETOES"
    logger.info("AI %s %s  structure=%s  conf=%s  (%s)",
                verdict, side.upper(), decision.structure,
                decision.confidence, decision.reason)
    return agree


def _has_margin(price: float) -> bool:
    """True if there is enough free margin to open one more VOLUME lot.
    Estimates required margin from price, contract size, and account leverage."""
    try:
        acct = broker.get_account()
        free = float(acct.get("free_margin", 0))
        lev = float(acct.get("leverage", 100)) or 100
        required = price * _CONTRACT_SIZE * VOLUME / lev
        return free >= required * 1.05  # 5% buffer
    except Exception:
        return True  # if we can't check, let the broker decide


def signal_loop():
    """Checks for entry signals on every new M5 candle (~60s)."""
    logger.info("Signal loop started  symbol=%s  volume=%s  interval=%ss",
                SYMBOL, VOLUME, POLL_INTERVAL)
    while not _stop.is_set():
        try:
            # Auto-trading toggle is controlled live from the dashboard
            if not db.is_auto_trade_on():
                logger.debug("Auto-trade OFF — monitoring only")
                _stop.wait(POLL_INTERVAL)
                continue

            # Manual trade running -> hand control to the user, pause the bot
            if db.is_manual_active():
                logger.info("Manual trade active — auto-trading paused")
                _stop.wait(POLL_INTERVAL)
                continue

            # Skip entry if already at max open positions (live, dashboard-adjustable)
            max_pos = db.get_max_positions()
            if max_pos > 0:
                open_pos = broker.get_positions(SYMBOL)
                if len(open_pos) >= max_pos:
                    logger.info("Max positions reached (%s/%s) — skipping entry",
                                len(open_pos), max_pos)
                    _stop.wait(POLL_INTERVAL)
                    continue

            tf = db.get_timeframe()  # trading timeframe set from the dashboard
            df = broker.get_rates(tf=tf)
            sig = get_signal(df)

            # Live indicator snapshot so you can see the loop is alive and why
            ind = add_indicators(df)
            snap, prev = ind.iloc[-1], ind.iloc[-2]
            trend = strategy.trend_of(snap, prev)
            strong = strategy.trend_strong(snap)
            logger.info(
                "AUTO ON  tf=%s  close=%.2f  trend=%s  strong=%s  rsi=%.0f  atr=%.2f  %%K=%.1f -> signal=%s",
                tf, snap["close"], trend or "flat", strong, snap.get("rsi", 0),
                snap.get("atr", 0), snap["%K"], sig or "none",
            )

            # Cooldown after a losing close
            if time.time() < float(db.get_state("cooldown_until", "0")):
                logger.info("In loss cooldown — skipping entry")
                _stop.wait(POLL_INTERVAL)
                continue

            if SCALP_MODE:
                # Follow the trend (filtered by strength + momentum). Enter a single
                # market trade (no SL/TP) when flat; monitor closes at +$PROFIT_TARGET.
                side = strategy.scalp_side(df)
                if side is None:
                    logger.debug("Scalp: no qualified trend entry — waiting")
                elif not _has_margin(snap["close"]):
                    logger.info("Margin full (%s open) — need higher leverage or lower lot; "
                                "not entering", len(open_pos))
                elif not _ai_approves(side):
                    pass  # AI vetoed — already logged; wait for the next cycle
                else:
                    tick = broker.get_tick()
                    price = tick["ask"] if side == "buy" else tick["bid"]
                    result = broker.place_order(side, sl=0.0, tp=0.0)
                    retcode = result.get("retcode", -1)
                    order_id = result.get("order", 0)
                    comment = result.get("comment", "")
                    db.log_trade(SYMBOL, side, VOLUME, price, retcode, order_id, comment)
                    if retcode == 10009:
                        alerts.order_placed(side, SYMBOL, result.get("price", price), VOLUME)
                        logger.info("Scalp entry  %s  price=%.2f  target=+$%.1f  order_id=%s",
                                    side.upper(), price, PROFIT_TARGET, order_id)
                    else:
                        alerts.order_failed(side, SYMBOL, retcode, comment)
                        logger.warning("Scalp entry failed  retcode=%s  %s", retcode, comment)

            elif sig:
                tick = broker.get_tick()
                price = tick["ask"] if sig == "buy" else tick["bid"]
                logger.info("Signal: %s  price=%.2f  opening %d TP leg(s): %s",
                            sig.upper(), price, len(TP_LEVELS), TP_LEVELS)

                # One trade per TP level, all sharing the same SL (scaling out)
                for tp_dist, result in broker.place_scaled_orders(
                    sig, price, SL_DISTANCE, TP_LEVELS
                ):
                    retcode = result.get("retcode", -1)
                    order_id = result.get("order", 0)
                    comment = result.get("comment", "")
                    db.log_trade(SYMBOL, sig, VOLUME, price, retcode, order_id, comment)

                    if retcode == 10009:  # TRADE_RETCODE_DONE
                        alerts.order_placed(sig, SYMBOL, result.get("price", price), VOLUME)
                        logger.info("Leg placed  TP=$%.1f  order_id=%s", tp_dist, order_id)
                    else:
                        alerts.order_failed(sig, SYMBOL, retcode, comment)
                        logger.warning("Leg failed  TP=$%.1f  retcode=%s  %s",
                                       tp_dist, retcode, comment)
            else:
                logger.debug("No signal")

        except Exception as e:
            logger.error("Signal loop error: %s", e)

        _stop.wait(POLL_INTERVAL)


def main():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Create tables first so the dashboard's controls work even if the bridge is down
    db.init_db()

    logger.info("Connecting to MT5 bridge…")
    while not broker.ping() and not _stop.is_set():
        logger.error("Cannot reach MT5 bridge — check VM_IP in .env. Retrying in 10s…")
        _stop.wait(10)
    if _stop.is_set():
        return
    logger.info("Bridge connected.")

    try:
        acct = broker.get_account()
        logger.info(
            "Account: %s | Balance: %.2f %s | Equity: %.2f",
            acct.get("name"), acct.get("balance"), acct.get("currency"), acct.get("equity"),
        )
        alerts.bot_started()
    except Exception as e:
        logger.warning("Could not fetch account info: %s", e)

    # Background thread: real-time position monitor
    monitor_thread = threading.Thread(
        target=monitor_loop, args=(_stop,), daemon=True, name="monitor"
    )
    monitor_thread.start()

    # Main thread: signal + entry logic
    signal_loop()

    alerts.bot_stopped()
    logger.info("Bot stopped")


if __name__ == "__main__":
    main()
