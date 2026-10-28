@echo off
setlocal
cd /d "%~dp0"

set "TASK_NAME=Anaplan Daily Backup"
set "RUN_TIME=%~1"
if "%RUN_TIME%"=="" set "RUN_TIME=01:00"

echo Creating Windows scheduled task "%TASK_NAME%" at %RUN_TIME% daily.
echo The task runs only while this user has an interactive Windows session.

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$q=[char]34; $arguments='/d /c '+$q+'%~dp0run.bat'+$q+' --run-once';" ^
  "$action=New-ScheduledTaskAction -Execute $env:ComSpec -Argument $arguments -WorkingDirectory '%~dp0';" ^
  "$trigger=New-ScheduledTaskTrigger -Daily -At '%RUN_TIME%';" ^
  "$user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name;" ^
  "$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited;" ^
  "Register-ScheduledTask -TaskName '%TASK_NAME%' -Action $action -Trigger $trigger -Principal $principal -Description 'Anaplan Copy and Archive backup' -Force | Out-Null"

if errorlevel 1 (
  echo ERROR: Could not create the scheduled task. Check the time format and Windows Task Scheduler permissions.
  exit /b 1
)

echo Installed "%TASK_NAME%". The task uses backup.dry_run from config\models.yaml.
exit /b 0
