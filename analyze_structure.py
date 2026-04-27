import json
import pprint

with open('trade_admission_history.json') as f:
    data = json.load(f)
    print('JSON Keys:', list(data.keys()))
    
    # Check if there are rejection windows
    if 'rejection_windows' in data:
        print('Rejection windows count:', len(data['rejection_windows']))
        if data['rejection_windows']:
            print('\nSample rejection window:')
            print(json.dumps(data['rejection_windows'][0], indent=2)[:800])
    
    # Check opportunity windows
    if 'opportunity_windows' in data:
        print('\nOpportunity windows regimes:', list(data['opportunity_windows'].keys()))
        for regime, windows in data['opportunity_windows'].items():
            if windows:
                print(f'\n{regime}: {len(windows)} signals')
                # Look at rejection reasons in these windows
                sample = windows[0] if isinstance(windows, list) and len(windows) > 0 else windows
                if isinstance(windows, dict):
                    sample = windows
                print('Sample:', json.dumps(sample, indent=2, default=str)[:500])
