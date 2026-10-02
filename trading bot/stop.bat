@echo off
REM ===================================================================
REM  Stop the trading bot cleanly.  Double-click this file.
REM
REM  This asks the bot to finish its current cycle and shut down -- it
REM  does not kill it mid-write, so the journal stays intact.  Open
REM  positions are left alone; close those yourself or from Telegram.
REM ===================================================================
cd /d "%~dp0"
title tbot - stopping

if not exist "data" mkdir "data"
echo stop requested %DATE% %TIME% > "data\STOP"

echo.
echo   Stop requested.  The bot will finish its current cycle and exit
echo   within one poll - about 15 seconds by default.
echo.
echo   Any open positions are still open.  Close them in MT5 or send
echo   /closeall from Telegram if you want them flat.
echo.
timeout /t 5 >nul
