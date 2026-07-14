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
echo Generation des pseudo-labels depuis les vrais plans...
echo.

if "%PYTHON_EXE%"=="py -3" (
  py -3 "%ROOT%generate_pseudolabel_dataset.py" --workspace "%ROOT%prepared_data\annotation_workspace" --templates "%ROOT%legend_templates_example\templates.json" --dataset "%ROOT%datasets\plans_auto" --max-page-size 2200 --threshold 0.82 --min-scale 0.7 --max-scale 1.25 --scale-step 0.15 --nms-distance 28 --max-per-template 20
) else (
  "%PYTHON_EXE%" "%ROOT%generate_pseudolabel_dataset.py" --workspace "%ROOT%prepared_data\annotation_workspace" --templates "%ROOT%legend_templates_example\templates.json" --dataset "%ROOT%datasets\plans_auto" --max-page-size 2200 --threshold 0.82 --min-scale 0.7 --max-scale 1.25 --scale-step 0.15 --nms-distance 28 --max-per-template 20
)

if errorlevel 1 (
  echo.
  echo Echec de la generation des pseudo-labels.
  pause
  exit /b 1
)

echo.
echo Entrainement du modele auto depuis les plans...
echo.

if "%PYTHON_EXE%"=="py -3" (
  py -3 "%ROOT%train.py" --dataset "%ROOT%datasets\plans_auto" --output "%ROOT%models\symbol_classifier_auto_from_plans.pt" --run-dir "%ROOT%training_runs\plans_auto_run_001" --epochs 12 --batch-size 32 --image-size 64 --min-samples-per-class 10
) else (
  "%PYTHON_EXE%" "%ROOT%train.py" --dataset "%ROOT%datasets\plans_auto" --output "%ROOT%models\symbol_classifier_auto_from_plans.pt" --run-dir "%ROOT%training_runs\plans_auto_run_001" --epochs 12 --batch-size 32 --image-size 64 --min-samples-per-class 10
)

if errorlevel 1 (
  echo.
  echo Echec de l'entrainement.
  pause
  exit /b 1
)

echo.
echo Generation des courbes...
echo.

if "%PYTHON_EXE%"=="py -3" (
  py -3 "%ROOT%plot_training_metrics.py" --metrics "%ROOT%training_runs\plans_auto_run_001\metrics.jsonl" --output "%ROOT%training_runs\plans_auto_run_001"
) else (
  "%PYTHON_EXE%" "%ROOT%plot_training_metrics.py" --metrics "%ROOT%training_runs\plans_auto_run_001\metrics.jsonl" --output "%ROOT%training_runs\plans_auto_run_001"
)

if errorlevel 1 (
  echo.
  echo Echec de la generation des courbes.
  pause
  exit /b 1
)

if exist "%ROOT%training_runs\plans_auto_run_001\loss_curve.png" (
  if not exist "%ROOT%training_runs\plans_auto_run_001\loss_images" mkdir "%ROOT%training_runs\plans_auto_run_001\loss_images"
  copy /Y "%ROOT%training_runs\plans_auto_run_001\loss_curve.png" "%ROOT%training_runs\plans_auto_run_001\loss_images\loss_curve.png" >nul
)

echo.
echo Pipeline auto terminee.
echo Modele :
echo   models\symbol_classifier_auto_from_plans.pt
echo Courbe de loss :
echo   training_runs\plans_auto_run_001\loss_images\loss_curve.png
pause
exit /b 0
