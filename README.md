# XAUUSD Trading Bot

Python trading bot for XAUUSD on MetaTrader 5, with a Laravel + React web
dashboard.

## Architecture

- **`vm_bridge/flask_mt5.py`** — Flask API running on the Windows VM next to
  the MT5 terminal (do not run in Docker). Endpoints: `/ping /rates /tick
  /order /pending /cancel /positions /close /account /history`.
- **`bot/`** — trading logic (Docker service `bot`). Reads control flags from
  the shared Postgres `bot_state` table.
- **`db/init.sql`** — Postgres schema bootstrap (service `db`).
- **`webapp`** — Laravel 13 + Inertia/React dashboard (lives in the separate
  `darzbot` repo; see the `webapp` service in `docker-compose.yml`). Replaces
  the old Streamlit dashboard.
- **`dashboard/`** — legacy Streamlit dashboard. No longer wired into
  docker-compose; delete this directory once you're happy with the webapp.

## Running

1. Start the Flask bridge inside the Windows VM (with MT5 running):
   `python vm_bridge/flask_mt5.py`
2. `cp .env.example .env` and fill in `VM_IP`/`VM_PORT` (or set
   `MT5_BRIDGE_URL` directly) plus your trading settings.
3. Generate the Laravel app key and put it in `.env`:
   ```bash
   docker compose run --rm --entrypoint php webapp artisan key:generate --show
   # copy the output into .env as APP_KEY=base64:...
   ```
4. Build and start everything:
   ```bash
   docker compose up -d --build
   ```
   The webapp entrypoint runs `php artisan migrate --force` automatically
   (additive-only; it never touches the bot's `trades`/`bot_state` data).
5. First run only — create your dashboard login:
   ```bash
   docker compose exec webapp php artisan tinker --execute="App\Models\User::create(['name' => 'Me', 'email' => 'me@example.com', 'password' => bcrypt('choose-a-password'), 'email_verified_at' => now()]);"
   ```
   (Or open http://localhost:8000/register, then optionally disable
   registration.)
6. Open **http://localhost:8000**, log in, and manage everything from there:
   auto-trade toggle, timeframe, manual orders, MT5 accounts, history.

> **Networking note:** the webapp container talks to the VM bridge directly,
> so the Windows VM's IP must be reachable *from inside Docker containers*
> (bridged/shared VM networking — a host-only adapter that only your Mac can
> reach will not work).

The webapp build context in `docker-compose.yml` points at the darzbot repo
(`../../LARAVEL/darzbot`); adjust the path if you move or vendor the app into
this repo as `./webapp`.
