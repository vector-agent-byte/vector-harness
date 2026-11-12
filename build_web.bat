@echo off
setlocal
cd /d "%~dp0web"
if errorlevel 1 goto :fail

where node.exe >nul 2>&1
if errorlevel 1 (
    echo Node.js is missing from PATH. Install Node.js first.
    goto :fail
)
where npm.cmd >nul 2>&1
if errorlevel 1 (
    echo npm is missing from PATH. Install Node.js with npm first.
    goto :fail
)

if not exist "node_modules\" (
    echo Installing frontend dependencies...
    call npm.cmd ci
    if errorlevel 1 goto :fail
)

echo Building the Web frontend...
call npm.cmd run build
if errorlevel 1 goto :fail
echo.
echo Build complete: %~dp0web\dist
echo Refresh the browser to load the new frontend.
pause
exit /b 0

:fail
echo.
echo Web build failed. See the error above.
pause
exit /b 1
