"""Helper script to run main.py with admin elevation if needed."""
import ctypes
import sys
import os
import subprocess

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

if not is_admin():
    # Re-run this script as admin
    python_exe = sys.executable
    script = os.path.join(os.path.dirname(__file__), 'main.py')
    
    # Use ctypes to elevate
    ctypes.windll.shell32.ShellExecuteW(None, "runas", python_exe, f'"{script}"', None, 1)
    sys.exit(0)
else:
    # Already admin, run main.py
    os.chdir(os.path.dirname(__file__))
    exec(open('main.py').read())
