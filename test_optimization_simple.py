#!/usr/bin/env python3
"""
Simple Optimization Test - No Signal Generation Issues
Tests basic backtest functionality
"""
import subprocess
import sys
from pathlib import Path
import json

def run_single_backtest():
    """Run a single backtest and check metrics"""
    print("\n[TEST] Running single backtest...")
    
    result = subprocess.run(
        [sys.executable, "run_backtest.py"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(Path.cwd())
    )
    
    output = result.stdout + result.stderr
    
    # Print last 50 lines to see what happened
    lines = output.split('\n')
    print("\n".join(lines[-50:]))
    
    # Check for metrics
    if "Trades Executed:" in output:
        print("\n[OK] Backtest completed with metrics")
    else:
        print("\n[ERROR] No metrics found in output")
        
    return output

if __name__ == "__main__":
    output = run_single_backtest()
