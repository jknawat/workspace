@echo off
REM ===================================================================
REM  Start the bot automatically when you log in.  Double-click once.
REM
REM  Run it again to remove the schedule.  It only tells Windows to run
REM  run.bat at logon -- run.bat still does everything else, including
REM  starting MetaTrader 5 and restarting the bot if it crashes.
REM ===================================================================
cd /d "%~dp0"
title tbot - autostart

set "TASK=tbot"

schtasks /query /tn "%TASK%" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo   tbot is currently set to start when you log in.
    echo.
    choice /c YN /m "   Remove that"
    if errorlevel 2 goto :end
    schtasks /delete /tn "%TASK%" /f >nul
    echo   Removed.  You will need to start it yourself with run.bat.
    goto :end
)

echo.
echo   This will start tbot automatically when you log into Windows.
echo.
echo   At logon, not at boot: MetaTrader 5 needs a desktop to draw on,
echo   so the machine has to be logged in for either to run. If you want
echo   it trading while you are away, leave the PC on and logged in --
echo   or run it on a VPS, which is what that is for.
echo.
choice /c YN /m "   Set it up"
if errorlevel 2 goto :end

REM /rl limited, not highest: the bot needs no administrator rights, and
REM a trading process should not have them.
schtasks /create /tn "%TASK%" /tr "\"%~dp0run.bat\"" /sc onlogon /rl limited /f >nul
if errorlevel 1 (
    echo.
    echo   Could not create the scheduled task.  Try running this file as
    echo   administrator, or set it up by hand in Task Scheduler.
    goto :end
)

echo.
echo   Done.  tbot will start when you log in.
echo.
echo   Note: run.bat clears any waiting stop signal when it starts, so
echo   logging in WILL restart the bot even if you stopped it deliberately.
echo   To keep it off, run this file again and remove the schedule.
echo.
echo   Run this file again to undo it.

:end
echo.
pause
