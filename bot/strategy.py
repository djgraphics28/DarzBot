"""Signal generation — Stochastic crossover filtered by EMA50."""
import pandas as pd
from bot.config import STOCH_K, STOCH_D, OVERSOLD, OVERBOUGHT, EMA_PERIOD


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    low_min = df["low"].rolling(STOCH_K).min()
    high_max = df["high"].rolling(STOCH_K).max()
    df["%K"] = 100 * (df["close"] - low_min) / (high_max - low_min)
    df["%D"] = df["%K"].rolling(STOCH_D).mean()
    df["ema"] = df["close"].ewm(span=EMA_PERIOD).mean()
    return df


def get_signal(df: pd.DataFrame) -> str | None:
    """Return 'buy', 'sell', or None based on the last two candles."""
    df = add_indicators(df)
    if len(df) < EMA_PERIOD + STOCH_K:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # Stochastic %K crossed up through oversold AND price above EMA
    buy = (
        prev["%K"] < OVERSOLD
        and last["%K"] >= OVERSOLD
        and last["close"] > last["ema"]
    )
    # Stochastic %K crossed down through overbought AND price below EMA
    sell = (
        prev["%K"] > OVERBOUGHT
        and last["%K"] <= OVERBOUGHT
        and last["close"] < last["ema"]
    )

    if buy:
        return "buy"
    if sell:
        return "sell"
    return None
