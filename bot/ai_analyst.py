"""AI market-structure analyst — uses Anthropic Claude to read the last hour of
candles, judge higher-lows / lower-highs (trend structure), and return a
buy / sell / hold decision that gates the bot's auto-trade entries.
"""
import logging

import anthropic
from pydantic import BaseModel

from bot import broker
from bot.config import ANTHROPIC_API_KEY, AI_MODEL, SYMBOL

logger = logging.getLogger(__name__)

# Reuse one client. If no key is configured, analysis is skipped (returns None).
_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


class AIDecision(BaseModel):
    """Validated decision returned by Claude."""
    signal: str        # "buy" | "sell" | "hold"
    confidence: int    # 0-100
    structure: str     # e.g. "higher_lows", "lower_highs", "ranging"
    reason: str        # one sentence, grounded in the highs/lows


def _candle_table(df) -> str:
    rows = []
    for _, r in df.iterrows():
        rows.append(
            f"{r['time']:%H:%M}  O={r['open']:.2f} H={r['high']:.2f} "
            f"L={r['low']:.2f} C={r['close']:.2f}"
        )
    return "\n".join(rows)


def analyze(symbol: str = SYMBOL) -> AIDecision | None:
    """Ask Claude to read the last hour of 5-minute candles and decide.
    Returns an AIDecision, or None if AI is disabled or the call fails."""
    if _client is None:
        return None
    try:
        # Last 12 M5 candles == the past hour, oldest first
        df = broker.get_rates(symbol=symbol, tf=5, count=12)
        tick = broker.get_tick(symbol)

        prompt = f"""You are a market-structure analyst for {symbol} on a scalping bot.

Here are the last 12 five-minute candles (the past hour), oldest first:

{_candle_table(df)}

Current price: bid={tick['bid']:.2f}  ask={tick['ask']:.2f}

Read the market structure of this hour by comparing successive swing highs and swing lows:
- Higher highs AND higher lows -> uptrend -> favor BUY
- Lower highs AND lower lows -> downtrend -> favor SELL
- Mixed / flat (no clear progression of highs and lows) -> ranging -> HOLD

Decide whether to buy, sell, or hold right now. Set "structure" to one of
higher_lows, lower_highs, or ranging, give a confidence from 0-100, and a
one-sentence reason that references the specific highs and lows you used."""

        resp = _client.messages.parse(
            model=AI_MODEL,
            max_tokens=2048,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
            output_format=AIDecision,
        )
        return resp.parsed_output
    except Exception as e:
        logger.warning("AI analysis failed: %s", e)
        return None
