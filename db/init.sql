-- Run automatically by docker-compose on first start
CREATE TABLE IF NOT EXISTS trades (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL,
    volume      NUMERIC NOT NULL,
    price       NUMERIC,
    retcode     INT,
    order_id    BIGINT,
    comment     TEXT
);
