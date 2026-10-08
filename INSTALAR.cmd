@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$a=New-ScheduledTaskAction -Execute '%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe' -Argument '\"%~dp0jarvis.py\"' -WorkingDirectory '%~dp0'; $t=New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; $s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1); Register-ScheduledTask -TaskName 'Jarvis' -Action $a -Trigger $t -Settings $s -RunLevel Limited -Force | Out-Null; Start-ScheduledTask -TaskName 'Jarvis'; 'Jarvis instalado y arrancado.'"
pause
