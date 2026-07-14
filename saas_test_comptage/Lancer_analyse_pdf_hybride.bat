@echo off
setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
set "DEFAULT_PYTHON=C:\Users\takot\AppData\Local\Programs\Python\Python312\python.exe"

if exist "%DEFAULT_PYTHON%" (
  set "PYTHON_EXE=%DEFAULT_PYTHON%"
) else (
  set "PYTHON_EXE=py -3"
)

set "INPUT_PATH=%~1"
if "%INPUT_PATH%"=="" (
  set /p "INPUT_PATH=Chemin du PDF ou du dossier a analyser : "
)

if "%INPUT_PATH%"=="" (
  echo Aucun chemin fourni.
  pause
  exit /b 1
)

if not exist "%INPUT_PATH%" (
  echo Chemin introuvable : "%INPUT_PATH%"
  pause
  exit /b 1
)

for %%I in ("%INPUT_PATH%") do set "INPUT_ATTR=%%~aI"
if /I "!INPUT_ATTR:~0,1!"=="d" goto folder_mode
goto file_mode

:file_mode
for %%I in ("%INPUT_PATH%") do set "BASE_NAME=%%~nI"
set "OUTPUT_DIR=%~2"
if "%OUTPUT_DIR%"=="" set "OUTPUT_DIR=hybrid_runs\!BASE_NAME!"

call :run_one "%INPUT_PATH%" "%OUTPUT_DIR%"
if errorlevel 1 goto fail
goto success

:folder_mode
for %%I in ("%INPUT_PATH%") do set "FOLDER_NAME=%%~nI"
set "OUTPUT_ROOT=%~2"
if "%OUTPUT_ROOT%"=="" set "OUTPUT_ROOT=hybrid_runs\!FOLDER_NAME!"

set "FOUND=0"
for %%F in ("%INPUT_PATH%\*.pdf") do (
  if exist "%%~fF" (
    set "FOUND=1"
    call :run_one "%%~fF" "!OUTPUT_ROOT!\%%~nF"
    if errorlevel 1 goto fail
  )
)

if "!FOUND!"=="0" (
  echo Aucun PDF trouve dans le dossier : "%INPUT_PATH%"
  pause
  exit /b 1
)
goto success

:run_one
set "ONE_PDF=%~1"
set "ONE_OUT=%~2"

echo.
echo Analyse hybride de :
echo   !ONE_PDF!
echo Sortie :
echo   !ONE_OUT!
echo.

if "%PYTHON_EXE%"=="py -3" (
  py -3 "%ROOT%hybrid_pdf_counter.py" --pdf "!ONE_PDF!" --output "!ONE_OUT!"
) else (
  "%PYTHON_EXE%" "%ROOT%hybrid_pdf_counter.py" --pdf "!ONE_PDF!" --output "!ONE_OUT!"
)

exit /b %errorlevel%

:fail
echo.
echo Echec de l'analyse hybride.
pause
exit /b 1

:success
echo.
echo Analyse terminee.
echo Ouvrir ensuite le dossier hybrid_runs correspondant.
pause
exit /b 0
