@echo off
setlocal

set "WIN_ROOT=%~dp0"
set "WSL_ROOT=/mnt/c/Users/takot/Documents/projet_AIX/saas_test_comptage"

wsl bash -lc "cd \"%WSL_ROOT%\" && ./run-train-symbols.sh --dataset datasets/plans --output models/symbol_classifier.pt --run-dir training_runs/run_001 --epochs 12"

if errorlevel 1 (
  echo.
  echo Echec de l'entrainement.
  pause
  exit /b 1
)

echo.
echo Entrainement termine.
pause
exit /b 0
