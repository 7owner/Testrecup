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
echo Ouverture du labo KMeans...
echo.

netstat -ano | findstr /R /C:":8765 .*LISTENING" >nul
if errorlevel 1 (
  start "Hybrid GUI Server" cmd /k ""%PYTHON_EXE%" "%ROOT%serve_hybrid_gui.py""
  timeout /t 2 >nul
) else (
  echo Serveur deja actif sur le port 8765.
)

start "" "%URL%"

echo GUI lance :
echo   %URL%
echo.
echo Si le navigateur ne s'ouvre pas, colle cette URL manuellement.
pause
exit /b 0
