import json
import os

# Find the H4 filter thresholds from the code
print('===== H4 TREND FILTER PARAMETERS =====\n')

with open('src/strategies/trend_strategy.py', 'r') as f:
    lines = f.readlines()
    for i, line in enumerate(lines[895:920]):
        print(line.rstrip())

print('\n===== CURRENT FILTER STATUS =====')
print('\nThe H4 Trend filter has these thresholds:')
print('  BUY allowed:  current_price > h4_sma200 * 0.9995  (price above 99.95% of SMA200)')
print('  SELL allowed: current_price < h4_sma200 * 1.0005  (price below 100.05% of SMA200)')
print('\n  ⚠️  This is a VERY TIGHT band - only ±0.05% of SMA200!')
print('  ⚠️  If price is outside this band:')
print('      - BUY signals are BLOCKED')
print('      - SELL signals are BLOCKED')
print('      - Both directions rejected')

print('\nTo check current market state:')
print('  1. Current price vs H4 SMA200 distance needed')
print('  2. Check if price is in the 99.95%-100.05% band')
print('  3. MT5 data needed (not available in test environment)')
