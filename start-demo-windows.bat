@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto failed
call .venv\Scripts\activate.bat
python -m pip install -r requirements-core.txt
if errorlevel 1 goto failed
python run.py
pause
exit /b
:failed
echo Install Python 3.10 or newer and retry. No Instagram login was attempted.
pause
exit /b 1
