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
echo Recalcul des priors a partir des feedbacks...
echo.

if "%PYTHON_EXE%"=="py -3" (
  py -3 "%ROOT%build_feedback_priors.py"
) else (
  "%PYTHON_EXE%" "%ROOT%build_feedback_priors.py"
)

echo.
echo Termine.
pause
exit /b 0
