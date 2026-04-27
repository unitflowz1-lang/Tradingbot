#!/bin/bash
# Quick Start Script for Walk-Forward Multi-Objective Optimization
# Usage: ./run_optimization.sh

echo "========================================================"
echo "Walk-Forward Multi-Objective Optimization Suite"
echo "v2.1.0 - Anti-Overfitting Parameter Optimization"
echo "========================================================"
echo ""

# Step 1: Backup current parameters
echo "[1/5] Backing up current parameters..."
if [ -f "config/optimized_params.json" ]; then
    cp config/optimized_params.json config/optimized_params_backup_$(date +%Y%m%d_%H%M%S).json
    echo "✅ Backup created"
else
    echo "⚠️  No existing parameters to backup"
fi
echo ""

# Step 2: Check Python environment
echo "[2/5] Checking Python environment..."
python -c "import numpy; import pandas; print(f'✅ NumPy: {numpy.__version__}'); print(f'✅ Pandas: {pandas.__version__}')" || {
    echo "❌ Missing dependencies. Installing..."
    pip install numpy pandas scipy
}
echo ""

# Step 3: Verify historical data exists
echo "[3/5] Checking historical data..."
if [ -d "EURUSD Data" ] || [ -d "data" ]; then
    echo "✅ Historical data directory found"
else
    echo "⚠️  Warning: No historical data directory found"
    echo "    Optimization may use simulated data"
fi
echo ""

# Step 4: Run optimization
echo "[4/5] Starting optimization..."
echo "    This may take 30-60 minutes..."
echo ""
python scripts/walkforward_multi_optimizer.py

# Step 5: Display results
echo ""
echo "[5/5] Optimization complete!"
echo ""

if [ -f "config/optimized_params.json" ]; then
    echo "========================================================"
    echo "OPTIMIZATION RESULTS SUMMARY"
    echo "========================================================"
    python -c "
import json
with open('config/optimized_params.json', 'r') as f:
    params = json.load(f)
    
print(f\"Optimization Date: {params.get('optimization_date', 'N/A')}\")
print(f\"Fitness Score: {params.get('fitness_score', 0):.2f}\")
print(f\"Stability Rank: {params.get('stability_rank', 'N/A')}\")
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
"
    echo ""
    echo "========================================================"
    echo "OUTPUT FILES:"
    echo "========================================================"
    echo "✅ config/optimized_params.json (updated)"
    echo "✅ optimization_results/wfa_report.json (detailed)"
    echo "✅ optimization_results/wfa_optimization.log (execution log)"
    echo ""
    echo "========================================================"
    echo "NEXT STEPS:"
    echo "========================================================"
    echo "1. Review detailed report: cat optimization_results/wfa_report.json"
    echo "2. Run full backtest to validate results"
    echo "3. Paper trade for 1-2 weeks"
    echo "4. Deploy to production if results are satisfactory"
    echo ""
else
    echo "❌ Optimization failed. Check logs:"
    echo "   cat optimization_results/wfa_optimization.log"
    exit 1
fi
