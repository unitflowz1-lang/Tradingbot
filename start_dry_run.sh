#!/bin/bash
# ============================================
# DRY RUN LAUNCHER - 3-5 Day Forward Test
# ============================================
# Usage: 
#   chmod +x start_dry_run.sh
#   ./start_dry_run.sh
# ============================================

echo "============================================"
echo "  DRY RUN LAUNCHER - FORWARD TEST"
echo "============================================"
echo ""

# Check if Python is available
if ! command -v python &> /dev/null; then
    echo "❌ ERROR: Python not found!"
    echo "   Please install Python 3.12+"
    exit 1
fi

echo "✅ Python found: $(python --version)"
echo ""

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  WARNING: .env file not found!"
    echo "   Creating default .env for dry run..."
    cat > .env << 'EOF'
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
EOF
    echo "✅ Created .env file with dry run configuration"
    echo ""
else
    echo "✅ .env file found"
    
    # Check if DRY_RUN is enabled
    if grep -q "DRY_RUN=1" .env || grep -q "DRY_RUN=true" .env; then
        echo "✅ DRY_RUN mode is ENABLED"
    else
        echo "⚠️  WARNING: DRY_RUN might not be enabled!"
        echo "   Please verify .env has: DRY_RUN=1"
        echo ""
        read -p "Continue anyway? (y/n): " confirm
        if [ "$confirm" != "y" ]; then
            echo "Aborted. Please update .env file."
            exit 1
        fi
    fi
    echo ""
fi

# Check if logs directory exists
if [ ! -d "logs" ]; then
    echo "📁 Creating logs directory..."
    mkdir -p logs
    echo "✅ Logs directory created"
    echo ""
fi

# Display current configuration
echo "============================================"
echo "  CONFIGURATION SUMMARY"
echo "============================================"
echo ""
echo "Mode: DRY RUN (No real trades)"
echo "Demo Account Balance: \$95,332.81"
echo "Max Drawdown Limit: 15%"
echo "Risk Per Trade: 2%"
echo "Max Positions: 3"
echo ""
echo "Features Enabled:"
echo "  ✅ Aggressive Compounding (1.2x after 3 wins)"
echo "  ✅ Spread Trap Protection (>2x avg spread blocked)"
echo "  ✅ ML Signals"
echo "  ✅ Multi-Timeframe Analysis"
echo ""

# Pre-flight checklist
echo "============================================"
echo "  PRE-FLIGHT CHECKLIST"
echo "============================================"
echo ""

CHECKLIST_PASS=true

# Check 1: MT5 terminal running
echo "⏳ Checking MT5 terminal connection..."
python -c "import MetaTrader5 as mt5; mt5.initialize(); info = mt5.account_info(); print(f'✅ MT5 connected: Account {info.login} | Balance \${info.balance:.2f}') if info else print('❌ MT5 connection failed'); mt5.shutdown()" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "❌ MT5 terminal is not running or not accessible"
    echo "   Please start MT5 and login to your demo account"
    CHECKLIST_PASS=false
fi
echo ""

# Check 2: Config files exist
echo "⏳ Checking configuration files..."
if [ -f "config/optimized_params.json" ]; then
    echo "✅ Optimized parameters found: config/optimized_params.json"
else
    echo "⚠️  Using default parameters (config/optimized_params.json not found)"
fi
echo ""

# Check 3: Required modules
echo "⏳ Checking required Python modules..."
python -c "import pandas, numpy, torch" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ Core modules available (pandas, numpy, torch)"
else
    echo "⚠️  Some modules might be missing"
    echo "   Run: pip install -r requirements.txt"
fi
echo ""

# Check 4: No existing bot instances
echo "⏳ Checking for existing bot instances..."
BOT_COUNT=$(ps aux | grep "python main.py" | grep -v grep | wc -l)
if [ "$BOT_COUNT" -gt 0 ]; then
    echo "❌ WARNING: $BOT_COUNT bot instance(s) already running!"
    echo "   Please stop existing instances before starting new one"
    CHECKLIST_PASS=false
else
    echo "✅ No existing bot instances found"
fi
echo ""

# Final decision
if [ "$CHECKLIST_PASS" = false ]; then
    echo "============================================"
    echo "  ❌ PRE-FLIGHT CHECK FAILED"
    echo "============================================"
    echo ""
    echo "Please fix the issues above before starting."
    exit 1
fi

echo "============================================"
echo "  ✅ ALL CHECKS PASSED"
echo "============================================"
echo ""
echo "Starting dry run in 3 seconds..."
echo "Press Ctrl+C to stop the bot at any time."
echo ""
sleep 3

# Launch the bot
echo "============================================"
echo "  🚀 LAUNCHING BOT IN DRY RUN MODE"
echo "============================================"
echo ""

python main.py 2>&1 | tee logs/dry_run_$(date +%Y%m%d_%H%M%S).log

# Post-run analysis
echo ""
echo "============================================"
echo "  DRY RUN COMPLETED"
echo "============================================"
echo ""
echo "Log file saved to: logs/dry_run_*.log"
echo ""
echo "To analyze results, run:"
echo "  python scripts/analyze_dry_run_results.py"
echo ""
