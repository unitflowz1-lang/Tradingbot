# MT5 Connection Test - Run as Administrator
# Right-click this file and select "Run with PowerShell"

Write-Host "🤖 AI Trading Bot - MT5 Admin Test" -ForegroundColor Cyan
Write-Host "=" * 50

# Check if running as administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")

if (-not $isAdmin) {
    Write-Host "❌ Not running as Administrator" -ForegroundColor Red
    Write-Host "Please right-click this file and select 'Run as Administrator'" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit
}

Write-Host "✅ Running as Administrator" -ForegroundColor Green

# Navigate to the project directory
Set-Location $PSScriptRoot

# Activate virtual environment
Write-Host "🔄 Activating virtual environment..." -ForegroundColor Yellow
& ".\.venv\Scripts\Activate.ps1"

# Test MT5 connection
Write-Host "🧪 Testing MT5 connection..." -ForegroundColor Yellow
python test_mt5_basic.py

Write-Host "`n🚀 Testing full connection..." -ForegroundColor Yellow
python connect_mt5_demo.py

Write-Host "`n✅ Tests completed!" -ForegroundColor Green
Read-Host "Press Enter to exit"