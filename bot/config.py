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

# EMA filter
EMA_PERIOD = int(os.getenv("EMA_PERIOD", "50"))

# Risk management — distance in PRICE units (USD for XAUUSD). 0 = disabled.
# Example: SL_DISTANCE=3.0 means stop 3 dollars away.
SL_DISTANCE = float(os.getenv("SL_DISTANCE", "3.0"))

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

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# PostgreSQL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://botuser:botpass@db:5432/tradingbot"
)
