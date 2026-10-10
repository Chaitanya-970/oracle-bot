@echo off
title Oracle Academy Bot
cd /d "%~dp0"

echo ========================================================
echo         Oracle Academy Course ^& Quiz Bot
echo ========================================================
echo.

if not exist ".env" (
    echo [.env file not found. Creating one from .env.example...]
    copy .env.example .env
)

findstr /i "your_groq_api_key_here" .env >nul 2>&1
if %errorlevel% == 0 (
    echo.
    echo [ATTENTION] You need to put your GROQ API KEY in .env file!
    echo 1. Open the file named '.env' in Notepad
    echo 2. Replace 'your_groq_api_key_here' with your Groq key
    echo 3. Save and run this file again.
    echo.
    pause
    exit /b
)

echo Starting Oracle Bot in Chrome...
echo (A Chrome window will open. Log into Oracle and follow terminal prompts)
echo.

python -X utf8 run_bot.py

if %errorlevel% neq 0 (
    echo.
    echo [Notice] Bot exited with an error code. Check logs/bot.log for details.
    pause
)
