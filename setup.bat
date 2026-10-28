@echo off
setlocal
cd /d "%~dp0"

echo Anaplan Daily Backup - Windows setup
where py >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python 3 and the Windows py launcher are required.
  exit /b 1
)

py -3 -m venv .venv || exit /b 1
call ".venv\Scripts\activate.bat" || exit /b 1
python -m pip install --upgrade pip || exit /b 1
python -m pip install -r requirements.txt || exit /b 1
python -m playwright install chromium || exit /b 1

if not exist ".env" copy /Y ".env.example" ".env" >nul
if not exist "config\models.yaml" copy /Y "config\models.example.yaml" "config\models.yaml" >nul
if not exist "logs" mkdir "logs"
if not exist ".browser-profile" mkdir ".browser-profile"

echo.
echo Setup complete.
echo 1. Edit config\models.yaml
echo 2. Keep backup.dry_run: true
echo 3. Run: run.bat --check-config
echo 4. Run: run.bat --dry-run
exit /b 0
