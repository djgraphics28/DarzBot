"""Trend-following signals.

Direction is set by a fast/slow EMA stack (the trend on the chart), and entries
are timed with a Stochastic pullback in the direction of that trend:

  • Uptrend  (EMA fast > EMA slow, slow rising)  -> BUY when %K crosses up over %D
    while the stochastic is in the lower half (a dip inside the uptrend).
  • Downtrend (EMA fast < EMA slow, slow falling) -> SELL when %K crosses down under
    %D while the stochastic is in the upper half (a bounce inside the downtrend).

This means the bot only trades WITH the trend shown on the chart, and enters on
pullbacks rather than chasing.
"""
import pandas as pd
from bot.config import (
    STOCH_K, STOCH_D, EMA_FAST, EMA_SLOW, REQUIRE_SLOPE,
)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    low_min = df["low"].rolling(STOCH_K).min()
    high_max = df["high"].rolling(STOCH_K).max()
    df["%K"] = 100 * (df["close"] - low_min) / (high_max - low_min)
    df["%D"] = df["%K"].rolling(STOCH_D).mean()
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW).mean()
    df["ema"] = df["ema_slow"]  # chart draws this as the trend line
    return df


def trend_of(last, prev) -> str | None:
    """Return 'up', 'down', or None from the EMA stack (+ optional slope check)."""
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


def get_signal(df: pd.DataFrame) -> str | None:
    """Return 'buy', 'sell', or None for the latest candle."""
    df = add_indicators(df)
    if len(df) < EMA_SLOW + STOCH_K:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    trend = trend_of(last, prev)
    if trend is None:
        return None

    # Stochastic crossover on this candle
    crossed_up = prev["%K"] <= prev["%D"] and last["%K"] > last["%D"]
    crossed_down = prev["%K"] >= prev["%D"] and last["%K"] < last["%D"]

    # Buy pullbacks in an uptrend (cross up from the lower half)
    if trend == "up" and crossed_up and last["%K"] < 50:
        return "buy"
    # Sell pullbacks in a downtrend (cross down from the upper half)
    if trend == "down" and crossed_down and last["%K"] > 50:
        return "sell"
    return None
