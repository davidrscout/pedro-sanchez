@echo off
REM Prepara Windows para encenderse por red (Wake-on-LAN) desde apagado. Pide administrador.
net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo Pidiendo permisos de administrador...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
echo [1/3] Desactivando el inicio rapido (apagado completo de verdad)...
reg add "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power" /v HiberbootEnabled /t REG_DWORD /d 0 /f
echo.
echo [2/3] Activando Wake on Magic Packet en la tarjeta de cable...
powershell -NoProfile -Command "$n='Ethernet'; try{Set-NetAdapterPowerManagement -Name $n -WakeOnMagicPacket Enabled -WakeOnPattern Disabled -ErrorAction Stop; 'Magic packet: OK'}catch{'Magic packet: '+$_.Exception.Message}; foreach($p in 'Shutdown Wake-On-Lan','Wake on Magic Packet'){ try{Set-NetAdapterAdvancedProperty -Name $n -DisplayName $p -DisplayValue 'Enabled' -ErrorAction Stop; $p+': Enabled'}catch{$p+': (no existe en este driver)'} }; try{Set-NetAdapterAdvancedProperty -Name $n -DisplayName 'Energy Efficient Ethernet' -DisplayValue 'Disabled' -ErrorAction Stop; 'EEE: Disabled'}catch{'EEE: (no existe)'}"
echo.
echo [3/3] Permitiendo que la tarjeta despierte el equipo...
for /f "delims=" %%A in ('powershell -NoProfile -Command "(Get-NetAdapter -Name Ethernet).InterfaceDescription"') do powercfg -deviceenablewake "%%A"
echo.
echo Dispositivos armados para despertar:
powercfg -devicequery wake_armed
echo.
echo FALTA UN PASO TUYO EN LA BIOS: activar "Power On By PCI-E" (Advanced, APM). Al reiniciar, pulsa Supr o F2.
pause
