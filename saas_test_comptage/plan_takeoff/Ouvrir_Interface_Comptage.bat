@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creation de l'environnement Python...
  py -3.12 -m venv .venv || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --quiet pymupdf
)

echo Demarrage de l'interface de comptage...
echo Le navigateur va s'ouvrir sur http://localhost:8765
echo Ferme cette fenetre pour arreter.
".venv\Scripts\python.exe" serve.py
endlocal
