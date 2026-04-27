# Quick Start Script for Walk-Forward Multi-Objective Optimization (Windows PowerShell)
# Usage: .\scripts\run_optimization.ps1

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "Walk-Forward Multi-Objective Optimization Suite" -ForegroundColor Cyan
Write-Host "v2.1.0 - Anti-Overfitting Parameter Optimization" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Backup current parameters
Write-Host "[1/5] Backing up current parameters..." -ForegroundColor Yellow
$backupPath = "config\optimized_params_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss').json"
if (Test-Path "config\optimized_params.json") {
    Copy-Item "config\optimized_params.json" $backupPath
    Write-Host "✅ Backup created: $backupPath" -ForegroundColor Green
} else {
    Write-Host "⚠️  No existing parameters to backup" -ForegroundColor Yellow
}
Write-Host ""

# Step 2: Check Python environment
Write-Host "[2/5] Checking Python environment..." -ForegroundColor Yellow
try {
    $numpyVersion = python -c "import numpy; print(numpy.__version__)"
    $pandasVersion = python -c "import pandas; print(pandas.__version__)"
    Write-Host "✅ NumPy: $numpyVersion" -ForegroundColor Green
    Write-Host "✅ Pandas: $pandasVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Missing dependencies. Installing..." -ForegroundColor Red
    pip install numpy pandas scipy
}
Write-Host ""

# Step 3: Verify historical data exists
Write-Host "[3/5] Checking historical data..." -ForegroundColor Yellow
if ((Test-Path "EURUSD Data") -or (Test-Path "data")) {
    Write-Host "✅ Historical data directory found" -ForegroundColor Green
} else {
    Write-Host "⚠️  Warning: No historical data directory found" -ForegroundColor Yellow
    Write-Host "    Optimization may use simulated data" -ForegroundColor Yellow
}
Write-Host ""

# Step 4: Run optimization
Write-Host "[4/5] Starting optimization..." -ForegroundColor Yellow
Write-Host "    This may take 30-60 minutes..." -ForegroundColor Yellow
Write-Host ""
python scripts\walkforward_multi_optimizer.py

# Step 5: Display results
Write-Host ""
Write-Host "[5/5] Optimization complete!" -ForegroundColor Green
Write-Host ""

if (Test-Path "config\optimized_params.json") {
    Write-Host "========================================================" -ForegroundColor Cyan
    Write-Host "OPTIMIZATION RESULTS SUMMARY" -ForegroundColor Cyan
    Write-Host "========================================================" -ForegroundColor Cyan
    
    python -c @"
import json
with open('config/optimized_params.json', 'r') as f:
    params = json.load(f)
    
print(f"Optimization Date: {params.get('optimization_date', 'N/A')}")
print(f"Fitness Score: {params.get('fitness_score', 0):.2f}")
print(f"Stability Rank: {params.get('stability_rank', 'N/A')}")
print()
print('Entry Filters:')
for k, v in params.get('entry_filters', {}).items():
    print(f'  {k}: {v}')
print()
print('Signal Weights:')
for k, v in params.get('signal_weights', {}).items():
    print(f'  {k}: {v}')
print()
print('Expected Performance:')
for k, v in params.get('expected_performance', {}).items():
    if isinstance(v, float):
        if 'rate' in k.lower() or 'pct' in k.lower():
            print(f'  {k}: {v:.2%}')
        else:
            print(f'  {k}: {v:.2f}')
    else:
        print(f'  {k}: {v}')
print()
print('Alpha Pairs:', params.get('alpha_pairs', []))
print('Low-Aggression Pairs:', params.get('low_aggression_pairs', []))
"@
    
    Write-Host ""
    Write-Host "========================================================" -ForegroundColor Cyan
    Write-Host "OUTPUT FILES:" -ForegroundColor Cyan
    Write-Host "========================================================" -ForegroundColor Cyan
    Write-Host "✅ config\optimized_params.json (updated)" -ForegroundColor Green
    Write-Host "✅ optimization_results\wfa_report.json (detailed)" -ForegroundColor Green
    Write-Host "✅ optimization_results\wfa_optimization.log (execution log)" -ForegroundColor Green
    Write-Host ""
    Write-Host "========================================================" -ForegroundColor Cyan
    Write-Host "NEXT STEPS:" -ForegroundColor Cyan
    Write-Host "========================================================" -ForegroundColor Cyan
    Write-Host "1. Review detailed report: Get-Content optimization_results\wfa_report.json" -ForegroundColor White
    Write-Host "2. Run full backtest to validate results" -ForegroundColor White
    Write-Host "3. Paper trade for 1-2 weeks" -ForegroundColor White
    Write-Host "4. Deploy to production if results are satisfactory" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host "❌ Optimization failed. Check logs:" -ForegroundColor Red
    Write-Host "   Get-Content optimization_results\wfa_optimization.log" -ForegroundColor Yellow
    exit 1
}
