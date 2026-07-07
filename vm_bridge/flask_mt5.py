"""Flask bridge — runs inside the Windows VM alongside MT5."""
import os
from flask import Flask, jsonify, request
import MetaTrader5 as mt5

app = Flask(__name__)

# Credentials come from environment variables — never hardcode them here.
# Set them in the VM before running, e.g. (PowerShell):
#   $env:MT5_LOGIN="5052702771"; $env:MT5_PASSWORD="..."; $env:MT5_SERVER="Broker-Demo"
MT5_LOGIN = os.getenv("MT5_LOGIN")
MT5_PASSWORD = os.getenv("MT5_PASSWORD")
MT5_SERVER = os.getenv("MT5_SERVER")

if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
    ok = mt5.initialize(login=int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER)
else:
    # Falls back to the account already logged in inside the MT5 terminal
    ok = mt5.initialize()

if not ok:
    raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")


@app.route("/ping")
def ping():
    return jsonify({"status": "ok"})


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


@app.route("/pending", methods=["POST"])
def place_pending():
    """Place a pending order at a specific entry price.
    Picks LIMIT vs STOP automatically based on entry vs current price."""
    data = request.json
    symbol = data.get("symbol", "XAUUSD")
    side = data["side"]           # "buy" | "sell"
    volume = float(data.get("volume", 0.01))
    entry = float(data["price"])  # requested entry price
    sl = data.get("sl", 0.0)
    tp = data.get("tp", 0.0)

    tick = mt5.symbol_info_tick(symbol)
    if side == "buy":
        # below market -> BUY LIMIT, above market -> BUY STOP
        order_type = mt5.ORDER_TYPE_BUY_LIMIT if entry < tick.ask else mt5.ORDER_TYPE_BUY_STOP
    else:
        # above market -> SELL LIMIT, below market -> SELL STOP
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
    app.run(host="0.0.0.0", port=5000, debug=False)
