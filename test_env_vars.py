#!/usr/bin/env python
"""Test if environment variables from ACTIVATE_OPTION_D.ps1 are being received by Python"""
import os
import sys

print("\n=== ENVIRONMENT VARIABLE DIAGNOSTIC ===\n")

env_vars_to_check = [
    "STRICT_FRIDAY_LOCK",
    "FRIDAY_CUTOFF_HOUR",
    "OVERRIDE_ROLLOVER_PAUSE",
    "ML_ACCURACY_MIN_GATE",
    "SIGNAL_QUALITY_MINIMUM",
    "AGGRESSIVE_ENGAGEMENT",
    "PERMIT_INSTITUTIONAL_SWEEP_OVERRIDES",
    "ALLOW_FRIDAY_LATE_SESSION",
]

print("OPTION D DEPLOYMENT VARIABLES:")
for var in env_vars_to_check:
    value = os.environ.get(var, "[NOT SET]")
    print(f"  {var} = {value}")

print("\nALL ENVIRONMENT VARIABLES COUNT:", len(os.environ))
print("\nVariables starting with 'ML':", [f"{k}={v}" for k, v in os.environ.items() if k.startswith("ML")])
print("Variables starting with 'FRIDAY':", [f"{k}={v}" for k, v in os.environ.items() if k.startswith("FRIDAY")])
print("Variables starting with 'STRICT':", [f"{k}={v}" for k, v in os.environ.items() if k.startswith("STRICT")])
print("Variables starting with 'OVERRIDE':", [f"{k}={v}" for k, v in os.environ.items() if k.startswith("OVERRIDE")])

print("\n" + "="*50)
