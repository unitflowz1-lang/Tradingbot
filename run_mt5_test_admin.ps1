# MT5 Connection Test - Auto-elevate to Administrator
# This script will automatically request Administrator privileges

param(
    [switch]$Elevated
)

function Test-Admin {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not $Elevated) {
    if (Test-Admin) {
        Write-Host "✅ Already running as Administrator" -ForegroundColor Green
    } else {
        Write-Host "🔄 Requesting Administrator privileges..." -ForegroundColor Yellow
        Start-Process PowerShell -Verb RunAs -ArgumentList ("-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Elevated")
        exit
    }
}

# Now we're running as Administrator
Write-Host "🤖 AI Trading Bot - MT5 Connection Test (Administrator Mode)" -ForegroundColor Cyan
Write-Host "=" * 60

# Navigate to the script directory
Set-Location $PSScriptRoot

# Activate virtual environment
Write-Host "🔄 Activating virtual environment..." -ForegroundColor Yellow
try {
    & ".\.venv\Scripts\Activate.ps1"
    Write-Host "✅ Virtual environment activated" -ForegroundColor Green
} catch {
    Write-Host "❌ Failed to activate virtual environment: $_" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit
}

# Run the MT5 test
Write-Host "`n🧪 Running MT5 connection test..." -ForegroundColor Yellow
python test_mt5_with_path.py

Write-Host "`n🚀 Running full connection test..." -ForegroundColor Yellow
python connect_mt5_demo.py

Write-Host "`n✅ Tests completed!" -ForegroundColor Green
Write-Host "Press Enter to exit..." -ForegroundColor Yellow
Read-Host