@echo off
powershell -NoProfile -Command "Stop-ScheduledTask -TaskName Jarvis -EA SilentlyContinue; Unregister-ScheduledTask -TaskName Jarvis -Confirm:$false -EA SilentlyContinue; Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -match 'jarvis.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; 'Jarvis desinstalado.'"
pause
