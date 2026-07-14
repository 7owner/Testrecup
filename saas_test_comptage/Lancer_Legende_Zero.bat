@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=C:\Users\takot\AppData\Local\Programs\Python\Python312\python.exe"
set "URL=http://127.0.0.1:8870"
set "WAIT_PS=$ready=$false; for($i=0; $i -lt 30; $i++){ try { $resp=Invoke-WebRequest -UseBasicParsing '%URL%'; if($resp.StatusCode -eq 200){ $ready=$true; break } } catch {} Start-Sleep -Milliseconds 500 }; if(-not $ready){ exit 1 }"

start "Legend Zero Server" cmd /k ""%PYTHON_EXE%" legend_zero\run_server.py"
powershell -NoProfile -Command "%WAIT_PS%"
start "" "%URL%"

endlocal
