import json
with open('trade_admission_history.json') as f:
    data = json.load(f)
    print('===== SIGNAL FILTERING ANALYSIS =====')
    print('Total Evaluated:', data['stats']['total_evaluated'])
    print('Total Admitted:', data['stats']['total_admitted'])
    print('Total Rejected:', data['stats']['total_rejected'])
    print('Rejection Rate: {:.1f}%'.format(data['stats']['total_rejected'] / data['stats']['total_evaluated'] * 100))
    print()
    
    # Look for rejection windows
    if 'rejection_windows' in data and data['rejection_windows']:
        print('===== REJECTION PATTERNS =====')
        rejection_reasons = {}
        for window in data['rejection_windows'][:100]:  # Sample first 100
            reason = window.get('rejection_reason', 'Unknown')
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
        
        for reason, count in sorted(rejection_reasons.items(), key=lambda x: x[1], reverse=True):
            if count > 10:
                print('  {}x: {}'.format(count, reason[:100]))
    
    # Check for H4-specific rejections
    if 'rejection_windows' in data:
        h4_blocks = [w for w in data['rejection_windows'] if 'h4' in str(w).lower() or 'trend' in str(w).lower() or 'mtf' in str(w).lower()]
        if h4_blocks:
            print('\n===== H4 TREND FILTER BLOCKS =====')
            print('Found {} H4/Trend-related rejections'.format(len(h4_blocks)))
            if h4_blocks:
                print('Sample:', json.dumps(h4_blocks[0], indent=2)[:400])
