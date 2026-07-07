import os
from dotenv import load_dotenv

load_dotenv()

VM_IP = os.getenv("VM_IP", "192.168.64.2")
VM_PORT = os.getenv("VM_PORT", "5000")
MT5_BASE_URL = f"http://{VM_IP}:{VM_PORT}"

SYMBOL = os.getenv("SYMBOL", "XAUUSD")
TIMEFRAME = int(os.getenv("TIMEFRAME", "5"))   # minutes (M5)
VOLUME = float(os.getenv("VOLUME", "0.01"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))     # seconds — signal check (M5 candle)
MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "5")) # seconds — position P&L check

# Max open positions at once (0 = unlimited)
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "1"))

# Stochastic settings
STOCH_K = int(os.getenv("STOCH_K", "14"))
STOCH_D = int(os.getenv("STOCH_D", "3"))
OVERSOLD = float(os.getenv("OVERSOLD", "20"))
OVERBOUGHT = float(os.getenv("OVERBOUGHT", "80"))

# Trend filter — fast/slow EMA. Trend = up when fast > slow (and slow rising).
EMA_FAST = int(os.getenv("EMA_FAST", "21"))
EMA_SLOW = int(os.getenv("EMA_SLOW", "50"))
EMA_PERIOD = EMA_SLOW  # kept for the chart / backward compatibility

# Require the slow EMA to be sloping in the trade direction (confirms trend)
REQUIRE_SLOPE = os.getenv("REQUIRE_SLOPE", "true").lower() == "true"

# Trend-strength filter: EMA gap must be >= MIN_TREND_ATR × ATR to trade
# (rejects flat/ranging markets). Higher = stricter, fewer but cleaner trades.
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "14"))
MIN_TREND_ATR = float(os.getenv("MIN_TREND_ATR", "0.15"))

# Momentum filter: RSI must agree with the trade direction
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
USE_RSI = os.getenv("USE_RSI", "true").lower() == "true"

# ── Entry timing (scalp mode) ────────────────────────────────────────────────
# Enter on PULLBACKS instead of anywhere: buy dips in uptrends, sell rallies in
# downtrends. Uses the Stochastic to find a good price.
PULLBACK_ENTRY = os.getenv("PULLBACK_ENTRY", "false").lower() == "true"
SCALP_BUY_BELOW = float(os.getenv("SCALP_BUY_BELOW", "50"))   # buy when %K <= this
SCALP_SELL_ABOVE = float(os.getenv("SCALP_SELL_ABOVE", "50"))  # sell when %K >= this
# Reject entries too far from the fast EMA (chasing an extended move that may revert)
MAX_EXTENSION_ATR = float(os.getenv("MAX_EXTENSION_ATR", "1.5"))

# Risk management — distance in PRICE units (USD for XAUUSD). 0 = disabled.
# Example: SL_DISTANCE=3.0 means stop 3 dollars away.
SL_DISTANCE = float(os.getenv("SL_DISTANCE", "3.0"))

# ── Scalp mode ──────────────────────────────────────────────────────────────
# When ON: auto-trade enters WITH the trend, no SL/TP, and closes each position
# as soon as it reaches PROFIT_TARGET dollars, then opens a fresh trend trade.
SCALP_MODE = os.getenv("SCALP_MODE", "true").lower() == "true"
PROFIT_TARGET = float(os.getenv("PROFIT_TARGET", "2.0"))  # close at +$ this much

# Safety net (works in any mode): emergency close if a position hits -$MAX_LOSS.
# 0 disables it. Strongly recommended when scalping without a hard SL.
MAX_LOSS = float(os.getenv("MAX_LOSS", "10.0"))

# After a losing close, wait this many seconds before re-entering (avoids
# immediately re-entering into a move that just went against us).
LOSS_COOLDOWN = int(os.getenv("LOSS_COOLDOWN", "30"))

# Multiple take-profit levels (scaling out). Comma-separated distances in USD.
# Each level opens a SEPARATE trade of VOLUME lots sharing the same SL.
#   TP_LEVELS="6"      -> one trade, TP at $6
#   TP_LEVELS="6,12"   -> two trades: one closes at $6, one at $12
#   TP_LEVELS="4,8,12" -> three trades at $4/$8/$12
TP_LEVELS = [
    float(x) for x in os.getenv("TP_LEVELS", "6,12").split(",") if x.strip()
]

# Backwards-compatible single TP (first level), kept for the dashboard default
TP_DISTANCE = TP_LEVELS[0] if TP_LEVELS else 0.0

# ── AI analyst (Anthropic Claude) ────────────────────────────────────────────
# When AI_ENABLED, Claude reads the last hour of candles and must AGREE with the
# technical entry (higher-lows -> buy, lower-highs -> sell) before a trade opens.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_ENABLED = os.getenv("AI_ENABLED", "false").lower() == "true"
AI_MODEL = os.getenv("AI_MODEL", "claude-opus-4-8")
AI_MIN_CONFIDENCE = int(os.getenv("AI_MIN_CONFIDENCE", "60"))  # veto below this

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# PostgreSQL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://botuser:botpass@db:5432/tradingbot"
)
