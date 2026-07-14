@echo off
setlocal

set "ROOT=%~dp0"
set "UI=%ROOT%plan_counter_ui\plan_counter.html"

if not exist "%UI%" (
  echo Interface introuvable : "%UI%"
  pause
  exit /b 1
)

start "" "%UI%"
exit /b 0
