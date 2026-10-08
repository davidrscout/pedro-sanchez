@echo off
cd /d "%~dp0"
python webpanel.py devices
echo.
echo Para revocar TODOS los dispositivos autorizados: python webpanel.py revoke
pause
