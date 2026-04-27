@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "APP_URL=http://127.0.0.1:8085"
set "RUNTIME_DIR=%CD%\.runtime"
set "UV_BIN="

if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"

echo Starting SRT Coder...

call :resolve_uv_bin
if not defined UV_BIN (
    echo Installing local runtime manager ^(uv^) ...
    where powershell >nul 2>nul
    if errorlevel 1 (
        echo Error: PowerShell is required but was not found.
        exit /b 1
    )
    set "UV_INSTALL_DIR=%CD%\.local"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
)

call :resolve_uv_bin
if not defined UV_BIN (
    echo Error: uv was not found after installation.
    echo Expected at .local\bin\uv.exe, .local\uv.exe, or on PATH.
    exit /b 1
)

echo Preparing Python environment ...
if not exist "%CD%\.venv\Scripts\python.exe" (
    "%UV_BIN%" venv "%CD%\.venv" --python 3.13
) else (
    echo Using existing virtual environment at .venv
)

"%UV_BIN%" pip install --python "%CD%\.venv\Scripts\python.exe" -r "%CD%\requirements.txt"
if errorlevel 1 exit /b 1

echo Launching app ...
start "" "%APP_URL%"
echo SRT Coder running in this terminal.
echo Close this terminal window to stop SRT Coder.

"%CD%\.venv\Scripts\python.exe" "%CD%\app.py"
exit /b %ERRORLEVEL%

:resolve_uv_bin
if exist "%CD%\.local\bin\uv.exe" (
    set "UV_BIN=%CD%\.local\bin\uv.exe"
    exit /b 0
)
if exist "%CD%\.local\uv.exe" (
    set "UV_BIN=%CD%\.local\uv.exe"
    exit /b 0
)
where uv >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('where uv') do (
        if not defined UV_BIN set "UV_BIN=%%I"
    )
)
exit /b 0
