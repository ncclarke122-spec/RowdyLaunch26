# AntiDoze Fleet Dashboard - Windows Firewall Rule (Port 8080)
# Run in PowerShell as Administrator

Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host " AntiDoze Fleet Command: Windows Firewall Configuration (Port 8080)" -ForegroundColor Cyan
Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host ""

try {
    # Check if rule exists
    $existing = Get-NetFirewallRule -DisplayName "AntiDoze Fleet Dashboard (Port 8080)" -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "[OK] Firewall rule already exists for Port 8080." -ForegroundColor Green
    } else {
        New-NetFirewallRule -DisplayName "AntiDoze Fleet Dashboard (Port 8080)" -Direction Inbound -LocalPort 8080 -Protocol TCP -Action Allow -Profile Any -ErrorAction Stop | Out-Null
        Write-Host "[SUCCESS] Added Windows Firewall inbound rule for TCP Port 8080!" -ForegroundColor Green
    }
} catch {
    Write-Host "[INFO] Using netsh fallback..." -ForegroundColor Yellow
    & netsh advfirewall firewall add rule name="AntiDoze Fleet Dashboard (Port 8080)" dir=in action=allow protocol=TCP localport=8080 profile=any
}

Write-Host ""
Write-Host "To access the dashboard from another computer on the same Wi-Fi/network:" -ForegroundColor White
$ips = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "Loopback|vEthernet" -and $_.IPAddress -notlike "169.254*" }).IPAddress
foreach ($ip in $ips) {
    Write-Host "  -> http://${ip}:8080/" -ForegroundColor Cyan
}
Write-Host ""
Write-Host "Press any key to close..."
[void][System.Console]::ReadKey()
