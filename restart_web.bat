@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 goto :fail

set "PYTHON_EXE=%VECTOR_PYTHON%"
if not defined PYTHON_EXE set "PYTHON_EXE=D:\CONDA_ENVS\env-py3117\python.exe"
if not defined VECTOR_PYTHON if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
"%PYTHON_EXE%" -c "import vector_harness.web"
if errorlevel 1 goto :fail

echo Checking the Web service on port 8787...
powershell.exe -NoProfile -Command ^
  "$ErrorActionPreference = 'Stop'; try {" ^
  "$listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -eq 8787 });" ^
  "$owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique);" ^
  "foreach ($ownerId in $owners) { $service = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $ownerId); if ($null -eq $service -or $service.Name -notmatch '^python(w)?\.exe$' -or $service.CommandLine -notmatch '(?:^|\s)-m\s+vector_harness\.web(?:\s|$)') { throw ('Port 8787 belongs to another service (PID ' + $ownerId + '). Nothing stopped.') } };" ^
  "foreach ($ownerId in $owners) { Stop-Process -Id $ownerId -Force -ErrorAction Stop; Wait-Process -Id $ownerId -Timeout 10 -ErrorAction SilentlyContinue; Write-Host ('Stopped Web service: ' + $ownerId) };" ^
  "} catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 goto :fail

echo Starting http://127.0.0.1:8787/ with max-steps=50
echo Keep this window open. Press Ctrl+C to stop the service.
"%PYTHON_EXE%" -m vector_harness.web --workspace . --max-steps 50
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo Web service restart failed. See the error above.
pause
exit /b 1
