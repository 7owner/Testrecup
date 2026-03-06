@echo off
setlocal
cd /d "%~dp0\.."

REM Exemple: scripts\tv-switch-adb.cmd 192.168.43.50:5555
set TVHOST=%~1

powershell -ExecutionPolicy Bypass -File ".\scripts\tv-switch-adb.ps1" -TvHost "%TVHOST%" -IntervalSeconds 40 -StartOnWeb

endlocal
