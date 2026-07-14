@echo off
setlocal

set "ROOT=%~dp0"
set "DEFAULT_PYTHON=C:\Users\takot\AppData\Local\Programs\Python\Python312\python.exe"

if exist "%DEFAULT_PYTHON%" (
  set "PYTHON_EXE=%DEFAULT_PYTHON%"
) else (
  set "PYTHON_EXE=py -3"
)

echo.
echo Rendu de tous les PDF du dossier exemples...
echo.

if "%PYTHON_EXE%"=="py -3" (
  py -3 "%ROOT%batch_render_examples.py" --input-dir "%ROOT%exemples" --output-dir "%ROOT%prepared_data\rendered_examples" --dpi 180
) else (
  "%PYTHON_EXE%" "%ROOT%batch_render_examples.py" --input-dir "%ROOT%exemples" --output-dir "%ROOT%prepared_data\rendered_examples" --dpi 180
)

if errorlevel 1 (
  echo.
  echo Echec du rendu des PDF.
  pause
  exit /b 1
)

echo.
echo Rendu termine.
echo Manifeste :
echo   prepared_data\rendered_examples\render_manifest.json
pause
exit /b 0
