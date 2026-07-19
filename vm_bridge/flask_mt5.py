"""Flask bridge — runs inside the Windows VM alongside MT5.

The MT5 connection is checked before every request and re-established
automatically, so the bridge survives the terminal being closed/reopened
(the old version connected once at startup and returned "IPC send failed"
forever after the terminal restarted).
"""
import logging
import os
import threading
from flask import Flask, jsonify, request
import MetaTrader5 as mt5

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s %(message)s")
log = logging.getLogger("flask_mt5")

app = Flask(__name__)

# Credentials come from environment variables — never hardcode them here.
# Set them in the VM before running, e.g. (PowerShell):
#   $env:MT5_LOGIN="5052702771"; $env:MT5_PASSWORD="..."; $env:MT5_SERVER="Broker-Demo"
# All optional: with no credentials the bridge attaches to the account already
# logged in inside the MT5 terminal. Set MT5_PATH if the terminal is installed
# somewhere non-standard, e.g. C:\Program Files\MetaTrader 5\terminal64.exe
MT5_LOGIN = os.getenv("MT5_LOGIN")
MT5_PASSWORD = os.getenv("MT5_PASSWORD")
MT5_SERVER = os.getenv("MT5_SERVER")
MT5_PATH = os.getenv("MT5_PATH")

_connect_lock = threading.Lock()


def _connect() -> bool:
    """(Re)initialize the MT5 connection. Returns True when connected."""
    mt5.shutdown()  # drop any dead half-open connection first

    kwargs = {}
    if MT5_PATH:
        kwargs["path"] = MT5_PATH
    if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
        kwargs.update(login=int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER)

    ok = mt5.initialize(**kwargs)
    if ok:
        info = mt5.account_info()
        log.info("MT5 connected  login=%s  server=%s",
                 getattr(info, "login", "?"), getattr(info, "server", "?"))
    else:
        log.warning("MT5 initialize failed: %s", mt5.last_error())
    return ok


def _is_connected() -> bool:
    """terminal_info() returns None whenever the IPC link is dead."""
    return mt5.terminal_info() is not None


@app.before_request
def _ensure_mt5():
    """Reconnect on demand so a terminal restart never requires a bridge restart."""
    if request.path == "/ping":
        return None
    if not _is_connected():
        with _connect_lock:
            if not _is_connected() and not _connect():
                return jsonify({"error": ["mt5_disconnected", str(mt5.last_error())]}), 503
    return None


@app.route("/ping")
def ping():
    return jsonify({"status": "ok", "mt5": _is_connected()})


@app.route("/rates")
def get_rates():
    symbol = request.args.get("symbol", "XAUUSD")
    tf = int(request.args.get("tf", mt5.TIMEFRAME_M5))
    count = int(request.args.get("count", 200))
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None:
        return jsonify({"error": mt5.last_error()}), 500
    return jsonify(rates.tolist())


@app.route("/tick")
def get_tick():
    symbol = request.args.get("symbol", "XAUUSD")
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return jsonify({"error": mt5.last_error()}), 500
    return jsonify({"bid": tick.bid, "ask": tick.ask, "time": tick.time})


@app.route("/order", methods=["POST"])
def place_order():
    data = request.json
    symbol = data.get("symbol", "XAUUSD")
    side = data["side"]  # "buy" | "sell"
    volume = float(data.get("volume", 0.01))
    sl = data.get("sl", 0.0)
    tp = data.get("tp", 0.0)

    tick = mt5.symbol_info_tick(symbol)
    price = tick.ask if side == "buy" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL

    request_dict = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 10,
        "magic": 12345,
        "comment": "xauusd-bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request_dict)
    return jsonify({
        "retcode": result.retcode,
        "order": result.order,
        "price": result.price,
        "comment": result.comment,
    })


_PENDING_TYPES = {
    "buy_limit":  mt5.ORDER_TYPE_BUY_LIMIT,
    "sell_limit": mt5.ORDER_TYPE_SELL_LIMIT,
    "buy_stop":   mt5.ORDER_TYPE_BUY_STOP,
    "sell_stop":  mt5.ORDER_TYPE_SELL_STOP,
}


@app.route("/pending", methods=["POST"])
def place_pending():
    """Place a pending order at a specific entry price.
    Pass "order_type" (buy_limit/sell_limit/buy_stop/sell_stop) for explicit control,
    otherwise LIMIT vs STOP is inferred from entry vs current price."""
    data = request.json
    symbol = data.get("symbol", "XAUUSD")
    side = data.get("side", "buy")   # used only when order_type not given
    volume = float(data.get("volume", 0.01))
    entry = float(data["price"])     # requested entry price
    sl = data.get("sl", 0.0)
    tp = data.get("tp", 0.0)
    explicit = data.get("order_type")  # optional

    if explicit and explicit in _PENDING_TYPES:
        order_type = _PENDING_TYPES[explicit]
    else:
        tick = mt5.symbol_info_tick(symbol)
        if side == "buy":
            order_type = mt5.ORDER_TYPE_BUY_LIMIT if entry < tick.ask else mt5.ORDER_TYPE_BUY_STOP
        else:
            order_type = mt5.ORDER_TYPE_SELL_LIMIT if entry > tick.bid else mt5.ORDER_TYPE_SELL_STOP

    result = mt5.order_send({
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": entry,
        "sl": sl,
        "tp": tp,
        "deviation": 10,
        "magic": 12345,
        "comment": "xauusd-bot-pending",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    })
    return jsonify({
        "retcode": result.retcode,
        "order": result.order,
        "price": result.price,
        "comment": result.comment,
    })


@app.route("/pending", methods=["GET"])
def get_pending():
    symbol = request.args.get("symbol", "XAUUSD")
    orders = mt5.orders_get(symbol=symbol)
    if orders is None:
        return jsonify([])
    return jsonify([o._asdict() for o in orders])


@app.route("/cancel", methods=["POST"])
def cancel_pending():
    data = request.json
    ticket = int(data["ticket"])
    result = mt5.order_send({
        "action": mt5.TRADE_ACTION_REMOVE,
        "order": ticket,
    })
    return jsonify({"retcode": result.retcode, "comment": result.comment})


@app.route("/positions")
def get_positions():
    symbol = request.args.get("symbol", "XAUUSD")
    positions = mt5.positions_get(symbol=symbol)
    if positions is None:
        return jsonify([])
    return jsonify([p._asdict() for p in positions])


@app.route("/close", methods=["POST"])
def close_position():
    data = request.json
    ticket = int(data["ticket"])
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return jsonify({"error": "position not found"}), 404

    pos = positions[0]
    side = "sell" if pos.type == mt5.ORDER_TYPE_BUY else "buy"
    tick = mt5.symbol_info_tick(pos.symbol)
    price = tick.bid if side == "sell" else tick.ask

    result = mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pos.symbol,
        "volume": pos.volume,
        "type": mt5.ORDER_TYPE_SELL if side == "sell" else mt5.ORDER_TYPE_BUY,
        "position": ticket,
        "price": price,
        "deviation": 10,
        "magic": 12345,
        "comment": "close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    })
    return jsonify({"retcode": result.retcode, "comment": result.comment})


@app.route("/account")
def get_account():
    info = mt5.account_info()
    if info is None:
        return jsonify({"error": mt5.last_error()}), 500
    return jsonify({
        "balance":    info.balance,
        "equity":     info.equity,
        "profit":     info.profit,
        "margin":     info.margin,
        "free_margin": info.margin_free,
        "currency":   info.currency,
        "leverage":   info.leverage,
        "server":     info.server,
        "name":       info.name,
    })


@app.route("/history")
def get_history():
    """Closed deals from the last N days."""
    days = int(request.args.get("days", 7))
    from datetime import datetime, timedelta
    date_from = datetime.now() - timedelta(days=days)
    deals = mt5.history_deals_get(date_from, datetime.now())
    if deals is None:
        return jsonify([])
    return jsonify([d._asdict() for d in deals])


if __name__ == "__main__":
    # Connect eagerly so problems show up in the console immediately, but do
    # NOT crash if MT5 isn't ready yet — before_request will keep retrying.
    if not _connect():
        log.warning("Starting anyway — will retry connecting on each request. "
                    "Make sure the MT5 terminal is running and logged in.")
    app.run(host="0.0.0.0", port=5000, debug=False)
