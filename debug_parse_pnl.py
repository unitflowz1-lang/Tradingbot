#!/usr/bin/env python3
import re
import subprocess
import sys
import os

# Run a single backtest
env = os.environ.copy()
env['BACKTEST_ATR_PERIOD'] = '10'
env['BACKTEST_RISK_RATIO'] = '1.0'

result = subprocess.run(
    [sys.executable, "run_backtest.py"],
    capture_output=True,
    text=True,
    timeout=120,
    env=env
)

output = result.stdout + result.stderr

# Strip ANSI codes
ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
output_clean = ansi_escape.sub('', output)

# Try the regex
pattern = r'Total PnL:\s*([+-]?[\d.]+)'
match = re.search(pattern, output_clean, re.IGNORECASE)
if match:
    print(f"Regex MATCHED: {match.group(1)}")
    print(f"PnL value: {float(match.group(1))}")
else:
    print(f"Regex DID NOT MATCH")
    print(f"\nLooking for lines with 'Total':")
    for line in output_clean.split('\n'):
        if 'Total' in line or 'PnL' in line:
            print(f"  {repr(line)}")

