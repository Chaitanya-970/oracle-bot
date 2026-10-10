@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM v34 launcher: Gemini 3.1 Flash-Lite only; uses the venv Python directly.

if "%GEMINI_API_KEY%"=="" if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /I "%%A"=="GEMINI_API_KEY" set "GEMINI_API_KEY=%%B"
    if /I "%%A"=="GEMINI_MODEL" set "GEMINI_MODEL=%%B"
  )
)

if "%GEMINI_API_KEY%"=="" (
  echo.
  echo [ERROR] GEMINI_API_KEY is not set.
  echo Put it in .env as: GEMINI_API_KEY=your_key_here
  echo.
  pause
  exit /b 1
)

if "%GEMINI_MODEL%"=="" set "GEMINI_MODEL=gemini-3.1-flash-lite"
echo [AI] Gemini model: %GEMINI_MODEL%
if not exist ".venv\Scripts\python.exe" (
  echo [SETUP] Creating Python virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Could not create .venv. Make sure Python is installed and the py launcher works.
    pause
    exit /b 1
  )
)

set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo [ERROR] Virtual environment Python is missing: %PYTHON%
  pause
  exit /b 1
)

echo [SETUP] Checking Python dependencies...
"%PYTHON%" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Dependency installation failed.
  pause
  exit /b 1
)

echo [RUN] Starting Oracle Quiz Runner v34...
"%PYTHON%" oracle_quiz_runner.py
set "EXITCODE=%ERRORLEVEL%"
echo.
echo [RUNNER] Exited with code %EXITCODE%.
pause
exit /b %EXITCODE%
