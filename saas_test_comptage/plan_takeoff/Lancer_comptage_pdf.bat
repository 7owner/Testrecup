@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creation de l'environnement Python...
  py -3.12 -m venv .venv || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --quiet pymupdf
)

rem Glisser-deposer un PDF ou un dossier sur ce .bat, sinon utilise PDF_A_COMPTER\
set "CIBLE=%~1"
if "%CIBLE%"=="" (
  if not exist "PDF_A_COMPTER" mkdir "PDF_A_COMPTER"
  set "CIBLE=PDF_A_COMPTER"
  echo Aucun fichier depose : traitement du dossier PDF_A_COMPTER\
)

echo Comptage des objets de legende dans : %CIBLE%
".venv\Scripts\python.exe" takeoff.py --pdf "%CIBLE%" --out rapport_pdf
if errorlevel 1 (
  echo.
  echo Des erreurs sont survenues, voir ci-dessus.
  pause
  exit /b 1
)

start "" "rapport_pdf\index.html"
endlocal
