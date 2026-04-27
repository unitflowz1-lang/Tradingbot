"""
Quick fix script to replace non-ASCII characters in main.py logs
Run: python fix_ascii_main.py
"""
import re

file_path = "main.py"

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace lock emoji with hyphen
content = content.replace('🔒', '-')
# Replace prohibition sign with hyphen  
content = content.replace('🚫', '-')
# Replace checkmark with [OK]
content = content.replace('✅', '[OK]')
# Replace question mark box with hyphen
content = content.replace('?', '-')

# Write back
with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("[ASCII_FIX] Replaced all non-ASCII characters in main.py")
print("[ASCII_FIX] Characters replaced: 🔒🚫✅? -> -  [OK]")
