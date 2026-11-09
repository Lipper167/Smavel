@echo off
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul && echo Created .env - open it, paste your API key(s), save, then run this file again. && notepad .env && pause && exit /b
python -m pip install -r requirements.txt
start "" http://127.0.0.1:8000
python -m uvicorn main:app --reload
pause
