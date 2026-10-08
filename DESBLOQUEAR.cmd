@echo off
cd /d "%~dp0"
del /q LOCKED 2>nul
del /q webpanel_state.json 2>nul
echo Panel desbloqueado: IPs bloqueadas, pausa y contadores a cero.
pause
