"""Main bot — signal loop + real-time position monitor, running on Mac inside Docker."""
import logging
import signal
import sys
import threading
import time

from bot import alerts, broker, db
from bot.config import (
    MAX_POSITIONS, POLL_INTERVAL, SL_DISTANCE, SYMBOL, TP_LEVELS, VOLUME,
)
from bot.position_tracker import monitor_loop
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

            # Skip entry if already at max open positions
            if MAX_POSITIONS > 0:
                open_pos = broker.get_positions(SYMBOL)
                if len(open_pos) >= MAX_POSITIONS:
                    logger.info("Max positions reached (%s) — skipping signal check", MAX_POSITIONS)
                    _stop.wait(POLL_INTERVAL)
                    continue

            df = broker.get_rates()
            sig = get_signal(df)

            # Live indicator snapshot so you can see the loop is alive and why
            snap = add_indicators(df).iloc[-1]
            logger.info(
                "AUTO ON  close=%.2f  ema=%.2f  %%K=%.1f  %%D=%.1f  -> signal=%s",
                snap["close"], snap["ema"], snap["%K"], snap["%D"], sig or "none",
            )

            if sig:
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
