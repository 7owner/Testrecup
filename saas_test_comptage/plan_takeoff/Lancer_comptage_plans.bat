@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creation de l'environnement Python...
  py -3.12 -m venv .venv || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --quiet pymupdf
)

echo Comptage des plans (PLANS_COMPLETS_NEW)...
".venv\Scripts\python.exe" takeoff.py --root "..\PLANS_COMPLETS_NEW" --out rapport
if errorlevel 1 (
  echo.
  echo Des erreurs sont survenues, voir ci-dessus.
  pause
  exit /b 1
)

start "" "rapport\index.html"
endlocal
