#!/usr/bin/env python3
"""Fix redundant position sizer overrides in main.py"""

import re

# Read the file
with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Pattern to find the problematic section
# We'll look for the logger.debug line and replace through the logger.info with ConfMult
pattern = r"(\s+)logger\.debug\(f\"\[FINAL_SIZE\].*?PositionSizer output:.*?lots.*?\)\)\n(.*?)\n(\s+)logger\.info\(\s+\"\[ACTION\] Risk OK.*?ConfMult:.*?Final: %s lots\","

# Find matches
matches = list(re.finditer(pattern, content, re.DOTALL))
print(f"Found {len(matches)} matches")

if matches:
    match = matches[0]
    start = match.start()
    end = match.end()
    
    print(f"Match found at char {start} to {end}")
    print(f"\nSection to be replaced:")
    print(content[start:start+500])
else:
    print("No matches found - trying simpler pattern")
    
    # Try simpler pattern - just look for confluence_score.position_size_multiplier
    if "confluence_score.position_size_multiplier" in content:
        idx = content.find("confluence_score.position_size_multiplier")
        print(f"\nFound confluence_score.position_size_multiplier at char {idx}")
        print(f"Context: {content[max(0, idx-200):idx+200]}")
    else:
        print("confluence_score pattern not found")
