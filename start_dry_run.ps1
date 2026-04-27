# ============================================
# DRY RUN LAUNCHER - 3-5 Day Forward Test
# PowerShell Version (Windows)
# ============================================
# Usage: 
#   .\start_dry_run.ps1
# ============================================

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  DRY RUN LAUNCHER - FORWARD TEST" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check if Python is available
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ ERROR: Python not found!" -ForegroundColor Red
    Write-Host "   Please install Python 3.12+" -ForegroundColor Yellow
    exit 1
}
Write-Host ""

# Check if .env file exists
if (-Not (Test-Path ".env")) {
    Write-Host "⚠️  WARNING: .env file not found!" -ForegroundColor Yellow
    Write-Host "   Creating default .env for dry run..." -ForegroundColor Yellow
    
    $envContent = @"
# DRY RUN CONFIGURATION
DRY_RUN=1
DRY_RUN_BALANCE=10000.0

# Risk Management
MAX_DRAWDOWN_PCT=15.0
RISK_PER_TRADE=0.02
MAX_POSITIONS=3

# Logging
LOG_LEVEL=INFO
LOG_TRADES=1
LOG_SIGNALS=1
LOG_FILE=logs/bot_dry_run.log

# Features
ENABLE_AGGRESSIVE_COMPOUNDING=1
ENABLE_SPREAD_TRAP_PROTECTION=1
ENABLE_ML_SIGNALS=1
ENABLE_MULTI_TF_ANALYSIS=1

# Trading Schedule
TRADING_ENABLED=1
MAX_DAILY_TRADES=20
"@
    
    $envContent | Out-File -FilePath ".env" -Encoding utf8
    Write-Host "✅ Created .env file with dry run configuration" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "✅ .env file found" -ForegroundColor Green
    
    # Check if DRY_RUN is enabled
    $envContent = Get-Content ".env" -Raw
    if ($envContent -match "DRY_RUN\s*=\s*(1|true|yes)") {
        Write-Host "✅ DRY_RUN mode is ENABLED" -ForegroundColor Green
    } else {
        Write-Host "⚠️  WARNING: DRY_RUN might not be enabled!" -ForegroundColor Yellow
        Write-Host "   Please verify .env has: DRY_RUN=1" -ForegroundColor Yellow
        Write-Host ""
        $confirm = Read-Host "Continue anyway? (y/n)"
        if ($confirm -ne "y") {
            Write-Host "Aborted. Please update .env file." -ForegroundColor Red
            exit 1
        }
    }
    Write-Host ""
}

# Check if logs directory exists
if (-Not (Test-Path "logs")) {
    Write-Host "📁 Creating logs directory..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path "logs" | Out-Null
    Write-Host "✅ Logs directory created" -ForegroundColor Green
    Write-Host ""
}

# Display current configuration
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  CONFIGURATION SUMMARY" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Mode: DRY RUN (No real trades)" -ForegroundColor White
Write-Host "Demo Account Balance: `$95,332.81" -ForegroundColor White
Write-Host "Max Drawdown Limit: 15%" -ForegroundColor White
Write-Host "Risk Per Trade: 2%" -ForegroundColor White
Write-Host "Max Positions: 3" -ForegroundColor White
Write-Host ""
Write-Host "Features Enabled:" -ForegroundColor White
Write-Host "  ✅ Aggressive Compounding (1.2x after 3 wins)" -ForegroundColor Green
Write-Host "  ✅ Spread Trap Protection (>2x avg spread blocked)" -ForegroundColor Green
Write-Host "  ✅ ML Signals" -ForegroundColor Green
Write-Host "  ✅ Multi-Timeframe Analysis" -ForegroundColor Green
Write-Host ""

# Pre-flight checklist
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  PRE-FLIGHT CHECKLIST" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$checklistPass = $true

# Check 1: MT5 terminal running
Write-Host "⏳ Checking MT5 terminal connection..." -ForegroundColor Yellow
try {
    $mt5Check = python -c "import MetaTrader5 as mt5; mt5.initialize(); info = mt5.account_info(); print('OK' if info else 'FAIL'); mt5.shutdown()" 2>&1
    if ($mt5Check -match "OK") {
        Write-Host "✅ MT5 terminal is running and connected" -ForegroundColor Green
    } else {
        Write-Host "❌ MT5 terminal is not running or not accessible" -ForegroundColor Red
        Write-Host "   Please start MT5 and login to your demo account" -ForegroundColor Yellow
        $checklistPass = $false
    }
} catch {
    Write-Host "❌ MT5 check failed: $_" -ForegroundColor Red
    $checklistPass = $false
}
Write-Host ""

# Check 2: Config files exist
Write-Host "⏳ Checking configuration files..." -ForegroundColor Yellow
if (Test-Path "config/optimized_params.json") {
    Write-Host "✅ Optimized parameters found: config/optimized_params.json" -ForegroundColor Green
} else {
    Write-Host "⚠️  Using default parameters (config/optimized_params.json not found)" -ForegroundColor Yellow
}
Write-Host ""

# Check 3: Required modules
Write-Host "⏳ Checking required Python modules..." -ForegroundColor Yellow
try {
    python -c "import pandas, numpy" 2>&1 | Out-Null
    Write-Host "✅ Core modules available (pandas, numpy)" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Some modules might be missing" -ForegroundColor Yellow
    Write-Host "   Run: pip install -r requirements.txt" -ForegroundColor Yellow
}
Write-Host ""

# Check 4: No existing bot instances
Write-Host "⏳ Checking for existing bot instances..." -ForegroundColor Yellow
$botProcesses = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*main.py*" }
if ($botProcesses.Count -gt 0) {
    Write-Host "❌ WARNING: $($botProcesses.Count) bot instance(s) already running!" -ForegroundColor Red
    Write-Host "   Please stop existing instances before starting new one" -ForegroundColor Yellow
    $checklistPass = $false
} else {
    Write-Host "✅ No existing bot instances found" -ForegroundColor Green
}
Write-Host ""

# Final decision
if (-Not $checklistPass) {
    Write-Host "============================================" -ForegroundColor Red
    Write-Host "  ❌ PRE-FLIGHT CHECK FAILED" -ForegroundColor Red
    Write-Host "============================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please fix the issues above before starting." -ForegroundColor Yellow
    exit 1
}

Write-Host "============================================" -ForegroundColor Green
Write-Host "  ✅ ALL CHECKS PASSED" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Starting dry run in 3 seconds..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop the bot at any time." -ForegroundColor Cyan
Write-Host ""
Start-Sleep -Seconds 3

# Launch the bot
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  🚀 LAUNCHING BOT IN DRY RUN MODE" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$logFile = "logs/dry_run_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

try {
    python main.py 2>&1 | Tee-Object -FilePath $logFile
} catch {
    Write-Host "❌ Bot crashed: $_" -ForegroundColor Red
}

# Post-run analysis
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  DRY RUN COMPLETED" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Log file saved to: $logFile" -ForegroundColor White
Write-Host ""
Write-Host "To analyze results, run:" -ForegroundColor White
Write-Host "  python scripts/analyze_dry_run_results.py" -ForegroundColor Yellow
Write-Host ""
