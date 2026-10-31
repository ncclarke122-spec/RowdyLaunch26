@echo off
echo ====================================================================
echo  AntiDoze Fleet Command: Windows Firewall Port 8080 Setup
echo ====================================================================
echo.
echo Adding inbound Windows Firewall rule for TCP Port 8080...
echo (Allows other computers, tablets, and phones on the LAN to access the dashboard)
echo.

netsh advfirewall firewall add rule name="AntiDoze Fleet Dashboard (Port 8080)" dir=in action=allow protocol=TCP localport=8080 profile=any

echo.
if %ERRORLEVEL% equ 0 (
    echo ====================================================================
    echo [SUCCESS] Port 8080 is now open in Windows Firewall!
    echo.
    echo Other computers on your Wi-Fi / Local Network can now access the dashboard.
    echo Simply open a browser on the other computer and navigate to:
    echo.
    for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
        echo   -^> http:%%a:8080/
    )
    echo ====================================================================
) else (
    echo ====================================================================
    echo [NOTE] Administrator privileges required to configure Windows Firewall.
    echo Please right-click this 'allow_firewall.bat' file and select:
    echo   "Run as administrator"
    echo ====================================================================
)
echo.
pause
