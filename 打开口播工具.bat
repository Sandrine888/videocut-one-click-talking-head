@echo off
setlocal
cd /d "%~dp0"
if exist "venv_build\Scripts\pythonw.exe" (
    start "" "venv_build\Scripts\pythonw.exe" "%~dp0launch_web.pyw"
    exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%~dp0launch_web.pyw"
    exit /b
)
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3.11 "%~dp0launch_web.pyw"
    exit /b
)
echo Python 3.11 environment not found. Please install the project dependencies first.
pause
