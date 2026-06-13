# start_windows.ps1 — Windows PowerShell launcher for FinAlly

# 1. Check for .env file
if (-not (Test-Path ".env")) {
    Write-Host "WARNING: .env file not found. Creating a default one from .env.example..." -ForegroundColor Yellow
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
    } else {
        Set-Content -Path ".env" -Value "OPENROUTER_API_KEY=your-key-here`nLLM_MOCK=true"
    }
}

# 2. Check if Docker is running
Write-Host "Checking if Docker is running..." -ForegroundColor Cyan
& docker info >$null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker Desktop is not running. Please start Docker and try again."
    Exit 1
}

# 3. Build and launch containers
Write-Host "Building and starting FinAlly trading workstation..." -ForegroundColor Cyan
& docker compose up -d --build

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to start Docker containers."
    Exit 1
}

# 4. Open in browser
Write-Host "--------------------------------------------------------" -ForegroundColor Green
Write-Host "FinAlly AI Workstation is running!" -ForegroundColor Green
Write-Host "Access it at: http://localhost:8000" -ForegroundColor Green
Write-Host "--------------------------------------------------------" -ForegroundColor Green

Start-Sleep -Seconds 2
Start-Process "http://localhost:8000"
