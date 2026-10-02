@echo off
REM ===================================================================
REM  Start the trading bot.  Double-click this file.
REM
REM  It will start MetaTrader 5 for you if it is not already running,
REM  pinned to the right account and with the structure exporter on the
REM  gold chart.  To stop:  double-click stop.bat
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
pause
