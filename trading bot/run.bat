@echo off
REM ===================================================================
REM  Start the trading bot.  Double-click this file.
REM
REM  It will bring the shared trade journal up to date from GitHub,
REM  start MetaTrader 5 if it is not already running, then start the
REM  bot.  To stop:  double-click stop.bat
REM ===================================================================
cd /d "%~dp0"
title tbot - running

set "MT5=C:\Program Files\MetaTrader 5\terminal64.exe"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   Python environment missing.  Run this once:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -e ".[dev]"
    echo.
    pause
    exit /b 1
)

REM -------------------------------------------------------------------
REM  Shared journal: take whatever the other computer recorded before
REM  adding to it.  The journal is the only copy of the trade history,
REM  and two machines writing their own version of it leaves two half
REM  records that cannot be put back together.
REM -------------------------------------------------------------------
where git >nul 2>&1
if errorlevel 1 (
    echo   git not found - running with the local journal only.
    goto :aftersync
)

echo   Checking GitHub for newer history...
git fetch origin --quiet 2>nul
if errorlevel 1 (
    echo   Could not reach GitHub - running with the local journal.
    goto :aftersync
)

set BEHIND=0
set AHEAD=0
for /f %%i in ('git rev-list --count HEAD..origin/main 2^>nul') do set BEHIND=%%i
for /f %%i in ('git rev-list --count origin/main..HEAD 2^>nul') do set AHEAD=%%i

if %BEHIND% GTR 0 if %AHEAD% GTR 0 (
    echo.
    echo   ==================================================================
    echo    STOP - both computers have history the other does not have.
    echo.
    echo    That means the bot has been run in two places. Trading now would
    echo    add to one of two records that can no longer be merged, and the
    echo    one you do not pick is lost.
    echo.
    echo    Sort this out before trading. Ask Claude, or keep the journal
    echo    from the machine that actually placed the trades.
    echo   ==================================================================
    echo.
    pause
    exit /b 1
)

if %BEHIND% GTR 0 (
    echo   Taking %BEHIND% newer change^(s^) from the other computer...
    git merge --ff-only origin/main --quiet
    if errorlevel 1 (
        echo   Could not update cleanly. Fix this before trading.
        pause
        exit /b 1
    )
)
:aftersync

REM Start MT5 only if it is not already up -- never restart a terminal the
REM user is looking at, and never while it may hold open positions.
tasklist /fi "imagename eq terminal64.exe" 2>nul | find /i "terminal64.exe" >nul
if errorlevel 1 (
    if exist "%MT5%" (
        echo   Starting MetaTrader 5 on the pinned account...
        start "" "%MT5%" /config:"%~dp0mt5\start_gold.ini"
        echo   Waiting 60s for it to connect...
        timeout /t 60 >nul
    ) else (
        echo   MetaTrader 5 not found at:
        echo     %MT5%
        echo   Open it yourself, then run this again.
        pause
        exit /b 1
    )
) else (
    echo   MetaTrader 5 is already running - leaving it alone.
    echo   If the bot cannot find its symbol, check the account is the
    echo   one named in mt5\start_gold.ini.
)

REM Clear any leftover stop signal, or the bot would quit immediately.
if exist "data\STOP" del /q "data\STOP"

echo.
echo   Starting tbot.  Leave this window open.
echo   Dashboard:  http://127.0.0.1:8787
echo   To stop:    double-click stop.bat
echo.

".venv\Scripts\python.exe" -m tbot.cli paper -c "config\bot.toml"

echo.
echo   tbot has stopped.
echo   Run stop.bat to save the journal to GitHub if you have not already.
pause
