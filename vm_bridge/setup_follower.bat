@echo off
setlocal
REM ════════════════════════════════════════════════════════════════════
REM  ONE-SHOT follower setup: finds MT5, copies it to C:\MT5-Follower,
REM  starts the portable terminal, then runs the follower bridge on 5001.
REM  Put this file NEXT TO flask_mt5.py in the VM and double-click it.
REM  Safe to re-run: skips the copy if it already exists.
REM ════════════════════════════════════════════════════════════════════

set "FOLLOWER_DIR=C:\MT5-Follower"

if exist "%FOLLOWER_DIR%\terminal64.exe" (
    echo [1/4] Follower copy already exists at %FOLLOWER_DIR% - skipping copy.
    goto launch
)

echo [1/4] Locating your MT5 installation...
set "SRC="
for /f "delims=" %%i in ('where /r "C:\Program Files" terminal64.exe 2^>nul') do (
    set "SRC=%%~dpi"
    goto found
)
for /f "delims=" %%i in ('where /r "C:\Program Files (x86)" terminal64.exe 2^>nul') do (
    set "SRC=%%~dpi"
    goto found
)
echo ERROR: terminal64.exe not found under Program Files.
echo Right-click your MT5 shortcut, "Open file location", and tell Claude the path.
pause
exit /b 1

:found
echo       Found: %SRC%
echo [2/4] Copying MT5 to %FOLLOWER_DIR% (takes a minute)...
robocopy "%SRC%." "%FOLLOWER_DIR%" /E /NFL /NDL /NJH /NJS >nul
if not exist "%FOLLOWER_DIR%\terminal64.exe" (
    echo ERROR: copy failed - terminal64.exe still missing in %FOLLOWER_DIR%.
    pause
    exit /b 1
)

:launch
echo [3/4] Starting the follower terminal in portable mode...
start "" "%FOLLOWER_DIR%\terminal64.exe" /portable

echo.
echo  ─────────────────────────────────────────────────────────────
echo   In the MT5 window that just opened:
echo     1. File ^> Login to Trade Account
echo        Login:  641992   Server: ACCapitalMarket-Real
echo     2. Click the "Algo Trading" toolbar button so it is GREEN.
echo   Leave that terminal window OPEN.
echo  ─────────────────────────────────────────────────────────────
echo.
pause

echo [4/4] Starting the follower bridge on port 5001...
set "BRIDGE_PORT=5001"
set "MT5_PATH=%FOLLOWER_DIR%\terminal64.exe"
python flask_mt5.py
pause
