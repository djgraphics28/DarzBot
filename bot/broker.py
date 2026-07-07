"""Thin wrapper around the Flask MT5 bridge."""
import requests
import pandas as pd
from bot.config import MT5_BASE_URL, SYMBOL, TIMEFRAME, VOLUME


def _url(path: str) -> str:
    return f"{MT5_BASE_URL}{path}"


def ping() -> bool:
    """Bridge is reachable if it answers on /account (works on all bridge versions).
    Any HTTP response means the server is up; only a connection error means down."""
    try:
        r = requests.get(_url("/account"), timeout=5)
        return r.status_code == 200
    except requests.RequestException:
        return False


# Field order of MT5's copy_rates_from_pos structured array.
# The bridge returns rates.tolist(), which yields positional tuples (no names).
_RATE_COLUMNS = ["time", "open", "high", "low", "close",
                 "tick_volume", "spread", "real_volume"]


def get_rates(symbol: str = SYMBOL, tf: int = TIMEFRAME, count: int = 200) -> pd.DataFrame:
    r = requests.get(_url("/rates"), params={"symbol": symbol, "tf": tf, "count": count}, timeout=10)
    r.raise_for_status()
    rows = r.json()
    df = pd.DataFrame(rows, columns=_RATE_COLUMNS[:len(rows[0])] if rows else _RATE_COLUMNS)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def get_tick(symbol: str = SYMBOL) -> dict:
    r = requests.get(_url("/tick"), params={"symbol": symbol}, timeout=5)
    r.raise_for_status()
    return r.json()


def compute_sl_tp(side: str, entry: float, sl_distance: float, tp_distance: float):
    """Convert SL/TP distances (in price units) into absolute prices.
    Returns (sl_price, tp_price); 0.0 means 'not set' for that leg."""
    if side == "buy":
        sl = entry - sl_distance if sl_distance > 0 else 0.0
        tp = entry + tp_distance if tp_distance > 0 else 0.0
    else:  # sell
        sl = entry + sl_distance if sl_distance > 0 else 0.0
        tp = entry - tp_distance if tp_distance > 0 else 0.0
    return round(sl, 2), round(tp, 2)


def place_order(side: str, symbol: str = SYMBOL, volume: float = VOLUME,
                sl: float = 0.0, tp: float = 0.0) -> dict:
    payload = {"symbol": symbol, "side": side, "volume": volume, "sl": sl, "tp": tp}
    r = requests.post(_url("/order"), json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


def place_pending(side: str, entry: float, symbol: str = SYMBOL,
                  volume: float = VOLUME, sl: float = 0.0, tp: float = 0.0) -> dict:
    payload = {"symbol": symbol, "side": side, "volume": volume,
               "price": entry, "sl": sl, "tp": tp}
    r = requests.post(_url("/pending"), json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


def get_pending(symbol: str = SYMBOL) -> list:
    r = requests.get(_url("/pending"), params={"symbol": symbol}, timeout=5)
    r.raise_for_status()
    return r.json()


def cancel_pending(ticket: int) -> dict:
    r = requests.post(_url("/cancel"), json={"ticket": ticket}, timeout=10)
    r.raise_for_status()
    return r.json()


def place_scaled_orders(side: str, entry: float, sl_distance: float,
                        tp_levels: list, symbol: str = SYMBOL,
                        volume: float = VOLUME, pending: bool = False) -> list:
    """Open one trade per TP level (scaling out). All share the same SL.
    If pending=True, places limit/stop orders at `entry`; else market orders.
    Returns a list of (tp_level, result) tuples."""
    results = []
    for tp_dist in tp_levels:
        sl, tp = compute_sl_tp(side, entry, sl_distance, tp_dist)
        if pending:
            res = place_pending(side, entry, symbol=symbol, volume=volume, sl=sl, tp=tp)
        else:
            res = place_order(side, symbol=symbol, volume=volume, sl=sl, tp=tp)
        results.append((tp_dist, res))
    return results


def get_positions(symbol: str = SYMBOL) -> list:
    r = requests.get(_url("/positions"), params={"symbol": symbol}, timeout=5)
    r.raise_for_status()
    return r.json()


def get_account() -> dict:
    r = requests.get(_url("/account"), timeout=5)
    r.raise_for_status()
    return r.json()


def get_history(days: int = 7) -> list:
    r = requests.get(_url("/history"), params={"days": days}, timeout=10)
    r.raise_for_status()
    return r.json()


def close_position(ticket: int) -> dict:
    r = requests.post(_url("/close"), json={"ticket": ticket}, timeout=10)
    r.raise_for_status()
    return r.json()
