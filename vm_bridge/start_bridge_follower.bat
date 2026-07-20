@echo off
REM ── Second bridge for the copy-trading FOLLOWER terminal ──
REM Runs on port 5001 and drives the portable MT5 copy, so the follower
REM account can trade independently of the master terminal.
REM
REM 1. Copy your MT5 folder to C:\MT5-Follower and start it once with:
REM       C:\MT5-Follower\terminal64.exe /portable
REM    (log it into the follower account, enable Algo Trading)
REM 2. Adjust MT5_PATH below if you used a different folder.
REM
REM No MT5_LOGIN/PASSWORD here — the dashboard sends each account's
REM credentials per request via X-MT5-* headers.

set BRIDGE_PORT=5001
set MT5_PATH=C:\MT5-Follower\terminal64.exe

echo Starting FOLLOWER bridge on port %BRIDGE_PORT% ...
python flask_mt5.py
pause
