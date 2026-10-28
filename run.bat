@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Environment not installed. Run setup.bat first.
  exit /b 1
)

".venv\Scripts\python.exe" app\main.py %*
exit /b %ERRORLEVEL%
