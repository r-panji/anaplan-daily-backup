@echo off
setlocal
set "TASK_NAME=Anaplan Daily Backup"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$task=Get-ScheduledTask -TaskName '%TASK_NAME%' -ErrorAction SilentlyContinue; if ($task) { Unregister-ScheduledTask -TaskName '%TASK_NAME%' -Confirm:$false }"

if errorlevel 1 exit /b 1
echo Removed "%TASK_NAME%".
exit /b 0
