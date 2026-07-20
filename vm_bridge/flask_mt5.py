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

# Credentials can arrive two ways (per-request headers win):
#   1. Request headers  X-MT5-Login / X-MT5-Password / X-MT5-Server — sent by
#      the Laravel dashboard / bot for whichever account is active there. The
#      bridge switches MT5 to that account on the fly, so nothing account-
#      specific has to be configured statically in the VM.
#   2. Environment variables — fallback for callers that send no headers, e.g.
#      (PowerShell): $env:MT5_LOGIN="5052702771"; $env:MT5_PASSWORD="..."; $env:MT5_SERVER="Broker-Demo"
# All optional: with no credentials at all the bridge attaches to the account
# already logged in inside the MT5 terminal. Set MT5_PATH if the terminal is
# installed somewhere non-standard, e.g. C:\Program Files\MetaTrader 5\terminal64.exe
MT5_LOGIN = os.getenv("MT5_LOGIN")
MT5_PASSWORD = os.getenv("MT5_PASSWORD")
MT5_SERVER = os.getenv("MT5_SERVER")
MT5_PATH = os.getenv("MT5_PATH")

_connect_lock = threading.Lock()

# Login/server we last connected with, to detect when a request asks for a
# different account and the terminal must be re-logged-in.
_active = {"login": None, "server": None}


def _request_creds():
    """Credentials for the current request: headers first, env as fallback."""
    login = request.headers.get("X-MT5-Login") or MT5_LOGIN
    password = request.headers.get("X-MT5-Password") or MT5_PASSWORD
    server = request.headers.get("X-MT5-Server") or MT5_SERVER
    return login, password, server


def _connect(login=None, password=None, server=None) -> bool:
    """(Re)initialize the MT5 connection. Returns True when connected."""
    mt5.shutdown()  # drop any dead half-open connection first

    kwargs = {}
    if MT5_PATH:
        kwargs["path"] = MT5_PATH
    if login and password and server:
        kwargs.update(login=int(login), password=password, server=server)

    ok = mt5.initialize(**kwargs)
    if ok:
        info = mt5.account_info()
        _active["login"] = getattr(info, "login", None)
        _active["server"] = getattr(info, "server", None)
        log.info("MT5 connected  login=%s  server=%s",
                 _active["login"] or "?", _active["server"] or "?")
    else:
        _active["login"] = _active["server"] = None
        log.warning("MT5 initialize failed: %s", mt5.last_error())
    return ok


def _is_connected() -> bool:
    """terminal_info() returns None whenever the IPC link is dead."""
    return mt5.terminal_info() is not None


def _needs_switch(login) -> bool:
    """True when the request targets a different account than the one logged in."""
    if not login:
        return False
    try:
        return _active["login"] != int(login)
    except (TypeError, ValueError):
        return False


@app.before_request
def _ensure_mt5():
    """Reconnect on demand so a terminal restart never requires a bridge
    restart, and switch accounts when the request carries different creds."""
    if request.path == "/ping":
        return None
    login, password, server = _request_creds()
    if not _is_connected() or _needs_switch(login):
        with _connect_lock:
            if (not _is_connected() or _needs_switch(login)) \
                    and not _connect(login, password, server):
                return jsonify({"error": ["mt5_disconnected", str(mt5.last_error())]}), 503
    return None


@app.route("/ping")
def ping():
    return jsonify({"status": "ok", "mt5": _is_connected()})


def _select_symbol(symbol: str) -> bool:
    """Make sure the symbol exists and is visible in Market Watch.
    Brokers name instruments differently (XAUUSD vs XAUUSDm vs GOLD) and
    tick/rates calls fail with "Terminal: Not found" until it's selected."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return False
    if not info.visible:
        return mt5.symbol_select(symbol, True)
    return True


@app.route("/symbols")
def list_symbols():
    """Discover this broker's symbol names, e.g. /symbols?search=XAU"""
    search = request.args.get("search", "").upper()
    symbols = mt5.symbols_get() or []
    names = [s.name for s in symbols if search in s.name.upper()]
    return jsonify(names)


@app.route("/rates")
def get_rates():
    symbol = request.args.get("symbol", "XAUUSD")
    tf = int(request.args.get("tf", mt5.TIMEFRAME_M5))
    count = int(request.args.get("count", 200))
    if not _select_symbol(symbol):
        return jsonify({"error": ["unknown_symbol", symbol]}), 404
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None:
        return jsonify({"error": mt5.last_error()}), 500
    return jsonify(rates.tolist())


@app.route("/tick")
def get_tick():
    symbol = request.args.get("symbol", "XAUUSD")
    if not _select_symbol(symbol):
        return jsonify({"error": ["unknown_symbol", symbol]}), 404
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

    if not _select_symbol(symbol):
        return jsonify({"error": ["unknown_symbol", symbol]}), 404
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

    if not _select_symbol(symbol):
        return jsonify({"error": ["unknown_symbol", symbol]}), 404
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
    if not _connect(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER):
        log.warning("Starting anyway — will retry connecting on each request. "
                    "Make sure the MT5 terminal is running and logged in.")
    # BRIDGE_PORT lets a second bridge (for a copy-trading follower terminal)
    # run alongside the first, e.g. 5001. Pair it with MT5_PATH pointing at
    # that terminal's portable installation.
    app.run(host="0.0.0.0", port=int(os.getenv("BRIDGE_PORT", "5000")), debug=False)
