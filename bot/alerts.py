"""Telegram alert helpers."""
import logging
import requests
from bot.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def send(message: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("Telegram not configured — skipping alert")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=5)
    except requests.RequestException as e:
        logger.warning("Telegram alert failed: %s", e)


def order_placed(side: str, symbol: str, price: float, volume: float) -> None:
    emoji = "BUY" if side == "buy" else "SELL"
    send(f"[{emoji}] {symbol} @ {price:.2f}  vol={volume}")


def order_failed(side: str, symbol: str, retcode: int, comment: str) -> None:
    send(f"[FAILED] {side.upper()} {symbol}  retcode={retcode}  {comment}")


def bot_started() -> None:
    send("[BOT] Started — watching market")


def position_update(symbol: str, side: str, profit: float, price: float) -> None:
    arrow = "▲" if profit >= 0 else "▼"
    sign = "+" if profit >= 0 else ""
    send(f"[PnL] {symbol} {side.upper()}  {arrow} {sign}{profit:.2f}  @ {price:.2f}")


def position_closed(symbol: str, side: str, profit: float, ticket: int) -> None:
    result = "PROFIT" if profit >= 0 else "LOSS"
    sign = "+" if profit >= 0 else ""
    send(f"[CLOSED] {symbol} {side.upper()}  {result}: {sign}{profit:.2f}  ticket={ticket}")


def bot_stopped(reason: str = "") -> None:
    send(f"[BOT] Stopped  {reason}")
