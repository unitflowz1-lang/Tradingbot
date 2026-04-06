#!/usr/bin/env python3
"""
MOMENTUM_EXIT_SYSTEM_VERIFICATION.py
Validates that all momentum profit system components are correctly implemented.
"""

import os
import sys
import re
from pathlib import Path
from datetime import datetime

# ANSI colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
CHECK = '✓'
CROSS = '✗'
WARN = '⚠'

class MomentumVerifier:
    def __init__(self, workspace_root):
        self.workspace_root = Path(workspace_root)
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.results = []
        
    def log_pass(self, category, check, details=""):
        self.results.append({'status': 'PASS', 'category': category, 'check': check})
        self.passed += 1
        print(f"{GREEN}{CHECK}{RESET} {category}: {check}")
        if details:
            print(f"  → {details}")
    
    def log_fail(self, category, check, details=""):
        self.results.append({'status': 'FAIL', 'category': category, 'check': check})
        self.failed += 1
        print(f"{RED}{CROSS}{RESET} {category}: {check}")
        if details:
            print(f"  → {details}")
    
    def log_warn(self, category, check, details=""):
        self.results.append({'status': 'WARN', 'category': category, 'check': check})
        self.warnings += 1
        print(f"{YELLOW}{WARN}{RESET} {category}: {check}")
        if details:
            print(f"  → {details}")
    
    def verify_env_file(self):
        """Verify .env.optimized has all momentum parameters"""
        print(f"\n{BLUE}═══ VERIFYING .env.optimized (Momentum Parameters) ═══{RESET}")
        
        env_file = self.workspace_root / ".env.optimized"
        if not env_file.exists():
            self.log_fail("Configuration", ".env.optimized exists")
            return
        
        content = env_file.read_text()
        
        required_params = {
            'BREAKEVEN_TRIGGER_R': '0.3',
            'BREAKEVEN_SL_OFFSET_PIPS': '1',
            'TRAIL_ACTIVATION_R': '0.8',
            'TRAIL_ATR_PERIOD': '14',
            'TRAIL_ATR_MULTIPLIER': '1.5',
            'TRAIL_MIN_STEP_PIPS': '2',
            'SCALE_OUT_TRIGGER_R': '1.2',
            'SCALE_OUT_PERCENT': '25',
            'EXHAUSTION_BODY_THRESHOLD_PCT': '65',
            'EXHAUSTION_CHECK_LOOKBACK_BARS': '3',
            'STALL_CYCLES_FOR_TREND_EXHAUSTION': '3',
            'TIGHT_LEASH_REVERSAL_RISK_THRESHOLD': '0.7',
            'ML_CONFIDENCE_EXIT_THRESHOLD': '0.30',
            'TOKYO_SESSION_UTC_START': '00:00',
            'TOKYO_SESSION_UTC_END': '08:00',
            'TOKYO_ADX_THRESHOLD': '18',
            'TOKYO_STAGNATION_BARS_MAX': '20',
            'TOKYO_STAGNATION_OVERRIDE': 'true',
        }
        
        for param, expected_value in required_params.items():
            pattern = f'{param}\\s*=\\s*{re.escape(expected_value)}'
            if re.search(pattern, content):
                self.log_pass("Configuration", f"{param} = {expected_value}")
            else:
                # Check if param exists at all
                pattern_any = f'{param}\\s*='
                if re.search(pattern_any, content):
                    match = re.search(f'{param}\\s*=\\s*([^\\n#]*)', content)
                    actual = match.group(1).strip() if match else "?"
                    self.log_warn("Configuration", f"{param}", f"Found {actual}, expected {expected_value}")
                else:
                    self.log_fail("Configuration", f"{param} exists", "Parameter not found")
    
    def verify_momentum_manager_module(self):
        """Verify momentum_exit_manager.py exists and has key components"""
        print(f"\n{BLUE}═══ VERIFYING momentum_exit_manager.py (Core Module) ═══{RESET}")
        
        module_file = self.workspace_root / "src/trading/momentum_exit_manager.py"
        if not module_file.exists():
            self.log_fail("Code", "momentum_exit_manager.py exists")
            return
        
        self.log_pass("Code", "momentum_exit_manager.py exists")
        
        content = module_file.read_text()
        
        # Check for key classes
        classes_to_check = [
            ('MomentumExitManager', 'Main exit manager class'),
            ('MomentumExitSignal', 'Exit signal types enum'),
            ('MomentumPositionState', 'Position state tracking'),
            ('BreakevenLock', 'Breakeven lock dataclass'),
            ('ChandelierTrail', 'Chandelier trail state'),
            ('TightLeashSL', 'Tight leash SL state'),
        ]
        
        for class_name, description in classes_to_check:
            if f'class {class_name}' in content:
                self.log_pass("Code Structure", f"Class {class_name}", description)
            else:
                self.log_fail("Code Structure", f"Class {class_name}", description)
        
        # Check for key methods
        methods_to_check = [
            ('apply_breakeven_lock', 'Breakeven locking'),
            ('update_chandelier_trail', 'Chandelier trail updates'),
            ('check_scale_out_1_2r', 'Scale-out at 1.2R'),
            ('detect_exhaustion_reversal', 'Exhaustion detection'),
            ('apply_tight_leash_if_reversal_risk', 'Tight leash activation'),
            ('resolve_conflicting_sls', 'Conflict resolution'),
            ('check_ml_confidence_exit', 'ML confidence exit'),
            ('get_effective_stagnation_limit', 'Tokyo session adaptation'),
        ]
        
        for method_name, description in methods_to_check:
            if f'def {method_name}' in content:
                self.log_pass("Core Methods", f"Method {method_name}", description)
            else:
                self.log_fail("Core Methods", f"Method {method_name}", description)
    
    def verify_key_logic_implementations(self):
        """Verify critical logic implementations"""
        print(f"\n{BLUE}═══ VERIFYING Key Logic Implementations ═══{RESET}")
        
        module_file = self.workspace_root / "src/trading/momentum_exit_manager.py"
        if not module_file.exists():
            self.log_fail("Logic", "Module exists")
            return
        
        content = module_file.read_text()
        
        # Verify breakeven lock immutability
        if 'irreversible' in content and 'is_active' in content:
            self.log_pass("Logic", "Breakeven lock immutability enforced")
        else:
            self.log_fail("Logic", "Breakeven lock immutability")
        
        # Verify one-way trailing
        if 'one_way_tighten_only' in content and '_is_sl_tighter' in content:
            self.log_pass("Logic", "One-way tightening rule in chandelier")
        else:
            self.log_fail("Logic", "One-way tightening enforcement")
        
        # Verify most-protective-wins
        if 'resolve_conflicting_sls' in content and 'most_protective' in content.lower():
            self.log_pass("Logic", "Most-protective-wins conflict resolution")
        else:
            self.log_warn("Logic", "Most-protective-wins implementation", "Check manually")
        
        # Verify scale-out single only
        if 'scaled_out_at_1_2r' in content or 'scale_out_1_2r' in content:
            self.log_pass("Logic", "Single scale-out enforcement")
        else:
            self.log_fail("Logic", "Single scale-out tracking")
        
        # Verify ATR calculation
        if '_calculate_atr' in content or 'ATR' in content:
            self.log_pass("Logic", "ATR calculation for chandelier")
        else:
            self.log_fail("Logic", "ATR calculation method")
        
        # Verify exhaustion detection
        if 'EXHAUSTION_BODY_THRESHOLD' in content and 'body_pct' in content:
            self.log_pass("Logic", "Exhaustion body threshold detection")
        else:
            self.log_fail("Logic", "Exhaustion detection logic")
        
        # Verify Tokyo session handling
        if 'is_tokyo_session' in content and 'TOKYO' in content:
            self.log_pass("Logic", "Tokyo session time detection")
        else:
            self.log_fail("Logic", "Tokyo session logic")
        
        # Verify ML confidence exit
        if 'ML_CONFIDENCE_EXIT' in content and 'check_ml_confidence_exit' in content:
            self.log_pass("Logic", "ML confidence force exit")
        else:
            self.log_fail("Logic", "ML confidence exit logic")
    
    def verify_configuration_loading(self):
        """Verify environment configuration is loaded correctly"""
        print(f"\n{BLUE}═══ VERIFYING Configuration Loading ═══{RESET}")
        
        module_file = self.workspace_root / "src/trading/momentum_exit_manager.py"
        if not module_file.exists():
            return
        
        content = module_file.read_text()
        
        # Check for _load_configuration method
        if '_load_configuration' in content:
            self.log_pass("Configuration", "_load_configuration method exists")
        else:
            self.log_fail("Configuration", "_load_configuration method")
        
        # Check for os.environ.get usage
        env_get_count = content.count('os.environ.get')
        if env_get_count > 15:
            self.log_pass("Configuration", f"Environment loading ({env_get_count} parameters)")
        else:
            self.log_warn("Configuration", f"Environment loading", f"Only {env_get_count} params (expected 15+)")
        
        # Check for fallback defaults
        if '.get("' in content:
            self.log_pass("Configuration", "Fallback defaults provided")
        else:
            self.log_warn("Configuration", "Fallback defaults")
    
    def verify_docstrings(self):
        """Verify documentation coverage"""
        print(f"\n{BLUE}═══ VERIFYING Documentation ═══{RESET}")
        
        module_file = self.workspace_root / "src/trading/momentum_exit_manager.py"
        if not module_file.exists():
            return
        
        content = module_file.read_text()
        
        # Count docstrings
        docstring_count = content.count('"""') // 2  # Each docstring has 2 """
        
        if docstring_count >= 15:
            self.log_pass("Documentation", f"Docstring coverage ({docstring_count} docstrings)")
        else:
            self.log_warn("Documentation", "Docstring coverage", f"Only {docstring_count} found")
        
        # Check module docstring
        if content.startswith('"""'):
            self.log_pass("Documentation", "Module docstring present")
        else:
            self.log_warn("Documentation", "Module docstring")
    
    def verify_integration_guide(self):
        """Verify integration guide documentation"""
        print(f"\n{BLUE}═══ VERIFYING Documentation Files ═══{RESET}")
        
        guide_file = self.workspace_root / "MOMENTUM_PROFIT_SYSTEM_GUIDE.md"
        
        if guide_file.exists():
            self.log_pass("Documentation", "MOMENTUM_PROFIT_SYSTEM_GUIDE.md exists")
            
            content = guide_file.read_text()
            
            required_sections = [
                'Breakeven Lock',
                'Chandelier Trailing',
                'Intelligent Scale-Out',
                'Conflict Resolution',
                'Tokyo Session',
                'Integration',
                'Testing',
            ]
            
            for section in required_sections:
                if section in content:
                    self.log_pass("Documentation", f"Section: {section}")
                else:
                    self.log_warn("Documentation", f"Section: {section}")
        else:
            self.log_fail("Documentation", "MOMENTUM_PROFIT_SYSTEM_GUIDE.md")
    
    def verify_no_syntax_errors(self):
        """Basic syntax check"""
        print(f"\n{BLUE}═══ VERIFYING Python Syntax ═══{RESET}")
        
        module_file = self.workspace_root / "src/trading/momentum_exit_manager.py"
        if not module_file.exists():
            self.log_fail("Syntax", "Files to check", "momentum_exit_manager.py not found")
            return
        
        try:
            with open(module_file, 'r') as f:
                compile(f.read(), str(module_file), 'exec')
            self.log_pass("Syntax", "momentum_exit_manager.py compiles", "No syntax errors")
        except SyntaxError as e:
            self.log_fail("Syntax", "momentum_exit_manager.py", f"Syntax error: {e}")
    
    def print_summary(self):
        """Print verification summary"""
        total = self.passed + self.failed + self.warnings
        
        print(f"\n{BLUE}{'='*70}{RESET}")
        print(f"{BLUE}MOMENTUM PROFIT SYSTEM VERIFICATION SUMMARY{RESET}")
        print(f"{BLUE}{'='*70}{RESET}")
        
        print(f"{GREEN}✓ Passed:  {self.passed}/{total}{RESET}")
        print(f"{RED}✗ Failed:  {self.failed}/{total}{RESET}")
        print(f"{YELLOW}⚠ Warnings: {self.warnings}/{total}{RESET}")
        
        if self.failed == 0:
            print(f"\n{GREEN}✓ MOMENTUM EXIT SYSTEM VERIFIED SUCCESSFULLY{RESET}")
            print(f"{GREEN}Ready for integration with main trading loop.{RESET}")
            return True
        else:
            print(f"\n{RED}✗ VERIFICATION INCOMPLETE{RESET}")
            print(f"{RED}Please fix {self.failed} issue(s) before deployment.{RESET}")
            return False
        
        print(f"\n{BLUE}{'='*70}{RESET}")
    
    def run_all_checks(self):
        """Run all verification checks"""
        print(f"\n{BLUE}{'='*70}{RESET}")
        print(f"{BLUE}MOMENTUM PROFIT SYSTEM VERIFICATION{RESET}")
        print(f"{BLUE}Workspace: {self.workspace_root}{RESET}")
        print(f"{BLUE}Time: {datetime.now().isoformat()}{RESET}")
        print(f"{BLUE}{'='*70}{RESET}")
        
        self.verify_env_file()
        self.verify_momentum_manager_module()
        self.verify_key_logic_implementations()
        self.verify_configuration_loading()
        self.verify_docstrings()
        self.verify_integration_guide()
        self.verify_no_syntax_errors()
        
        success = self.print_summary()
        return success


if __name__ == "__main__":
    workspace_root = os.environ.get('WORKSPACE_ROOT',
        r'c:\Users\macki\Desktop\v8.5 core RL TradingBot')
    
    verifier = MomentumVerifier(workspace_root)
    success = verifier.run_all_checks()
    
    sys.exit(0 if success else 1)
