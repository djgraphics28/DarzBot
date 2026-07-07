"""Real-time position monitor — runs in a background thread."""
import logging
import time
from bot import alerts, broker, db
from bot.config import (
    MONITOR_INTERVAL, PROFIT_TARGET, SCALP_MODE, SYMBOL, MAX_LOSS, LOSS_COOLDOWN,
)

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

            # Manual-trade interlock: which tickets did the user open manually,
            # and reconcile the set so cancelled/closed manual tickets self-clear.
            manual = db.get_manual_tickets()
            if manual:
                live = current_tickets | {p.get("identifier") for p in positions}
                try:
                    live |= {o["ticket"] for o in broker.get_pending(SYMBOL)}
                except Exception:
                    pass
                for t in manual - live:
                    db.remove_manual_ticket(t)

            def _is_manual(pos) -> bool:
                return pos["ticket"] in manual or pos.get("identifier") in manual

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
                    db.remove_manual_ticket(ticket)
                    # Cooldown after a losing close, so we don't instantly re-enter
                    if snap["profit"] < 0 and LOSS_COOLDOWN > 0:
                        db.set_state("cooldown_until", str(time.time() + LOSS_COOLDOWN))
                        logger.info("Loss cooldown: pausing entries for %ss", LOSS_COOLDOWN)
                    del known[ticket]

            # Update / register open positions
            for pos in positions:
                ticket = pos["ticket"]
                profit = pos.get("profit", 0.0)
                side = "buy" if pos.get("type") == 0 else "sell"
                price = pos.get("price_current", 0.0)

                # Never auto-manage a manually-opened trade — leave it to the user
                if _is_manual(pos):
                    continue

                # Safety net (any mode): emergency close on large loss
                if MAX_LOSS > 0 and profit <= -MAX_LOSS:
                    res = broker.close_position(ticket)
                    logger.warning("MAX LOSS hit  ticket=%s  profit=%.2f -> %s",
                                   ticket, profit,
                                   "closed" if res.get("retcode") == 10009 else res.get("comment"))
                    continue

                # Scalp exit: bank profit as soon as it hits the target
                if SCALP_MODE and profit >= PROFIT_TARGET:
                    res = broker.close_position(ticket)
                    if res.get("retcode") == 10009:
                        logger.info("Profit target hit  ticket=%s  profit=%.2f -> closed",
                                    ticket, profit)
                    else:
                        logger.warning("Target-close failed  ticket=%s  %s",
                                       ticket, res.get("comment"))
                    # Skip further processing this cycle; closure detected next loop
                    continue

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
