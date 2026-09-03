@echo off
REM Sets RDO Lobby Manager up from a clone of the source, in a .venv beside
REM this file.
REM
REM Most people should use the installer instead - RDO-Lobby-Manager-Setup-
REM x.y.z.exe on the Releases page - which needs no Python at all. This is
REM for running from source.
REM
REM All this does is start the real installer, which draws its own window
REM and hides this console a moment later. A .bat rather than the .ps1
REM directly, because Windows opens a double-clicked .ps1 in Notepad and
REM its execution policy blocks a downloaded one. -ExecutionPolicy Bypass
REM applies to this one file only; it changes nothing about the machine's
REM own policy.
REM
REM The flag file is how this window knows whether the installer's own
REM window ever appeared. If it did, every message has already been shown
REM there, and pausing here would hang a console nobody can see. If it did
REM not, this console is still on screen and is the only place left to say
REM so.
setlocal
title Installing RDO Lobby Manager
cd /d "%~dp0"

set "FLAG=%TEMP%\rdo-lm-setup-window.flag"
if exist "%FLAG%" del /q "%FLAG%" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\install-from-source.ps1" %*
set "RC=%ERRORLEVEL%"

if exist "%FLAG%" (
    del /q "%FLAG%" >nul 2>&1
    endlocal & exit /b %RC%
)

echo.
echo   Setup could not start.
echo.
echo   Windows PowerShell runs the installer, and it did not get that far
echo   ^(exit code %RC%^). Any message above says why. If there is none,
echo   PowerShell is missing or blocked on this PC.
echo.
pause
endlocal & exit /b 1
