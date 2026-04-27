import json
import os
from pathlib import Path

# Check signal validator config
config_files = ['config/signal_validator.json', 'config.json', 'config/strategy.json']

print('===== H4 TREND FILTER CONFIGURATION =====\n')

for config_file in config_files:
    if os.path.exists(config_file):
        try:
            with open(config_file) as f:
                config = json.load(f)
                # Look for H4/Trend filter settings
                config_str = json.dumps(config, indent=2)
                if 'h4' in config_str.lower() or 'trend' in config_str.lower() or 'mtf' in config_str.lower():
                    print(f'\n--- {config_file} ---')
                    print(config_str[:1000])
        except Exception as e:
            pass

# Look for H4 filter settings in Python files
for py_file in Path('src').glob('**/*.py'):
    with open(py_file) as f:
        content = f.read()
        if 'h4' in content.lower() and 'filter' in content.lower():
            # Extract relevant lines
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if 'h4' in line.lower() and ('sma' in line.lower() or 'threshold' in line.lower() or 'trend' in line.lower()):
                    print(f'Found in {py_file.name}:{i}: {line[:100]}')
