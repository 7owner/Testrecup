@echo off
setlocal

set "ROOT=%~dp0"
set "DEFAULT_PYTHON=C:\Users\takot\AppData\Local\Programs\Python\Python312\python.exe"
set "URL=http://127.0.0.1:8765/hybrid_viewer/unsupervised.html"

if exist "%DEFAULT_PYTHON%" (
  set "PYTHON_EXE=%DEFAULT_PYTHON%"
) else (
  set "PYTHON_EXE=py -3"
)

echo.
echo Lancement de Detection Par Legende...
echo.

netstat -ano | findstr /R /C:":8765 .*LISTENING" >nul
if errorlevel 1 (
  start "Detection Par Legende Server" cmd /k ""%PYTHON_EXE%" "%ROOT%serve_hybrid_gui.py""
  timeout /t 2 >nul
) else (
  echo Serveur deja actif sur le port 8765.
)

start "" "%URL%"

echo Interface ouverte :
echo   %URL%
echo.
echo Utilise uniquement ce fichier .bat.
pause
exit /b 0
