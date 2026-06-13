# stop_windows.ps1 — Windows PowerShell script to stop FinAlly

Write-Host "Stopping FinAlly workstation..." -ForegroundColor Cyan
& docker compose down

if ($LASTEXITCODE -eq 0) {
    Write-Host "FinAlly stopped successfully." -ForegroundColor Green
} else {
    Write-Error "Failed to stop FinAlly containers."
}
