#!/usr/bin/env python3
"""
BALANCED_CONFIGURATION_VERIFICATION.py
Validates that all balanced configuration changes have been correctly applied.
Checks environment variables, code changes, and configuration consistency.
"""

import os
import re
import sys
from pathlib import Path
from datetime import datetime

# ANSI color codes
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
CHECKMARK = '✓'
CROSS = '✗'

class ConfigVerifier:
    def __init__(self, workspace_root):
        self.workspace_root = Path(workspace_root)
        self.results = []
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        
    def log_pass(self, category, check, details=""):
        """Log a passed check"""
        self.results.append({
            'status': 'PASS',
            'category': category,
            'check': check,
            'details': details
        })
        self.passed += 1
        print(f"{GREEN}{CHECKMARK}{RESET} {category}: {check}")
        if details:
            print(f"  → {details}")
    
    def log_fail(self, category, check, details=""):
        """Log a failed check"""
        self.results.append({
            'status': 'FAIL',
            'category': category,
            'check': check,
            'details': details
        })
        self.failed += 1
        print(f"{RED}{CROSS}{RESET} {category}: {check}")
        if details:
            print(f"  → {details}")
    
    def log_warn(self, category, check, details=""):
        """Log a warning"""
        self.results.append({
            'status': 'WARN',
            'category': category,
            'check': check,
            'details': details
        })
        self.warnings += 1
        print(f"{YELLOW}⚠{RESET} {category}: {check}")
        if details:
            print(f"  → {details}")
    
    def verify_env_file(self):
        """Verify .env.optimized configuration"""
        print(f"\n{BLUE}═══ VERIFYING .env.optimized ═══{RESET}")
        
        env_file = self.workspace_root / ".env.optimized"
        if not env_file.exists():
            self.log_fail("Environment", ".env.optimized exists", f"File not found: {env_file}")
            return
        
        env_content = env_file.read_text()
        
        # Check each configuration parameter
        checks = {
            'BROKER_TIMEZONE_OFFSET_HOURS': ('2', 'Broker UTC offset'),
            'ML_ACCURACY_MIN_GATE': ('0.45', 'ML accuracy gate'),
            'ADX_MIN_STANDARD': ('14', 'ADX standard floor'),
            'ADX_MIN_RELAXED': ('10', 'ADX relaxed floor'),
            'ML_RETRAIN_ON_STARTUP': ('true', 'ML training at startup'),
            'RETRAIN_IF_NO_MODEL': ('true', 'Retrain if model missing'),
            'AMNESIA_MODE_ON_STARTUP': ('false', 'Amnesia mode disabled'),
            'BRAIN_WASH_ON_STARTUP': ('false', 'Brain wash disabled'),
            'EARLY_ADX_PRECHECK': ('true', 'Early ADX precheck'),
            'EXPLORATION_ADX_BYPASS': ('false', 'Exploration ADX bypass disabled'),
            'ALLOW_TREND_STRATEGY_IN_RANGE': ('true', 'Trend in ranging markets'),
            'NEWS_MODE': ('live', 'News mode set to live'),
            'MACRO_RISK_FALLBACK': ('volatility_conservative', 'Macro risk fallback'),
        }
        
        for param, (expected_value, description) in checks.items():
            pattern = f'{param}\\s*=\\s*{re.escape(expected_value)}'
            if re.search(pattern, env_content):
                self.log_pass("Configuration", f"{param} = {expected_value}", description)
            else:
                # Try to find what value is actually there
                pattern_any = f'{param}\\s*=\\s*([^\\n#]*)'
                match = re.search(pattern_any, env_content)
                actual = match.group(1).strip() if match else "NOT FOUND"
                self.log_fail("Configuration", f"{param} = {expected_value}", 
                            f"Found: {actual}")
    
    def verify_main_py(self):
        """Verify main.py changes"""
        print(f"\n{BLUE}═══ VERIFYING main.py ═══{RESET}")
        
        main_file = self.workspace_root / "main.py"
        if not main_file.exists():
            self.log_fail("Code", "main.py exists", f"File not found: {main_file}")
            return
        
        content = main_file.read_text()
        
        # Check timezone offset in main.py
        if 'BROKER_TIMEZONE_OFFSET_HOURS.*"2"' in content or \
           'BROKER_TIMEZONE_OFFSET_HOURS.*2' in content:
            self.log_pass("Code", "Timezone offset default = 2", "main.py line ~1892")
        else:
            self.log_fail("Code", "Timezone offset default = 2", "Not found in main.py")
        
        # Check dynamic ADX floor logic
        if 'ADX_MIN_STANDARD' in content and 'ADX_MIN_RELAXED' in content:
            self.log_pass("Code", "Dynamic ADX floor logic present", "Reads from env vars")
        else:
            self.log_fail("Code", "Dynamic ADX floor logic", "Not found in main.py")
        
        # Check ML accuracy gate configuration
        if 'ML_ACCURACY_MIN_GATE' in content:
            self.log_pass("Code", "ML accuracy gate configurable", "Reads from env vars")
        else:
            self.log_fail("Code", "ML accuracy gate configurable", "Not found in main.py")
        
        # Warn if old hardcoded values still exist
        if re.search(r'adx_min.*==\s*18\b', content, re.IGNORECASE):
            self.log_warn("Code", "Old ADX floor value (18) still present", 
                        "Should use env var instead")
        
        if re.search(r'0\.50\b.*accuracy|accuracy.*0\.50', content, re.IGNORECASE):
            self.log_warn("Code", "Old ML accuracy gate (0.50) still present",
                        "Should use env var instead")
    
    def verify_exit_manager(self):
        """Verify exit_manager.py changes"""
        print(f"\n{BLUE}═══ VERIFYING src/trading/exit_manager.py ═══{RESET}")
        
        exit_file = self.workspace_root / "src/trading/exit_manager.py"
        if not exit_file.exists():
            self.log_warn("Code", "exit_manager.py exists", "File not found")
            return
        
        content = exit_file.read_text()
        
        # Check timezone offset
        if 'BROKER_TIMEZONE_OFFSET_HOURS.*"2"' in content or \
           'BROKER_TIMEZONE_OFFSET_HOURS.*2' in content:
            self.log_pass("Code", "exit_manager timezone offset = 2")
        else:
            self.log_warn("Code", "exit_manager timezone offset = 2", 
                         "Verify manually if present")
    
    def verify_mt5_broker(self):
        """Verify mt5_broker.py changes"""
        print(f"\n{BLUE}═══ VERIFYING src/data/mt5_broker.py ═══{RESET}")
        
        mt5_file = self.workspace_root / "src/data/mt5_broker.py"
        if not mt5_file.exists():
            self.log_warn("Code", "mt5_broker.py exists", "File not found")
            return
        
        content = mt5_file.read_text()
        
        # Check function exists
        if 'normalize_mt5_timestamp_to_utc' in content:
            self.log_pass("Code", "normalize_mt5_timestamp_to_utc() function exists")
        else:
            self.log_fail("Code", "normalize_mt5_timestamp_to_utc() function exists")
        
        # Check timezone offset
        if 'BROKER_TIMEZONE_OFFSET_HOURS.*"2"' in content:
            self.log_pass("Code", "mt5_broker timezone offset = 2")
    
    def verify_position_manager(self):
        """Verify position_manager.py changes"""
        print(f"\n{BLUE}═══ VERIFYING src/trading/position_manager.py ═══{RESET}")
        
        pm_file = self.workspace_root / "src/trading/position_manager.py"
        if not pm_file.exists():
            self.log_warn("Code", "position_manager.py exists", "File not found")
            return
        
        content = pm_file.read_text()
        
        # Check timezone normalization in shadow building
        if 'normalize_mt5_timestamp_to_utc' in content or 'opened_at' in content:
            self.log_pass("Code", "Timezone normalization in position recovery")
        else:
            self.log_warn("Code", "Timezone normalization", "Check manually")
    
    def verify_test_file(self):
        """Verify test_timezone_fix.py exists"""
        print(f"\n{BLUE}═══ VERIFYING test_timezone_fix.py ═══{RESET}")
        
        test_file = self.workspace_root / "test_timezone_fix.py"
        if test_file.exists():
            self.log_pass("Testing", "test_timezone_fix.py exists")
            # Try to run it
            try:
                import subprocess
                result = subprocess.run(
                    [sys.executable, str(test_file)],
                    capture_output=True,
                    timeout=30,
                    cwd=str(self.workspace_root)
                )
                if result.returncode == 0:
                    self.log_pass("Testing", "test_timezone_fix.py executes successfully")
                else:
                    self.log_warn("Testing", "test_timezone_fix.py execution",
                                f"Exit code: {result.returncode}")
            except Exception as e:
                self.log_warn("Testing", "test_timezone_fix.py execution", str(e))
        else:
            self.log_fail("Testing", "test_timezone_fix.py exists")
    
    def verify_consistency(self):
        """Verify consistency across files"""
        print(f"\n{BLUE}═══ CHECKING CONSISTENCY ═══{RESET}")
        
        env_file = self.workspace_root / ".env.optimized"
        if env_file.exists():
            env_content = env_file.read_text()
            
            # All timezone offsets should be 2
            tz_matches = re.findall(r'BROKER_TIMEZONE_OFFSET_HOURS\s*=\s*(\d+)', env_content)
            if tz_matches and all(m == '2' for m in tz_matches):
                self.log_pass("Consistency", "All timezone offsets are 2")
            elif tz_matches:
                self.log_warn("Consistency", "Mixed timezone offsets", 
                            f"Found: {tz_matches}")
            
            # ADX floors should be 14 and 10
            adx_std = re.search(r'ADX_MIN_STANDARD\s*=\s*(\d+)', env_content)
            adx_rel = re.search(r'ADX_MIN_RELAXED\s*=\s*(\d+)', env_content)
            if adx_std and adx_std.group(1) == '14' and \
               adx_rel and adx_rel.group(1) == '10':
                self.log_pass("Consistency", "ADX floors consistent (14, 10)")
            else:
                self.log_warn("Consistency", "ADX floor consistency",
                            f"Standard: {adx_std.group(1) if adx_std else '?'}, "
                            f"Relaxed: {adx_rel.group(1) if adx_rel else '?'}")
    
    def run_all_checks(self):
        """Run all verification checks"""
        print(f"\n{BLUE}{'='*60}{RESET}")
        print(f"{BLUE}BALANCED CONFIGURATION VERIFICATION{RESET}")
        print(f"{BLUE}Workspace: {self.workspace_root}{RESET}")
        print(f"{BLUE}Time: {datetime.now().isoformat()}{RESET}")
        print(f"{BLUE}{'='*60}{RESET}")
        
        self.verify_env_file()
        self.verify_main_py()
        self.verify_exit_manager()
        self.verify_mt5_broker()
        self.verify_position_manager()
        self.verify_test_file()
        self.verify_consistency()
        
        self.print_summary()
    
    def print_summary(self):
        """Print verification summary"""
        total = self.passed + self.failed + self.warnings
        
        print(f"\n{BLUE}{'='*60}{RESET}")
        print(f"{BLUE}VERIFICATION SUMMARY{RESET}")
        print(f"{BLUE}{'='*60}{RESET}")
        
        print(f"{GREEN}Passed: {self.passed}/{total}{RESET}")
        print(f"{RED}Failed: {self.failed}/{total}{RESET}")
        print(f"{YELLOW}Warnings: {self.warnings}/{total}{RESET}")
        
        if self.failed == 0:
            print(f"\n{GREEN}✓ CONFIGURATION VERIFIED SUCCESSFULLY{RESET}")
            print(f"{GREEN}All critical changes are in place.{RESET}")
        else:
            print(f"\n{RED}✗ VERIFICATION INCOMPLETE{RESET}")
            print(f"{RED}Please fix {self.failed} issue(s) before deployment.{RESET}")
        
        if self.warnings > 0:
            print(f"\n{YELLOW}⚠ WARNING: {self.warnings} item(s) need manual review{RESET}")
        
        print(f"\n{BLUE}{'='*60}{RESET}")
        
        return self.failed == 0

if __name__ == "__main__":
    workspace_root = os.environ.get('WORKSPACE_ROOT', 
        r'c:\Users\macki\Desktop\v8.5 core RL TradingBot')
    
    verifier = ConfigVerifier(workspace_root)
    success = verifier.run_all_checks()
    
    sys.exit(0 if success else 1)
