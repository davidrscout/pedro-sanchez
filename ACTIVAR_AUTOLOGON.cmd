@echo off
REM Activa el inicio de sesion automatico de ADMIN (cuenta SIN contrasena) para que Jarvis arranque solo tras encender el PC.
net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo Pidiendo permisos de administrador...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
set K=HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon
reg add "%K%" /v AutoAdminLogon /t REG_SZ /d 1 /f
reg add "%K%" /v DefaultUserName /t REG_SZ /d %USERNAME% /f
reg add "%K%" /v DefaultDomainName /t REG_SZ /d %COMPUTERNAME% /f
reg add "%K%" /v DefaultPassword /t REG_SZ /d "" /f
echo.
echo Listo: el PC entrara solo a la sesion de %USERNAME% al encender. Para quitarlo: DESACTIVAR_AUTOLOGON.cmd
pause
