"""Trend-following signals with volatility + momentum filters.

Layers (a trade must pass ALL of them):

  1. TREND      — fast/slow EMA stack (+ optional slope). Sets the only side we
                  are allowed to trade.
  2. STRENGTH   — the EMA gap must be at least MIN_TREND_ATR × ATR. This rejects
                  flat / ranging markets where trend-following whipsaws.
  3. MOMENTUM   — RSI must agree with the side (RSI > 50 for buys, < 50 for sells).
  4. TIMING     — (signal mode only) a Stochastic %K/%D pullback cross in the
                  trend direction. Scalp mode skips this and enters on 1–3.

This keeps the bot trading WITH a real, moving trend and out of chop.
"""
import pandas as pd
from bot.config import (
    STOCH_K, STOCH_D, EMA_FAST, EMA_SLOW, REQUIRE_SLOPE,
    ATR_PERIOD, MIN_TREND_ATR, RSI_PERIOD, USE_RSI,
    PULLBACK_ENTRY, SCALP_BUY_BELOW, SCALP_SELL_ABOVE, MAX_EXTENSION_ATR,
)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Stochastic
    low_min = df["low"].rolling(STOCH_K).min()
    high_max = df["high"].rolling(STOCH_K).max()
    df["%K"] = 100 * (df["close"] - low_min) / (high_max - low_min)
    df["%D"] = df["%K"].rolling(STOCH_D).mean()

    # EMAs
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW).mean()
    df["ema"] = df["ema_slow"]  # chart trend line

    # ATR (Wilder-style, simple rolling mean of true range)
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(ATR_PERIOD).mean()

    # RSI
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / RSI_PERIOD, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / RSI_PERIOD, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-9)
    df["rsi"] = 100 - 100 / (1 + rs)

    return df


def trend_of(last, prev) -> str | None:
    """'up' / 'down' / None from the EMA stack (+ optional slope)."""
    up = last["ema_fast"] > last["ema_slow"]
    down = last["ema_fast"] < last["ema_slow"]
    if REQUIRE_SLOPE:
        up = up and last["ema_slow"] >= prev["ema_slow"]
        down = down and last["ema_slow"] <= prev["ema_slow"]
    if up:
        return "up"
    if down:
        return "down"
    return None


def trend_strong(last) -> bool:
    """Trend must be wide enough vs volatility to be worth trading."""
    atr = last.get("atr", 0)
    if not atr or pd.isna(atr):
        return False
    gap = abs(last["ema_fast"] - last["ema_slow"])
    return gap >= MIN_TREND_ATR * atr


def momentum_ok(last, side: str) -> bool:
    """RSI must agree with the trade direction."""
    if not USE_RSI:
        return True
    rsi = last.get("rsi", 50)
    if pd.isna(rsi):
        return False
    return rsi > 50 if side == "buy" else rsi < 50


def not_overextended(last) -> bool:
    """Reject entries where price is stretched too far from the fast EMA."""
    atr = last.get("atr", 0)
    if not atr or pd.isna(atr):
        return False
    return abs(last["close"] - last["ema_fast"]) <= MAX_EXTENSION_ATR * atr


def pullback_ok(last, side: str) -> bool:
    """Enter on a pullback: buy dips (low %K) in uptrends, sell rallies
    (high %K) in downtrends — a better price than chasing."""
    if not PULLBACK_ENTRY:
        return True
    k = last["%K"]
    if pd.isna(k):
        return False
    return k <= SCALP_BUY_BELOW if side == "buy" else k >= SCALP_SELL_ABOVE


def scalp_side(df: pd.DataFrame) -> str | None:
    """Trend-follow scalp entry, gated by strength, momentum, pullback timing,
    and an overextension guard. Returns 'buy'/'sell'/None."""
    df = add_indicators(df)
    if len(df) < EMA_SLOW + max(STOCH_K, ATR_PERIOD, RSI_PERIOD):
        return None
    last, prev = df.iloc[-1], df.iloc[-2]
    trend = trend_of(last, prev)
    if trend is None or not trend_strong(last) or not not_overextended(last):
        return None
    side = "buy" if trend == "up" else "sell"
    if momentum_ok(last, side) and pullback_ok(last, side):
        return side
    return None


def get_signal(df: pd.DataFrame) -> str | None:
    """Signal-mode entry: trend + strength + momentum + Stochastic pullback cross."""
    df = add_indicators(df)
    if len(df) < EMA_SLOW + max(STOCH_K, ATR_PERIOD, RSI_PERIOD):
        return None

    last, prev = df.iloc[-1], df.iloc[-2]
    trend = trend_of(last, prev)
    if trend is None or not trend_strong(last):
        return None

    crossed_up = prev["%K"] <= prev["%D"] and last["%K"] > last["%D"]
    crossed_down = prev["%K"] >= prev["%D"] and last["%K"] < last["%D"]

    if trend == "up" and crossed_up and last["%K"] < 50 and momentum_ok(last, "buy"):
        return "buy"
    if trend == "down" and crossed_down and last["%K"] > 50 and momentum_ok(last, "sell"):
        return "sell"
    return None
