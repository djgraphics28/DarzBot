"""Real-time position monitor — runs in a background thread."""
import logging
import time
from bot import alerts, broker, db
from bot.config import MONITOR_INTERVAL, SYMBOL

logger = logging.getLogger(__name__)


def monitor_loop(stop_event):
    """
    Called in a thread. Polls open positions every MONITOR_INTERVAL seconds,
    logs P&L updates, and fires a Telegram alert when a position closes.
    """
    # ticket -> last known profit, used to detect significant moves
    known: dict[int, dict] = {}

    while not stop_event.is_set():
        try:
            positions = broker.get_positions(SYMBOL)
            current_tickets = {p["ticket"] for p in positions}

            # Detect newly closed positions
            for ticket, snap in list(known.items()):
                if ticket not in current_tickets:
                    logger.info(
                        "Position closed  ticket=%s  final_profit=%.2f",
                        ticket, snap["profit"],
                    )
                    alerts.position_closed(
                        snap["symbol"], snap["side"], snap["profit"], ticket
                    )
                    db.log_close(ticket, snap["profit"])
                    del known[ticket]

            # Update / register open positions
            for pos in positions:
                ticket = pos["ticket"]
                profit = pos.get("profit", 0.0)
                side = "buy" if pos.get("type") == 0 else "sell"
                price = pos.get("price_current", 0.0)

                prev = known.get(ticket)
                known[ticket] = {
                    "profit": profit,
                    "symbol": pos.get("symbol", SYMBOL),
                    "side": side,
                }

                # Log to console every cycle; Telegram only on meaningful change
                logger.info(
                    "Position  ticket=%s  %s  profit=%.2f  @ %.2f",
                    ticket, side.upper(), profit, price,
                )
                if prev is not None:
                    change = abs(profit - prev["profit"])
                    # Alert when profit changes by $1 or more (avoids spam)
                    if change >= 1.0:
                        alerts.position_update(
                            pos.get("symbol", SYMBOL), side, profit, price
                        )

        except Exception as e:
            logger.error("Monitor error: %s", e)

        stop_event.wait(MONITOR_INTERVAL)
