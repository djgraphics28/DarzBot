"""Trade logging to PostgreSQL."""
import logging
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import RealDictCursor
from bot.config import DATABASE_URL

logger = logging.getLogger(__name__)


def _connect():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db() -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id          SERIAL PRIMARY KEY,
                ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                symbol      TEXT NOT NULL,
                side        TEXT NOT NULL,
                volume      NUMERIC NOT NULL,
                price       NUMERIC,
                retcode     INT,
                order_id    BIGINT,
                comment     TEXT,
                closed_at   TIMESTAMPTZ,
                final_profit NUMERIC
            )
        """)
        # Shared control flags — dashboard writes, bot reads
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cur.execute("""
            INSERT INTO bot_state (key, value) VALUES ('auto_trade', 'off')
            ON CONFLICT (key) DO NOTHING
        """)
        # Migrate older tables that predate these columns
        cur.execute("ALTER TABLE trades ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ")
        cur.execute("ALTER TABLE trades ADD COLUMN IF NOT EXISTS final_profit NUMERIC")
        conn.commit()
    logger.info("DB initialised")


def get_state(key: str, default: str = "") -> str:
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT value FROM bot_state WHERE key = %s", (key,))
            row = cur.fetchone()
            return row["value"] if row else default
    except Exception as e:
        logger.error("DB state read failed: %s", e)
        return default


def set_state(key: str, value: str) -> None:
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO bot_state (key, value) VALUES (%s, %s)
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                (key, value),
            )
            conn.commit()
    except Exception as e:
        logger.error("DB state write failed: %s", e)


def is_auto_trade_on() -> bool:
    return get_state("auto_trade", "off") == "on"


def log_trade(symbol: str, side: str, volume: float, price: float,
              retcode: int, order_id: int, comment: str) -> None:
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO trades (ts, symbol, side, volume, price, retcode, order_id, comment)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (datetime.now(timezone.utc), symbol, side, volume,
                 price, retcode, order_id, comment),
            )
            conn.commit()
    except Exception as e:
        logger.error("DB log failed: %s", e)


def log_close(order_id: int, final_profit: float) -> None:
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE trades SET closed_at = %s, final_profit = %s
                   WHERE order_id = %s""",
                (datetime.now(timezone.utc), final_profit, order_id),
            )
            conn.commit()
    except Exception as e:
        logger.error("DB close log failed: %s", e)


def recent_trades(limit: int = 50) -> list:
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM trades ORDER BY ts DESC LIMIT %s", (limit,))
            return cur.fetchall()
    except Exception as e:
        logger.error("DB read failed: %s", e)
        return []
