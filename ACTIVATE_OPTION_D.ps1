param(
    [switch]$RunBot
)

# OPTION D: DEPLOYMENT ACTIVATION SCRIPT
#
# Run in PowerShell:
#   & ".\ACTIVATE_OPTION_D.ps1"
#   & ".\ACTIVATE_OPTION_D.ps1" -RunBot

Write-Host "=================================================================================" -ForegroundColor Cyan
Write-Host "OPTION D: DEPLOYMENT ACTIVATION" -ForegroundColor Cyan
Write-Host "Authorization Confirmed: 2026-04-03" -ForegroundColor Cyan
Write-Host "=================================================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "STEP 1: Setting Environment Variables..." -ForegroundColor Yellow
Write-Host ""

$env:STRICT_FRIDAY_LOCK = "0"
Write-Host "  [OK] STRICT_FRIDAY_LOCK = '0' (Friday lock disabled for this process)" -ForegroundColor Green

$env:FRIDAY_CUTOFF_HOUR = "23:59"
Write-Host "  [OK] FRIDAY_CUTOFF_HOUR = '23:59' (Trade until 23:59 UTC Friday)" -ForegroundColor Green

$env:OVERRIDE_ROLLOVER_PAUSE = "1"
Write-Host "  [OK] OVERRIDE_ROLLOVER_PAUSE = '1' (Rollover pause disabled)" -ForegroundColor Green

$env:ML_ACCURACY_MIN_GATE = "0.30"
Write-Host "  [OK] ML_ACCURACY_MIN_GATE = '0.30' (30% minimum ML accuracy)" -ForegroundColor Green

$env:SIGNAL_QUALITY_MINIMUM = "0.30"
Write-Host "  [OK] SIGNAL_QUALITY_MINIMUM = '0.30' (Quality floor 30%)" -ForegroundColor Green

$env:AGGRESSIVE_ENGAGEMENT = "1"
Write-Host "  [OK] AGGRESSIVE_ENGAGEMENT = '1' (Aggressive mode active)" -ForegroundColor Green

$env:SPREAD_ATR_RATIO_MAX = "1.50"
Write-Host "  [OK] SPREAD_ATR_RATIO_MAX = '1.50' (Spread tolerance widened to 150% of ATR)" -ForegroundColor Green

$env:MAX_ALLOWABLE_PIPS = "25.0"
$env:MAX_ALLOWED_SPREAD = "25.0"
Write-Host "  [OK] MAX_ALLOWABLE_PIPS = '25.0' (Hard spread cap widened)" -ForegroundColor Green
Write-Host "  [OK] MAX_ALLOWED_SPREAD = '25.0' (Alias for hard spread cap)" -ForegroundColor Green

$env:ADX_MIN_STRICT = "20"
Write-Host "  [OK] ADX_MIN_STRICT = '20' (Trend strength threshold relaxed)" -ForegroundColor Green

$env:ADX_MIN_EXECUTION_FLOOR = "12"
Write-Host "  [OK] ADX_MIN_EXECUTION_FLOOR = '12' (Reject only dead markets)" -ForegroundColor Green

$env:QUALITY_FLOOR_SCORE = "30"
Write-Host "  [OK] QUALITY_FLOOR_SCORE = '30' (Adaptive scorer base threshold)" -ForegroundColor Green

$env:BROKER_MIN_LOT = "0.05"
Write-Host "  [OK] BROKER_MIN_LOT = '0.05' (Zero-size protection floor)" -ForegroundColor Green

$env:POSITION_MULTIPLIER_FLOOR = "0.25"
Write-Host "  [OK] POSITION_MULTIPLIER_FLOOR = '0.25' (Multiplier floor enabled)" -ForegroundColor Green

$env:FORCE_TECHNICAL_ONLY_MODE = "1"
Write-Host "  [OK] FORCE_TECHNICAL_ONLY_MODE = '1' (LLM governance bypassed)" -ForegroundColor Green

$env:USE_MTF_FILTER = "0"
Write-Host "  [OK] USE_MTF_FILTER = '0' (Counter-trend entries allowed)" -ForegroundColor Green

$env:EV_THRESHOLD_R = "-5.0"
Write-Host "  [OK] EV_THRESHOLD_R = '-5.0' (Deeper negative EV tolerated)" -ForegroundColor Green

$env:PERMIT_INSTITUTIONAL_SWEEP_OVERRIDES = "1"
Write-Host "  [OK] PERMIT_INSTITUTIONAL_SWEEP_OVERRIDES = '1' (Sweep permission enabled)" -ForegroundColor Green

$env:ALLOW_FRIDAY_LATE_SESSION = "1"
Write-Host "  [OK] ALLOW_FRIDAY_LATE_SESSION = '1' (Friday late session enabled)" -ForegroundColor Green

Write-Host ""
Write-Host "STEP 2: Verification" -ForegroundColor Yellow
Write-Host ""
Write-Host "  STRICT_FRIDAY_LOCK = $env:STRICT_FRIDAY_LOCK" -ForegroundColor Cyan
Write-Host "  FRIDAY_CUTOFF_HOUR = $env:FRIDAY_CUTOFF_HOUR" -ForegroundColor Cyan
Write-Host "  OVERRIDE_ROLLOVER_PAUSE = $env:OVERRIDE_ROLLOVER_PAUSE" -ForegroundColor Cyan
Write-Host "  ML_ACCURACY_MIN_GATE = $env:ML_ACCURACY_MIN_GATE" -ForegroundColor Cyan
Write-Host "  SIGNAL_QUALITY_MINIMUM = $env:SIGNAL_QUALITY_MINIMUM" -ForegroundColor Cyan
Write-Host "  AGGRESSIVE_ENGAGEMENT = $env:AGGRESSIVE_ENGAGEMENT" -ForegroundColor Cyan
Write-Host "  SPREAD_ATR_RATIO_MAX = $env:SPREAD_ATR_RATIO_MAX" -ForegroundColor Cyan
Write-Host "  MAX_ALLOWABLE_PIPS = $env:MAX_ALLOWABLE_PIPS" -ForegroundColor Cyan
Write-Host "  MAX_ALLOWED_SPREAD = $env:MAX_ALLOWED_SPREAD" -ForegroundColor Cyan
Write-Host "  ADX_MIN_STRICT = $env:ADX_MIN_STRICT" -ForegroundColor Cyan
Write-Host "  ADX_MIN_EXECUTION_FLOOR = $env:ADX_MIN_EXECUTION_FLOOR" -ForegroundColor Cyan
Write-Host "  QUALITY_FLOOR_SCORE = $env:QUALITY_FLOOR_SCORE" -ForegroundColor Cyan
Write-Host "  BROKER_MIN_LOT = $env:BROKER_MIN_LOT" -ForegroundColor Cyan
Write-Host "  POSITION_MULTIPLIER_FLOOR = $env:POSITION_MULTIPLIER_FLOOR" -ForegroundColor Cyan
Write-Host "  FORCE_TECHNICAL_ONLY_MODE = $env:FORCE_TECHNICAL_ONLY_MODE" -ForegroundColor Cyan
Write-Host "  USE_MTF_FILTER = $env:USE_MTF_FILTER" -ForegroundColor Cyan
Write-Host "  EV_THRESHOLD_R = $env:EV_THRESHOLD_R" -ForegroundColor Cyan
Write-Host "  PERMIT_INSTITUTIONAL_SWEEP_OVERRIDES = $env:PERMIT_INSTITUTIONAL_SWEEP_OVERRIDES" -ForegroundColor Cyan
Write-Host "  ALLOW_FRIDAY_LATE_SESSION = $env:ALLOW_FRIDAY_LATE_SESSION" -ForegroundColor Cyan
Write-Host ""

Write-Host "=================================================================================" -ForegroundColor Cyan
Write-Host "OPTION D ACTIVATION COMPLETE" -ForegroundColor Green
Write-Host "=================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "CRITICAL REMINDERS:" -ForegroundColor Red
Write-Host ""
Write-Host "1. Rollover protection disabled: 21:55-22:15 UTC can trade with elevated spread/slippage risk." -ForegroundColor Yellow
Write-Host "2. Friday late session active: trading can continue until 23:59 UTC Friday." -ForegroundColor Yellow
Write-Host "3. Low ML accuracy gate: 30% permits more trades but lowers quality." -ForegroundColor Yellow
Write-Host "4. Hard limits still enforced: daily loss cap, position caps, and R/R minimum remain active." -ForegroundColor Yellow
Write-Host ""

if ($RunBot) {
    Write-Host "Launching python main.py in the same PowerShell process..." -ForegroundColor Cyan
    Write-Host ""
    python main.py
} else {
    Write-Host "NEXT STEP: Run '& .\\ACTIVATE_OPTION_D.ps1 -RunBot' to launch the bot in the same PowerShell process." -ForegroundColor Cyan
    Write-Host ""
}
