@echo off
REM ===================================================================
REM  Stop the trading bot cleanly.  Double-click this file.
REM
REM  This asks the bot to finish its current cycle and shut down -- it
REM  does not kill it mid-write, so the journal stays intact.  Once it
REM  has stopped, the journal is saved to GitHub so the other computer
REM  can carry on from it.  Open positions are left alone; close those
REM  yourself or from Telegram.
REM ===================================================================
cd /d "%~dp0"
title tbot - stopping

if not exist "data" mkdir "data"
echo stop requested %DATE% %TIME% > "data\STOP"

echo.
echo   Stop requested. Waiting for the bot to finish its current cycle
echo   (about 15 seconds).
echo.
echo   Any open positions are still open. Close them in MT5 or send
echo   /closeall from Telegram if you want them flat.
echo.

set /a TRIES=0
:waitloop
timeout /t 3 >nul
tasklist /fi "imagename eq python.exe" 2>nul | find /i "python.exe" >nul
if errorlevel 1 goto :stopped
set /a TRIES+=1
if %TRIES% LSS 20 goto :waitloop

echo   The bot is still running after a minute. Not saving the journal --
echo   copying it while it is being written is how a database gets
echo   corrupted. Close the tbot window, then run this again.
echo.
pause
exit /b 1

:stopped
echo   Stopped.
echo.

REM -------------------------------------------------------------------
REM  Save the journal so the other computer starts from this history.
REM  Only once the bot has actually exited: sqlite writes in the
REM  background, and a half-written file is worse than an old one.
REM -------------------------------------------------------------------
where git >nul 2>&1
if errorlevel 1 (
    echo   git not found - journal saved locally only.
    goto :done
)

git add "data/journal.sqlite" >nul 2>&1
git diff --cached --quiet "data/journal.sqlite"
if not errorlevel 1 (
    echo   Nothing new in the journal since last time.
    goto :done
)

echo   Saving the journal to GitHub...
git commit -q -m "Journal from %COMPUTERNAME%, %DATE% %TIME%" >nul 2>&1
git push --quiet 2>nul
if errorlevel 1 (
    echo.
    echo   Saved on this PC, but could not reach GitHub.
    echo   It will go up next time you run stop.bat with a connection.
    echo   Do NOT start the bot on the other computer until it has.
) else (
    echo   Done. The other computer will pick this up when you run it.
)

:done
echo.
timeout /t 5 >nul
