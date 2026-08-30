@echo off
cd /d "%~dp0"
title Start-Protokoll Bianca Lisa
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-protokoll.ps1"
echo.
echo Waechter beendet.
pause
