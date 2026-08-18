@echo off
setlocal
set "SCRIPT_DIR=%~dp0"

echo Running automated setup: ensuring Python and launching installer...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%scripts\ensure_python_and_run.ps1"
if %errorlevel% neq 0 (
    echo Setup failed. See the PowerShell output above for details.
    pause
    endlocal
    exit /b %errorlevel%
)

endlocal
exit /b 0
