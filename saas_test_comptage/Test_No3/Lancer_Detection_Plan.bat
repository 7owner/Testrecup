@echo off
REM Interface de detection sur plan PDF (modele local, torch-CPU).
REM Utilise le Python systeme (torch/torchvision/fitz), PAS le venv du projet.
cd /d "%~dp0"
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" serve_detect.py
pause
