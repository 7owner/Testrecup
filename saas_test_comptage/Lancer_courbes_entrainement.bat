@echo off
setlocal

set "WIN_ROOT=%~dp0"
set "WSL_ROOT=/mnt/c/Users/takot/Documents/projet_AIX/saas_test_comptage"

wsl bash -lc "cd \"%WSL_ROOT%\" && ./run-plot-metrics.sh --metrics training_runs/run_001/metrics.jsonl --output training_runs/run_001"

if errorlevel 1 (
  echo.
  echo Echec de la generation des courbes.
  pause
  exit /b 1
)

echo.
echo Courbes generees dans training_runs/run_001
pause
exit /b 0
