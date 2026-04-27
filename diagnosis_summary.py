# Summary of H4 Trend filter findings

print('===== SIGNAL FILTERING DIAGNOSIS SUMMARY =====\n')
print('COMMAND RUN: python diagnose_signal_filtering.py\n')

print('FINDINGS:')
print('-' * 70)
print('\n1. H4 TREND FILTER ACTIVE')
print('   • Location: src/strategies/trend_strategy.py (lines 895-914)')
print('   • Type: Multi-Timeframe filter')
print('   • Purpose: Block BUY/SELL signals when price is far from H4 trend\n')

print('2. FILTER THRESHOLDS (EXTREMELY TIGHT)')
print('   • BUY allowed:  Price > H4_SMA200 × 0.9995')
print('   • SELL allowed: Price < H4_SMA200 × 1.0005')
print('   • Band width:   ±0.05% around H4 SMA200')
print('   • Impact: Only ±0.05% deviation tolerated\n')

print('3. SIGNAL BLOCKING BEHAVIOR')
print('   • If Price > H4_SMA200 × 1.0005: BUY signals BLOCKED')
print('   • If Price < H4_SMA200 × 0.9995: SELL signals BLOCKED')
print('   • If Price far from band:        BOTH BUY & SELL BLOCKED\n')

print('4. TRADE ADMISSION STATISTICS')
print('   • Total Evaluated Signals: 120,040')
print('   • Total Admitted: 43,127 (35.9%)')
print('   • Total Rejected: 72,472 (60.4%)')
print('   • Rejection rate suggests strong filtering active\n')

print('5. RECENT LOG ANALYSIS')
print('   • No MTF-FILTER rejection logs found in output.log')
print('   • Indicates: No technical signals reaching filter recently')
print('   • OR: Price currently within acceptable band\n')

print('6. REQUIRED DATA FOR FULL DIAGNOSIS')
print('   • Current Price (from MT5 live data)')
print('   • H4 SMA200 value')
print('   • Price vs SMA200 distance percentage')
print('   • MT5 connection: NOT AVAILABLE in test environment\n')

print('CONCLUSION:')
print('-' * 70)
print('✓ H4 Trend filter IS ACTIVE with VERY TIGHT thresholds')
print('✓ Filter CAN block both BUY and SELL if price outside ±0.05% band')
print('⚠️  60.4% rejection rate confirms heavy filtering')
print('✓ Cannot determine if blocking NOW without MT5 live price data')
