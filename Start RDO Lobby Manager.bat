@echo off
setlocal
title RDO Lobby Manager
cd /d "%~dp0"

REM First run, or someone deleted .venv - set things up rather than fail.
if not exist ".venv\Scripts\rdo-lobby-manager.exe" (
    echo.
    echo   Setting up for the first time...
    echo.
    call "%~dp0Install.bat"
    if not exist ".venv\Scripts\rdo-lobby-manager.exe" exit /b 1
)

echo.
echo   Starting RDO Lobby Manager...
echo.

".venv\Scripts\rdo-lobby-manager.exe"
if errorlevel 1 (
    echo.
    echo   The tool stopped unexpectedly. The message above should say why.
    echo.
    pause
)
endlocal
