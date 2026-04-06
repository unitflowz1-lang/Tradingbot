#!/usr/bin/env python3
"""
Verification script to check for missing implementations and incomplete code
"""
import sys
import ast
import os
from pathlib import Path


def check_python_syntax(file_path):
    """Check if Python file has valid syntax"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            ast.parse(f.read())
        return True, None
    except SyntaxError as e:
        return False, str(e)


def find_incomplete_methods(file_path):
    """Find methods with only 'pass' or incomplete implementations"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read())
        
        issues = []
        
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Check if function body is only pass
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    issues.append(f"  - {node.name}() is empty (only 'pass')")
                elif len(node.body) == 0:
                    issues.append(f"  - {node.name}() has no body")
        
        return issues
    except Exception as e:
        return [f"  - Error parsing: {str(e)}"]


def check_critical_files():
    """Check critical source files"""
    critical_files = [
        'src/trading/execution_engine.py',
        'src/trading/position_manager.py',
        'src/data/mt5_broker.py',
        'src/strategies/trend_strategy.py',
        'src/risk/risk_calculator.py',
        'src/risk/sl_tp_calculator.py',
        'main.py'
    ]
    
    print("=" * 70)
    print("CODEBASE COMPLETENESS VERIFICATION")
    print("=" * 70)
    
    all_good = True
    
    for file_path in critical_files:
        full_path = Path(file_path)
        if not full_path.exists():
            print(f"\n❌ {file_path}")
            print(f"   FILE NOT FOUND")
            all_good = False
            continue
        
        # Check syntax
        syntax_ok, syntax_error = check_python_syntax(file_path)
        
        # Check for incomplete methods
        incomplete = find_incomplete_methods(file_path)
        
        status = "✅" if (syntax_ok and not incomplete) else "❌"
        print(f"\n{status} {file_path}")
        
        if not syntax_ok:
            print(f"   SYNTAX ERROR: {syntax_error}")
            all_good = False
        
        if incomplete:
            print(f"   INCOMPLETE IMPLEMENTATIONS:")
            for issue in incomplete:
                print(issue)
            all_good = False
        
        if syntax_ok and not incomplete:
            # Count lines
            with open(file_path, encoding='utf-8', errors='ignore') as f:
                lines = len(f.readlines())
            print(f"   ✓ Syntax OK | {lines} lines | Complete")
    
    print("\n" + "=" * 70)
    if all_good:
        print("✅ ALL CHECKS PASSED - Code appears to be complete!")
    else:
        print("⚠️  Some files have issues - see above for details")
    print("=" * 70)
    
    return all_good


def check_imports():
    """Verify that key imports can be resolved"""
    print("\nChecking imports...")
    
    imports_to_check = [
        ("src.config", "ConfigManager"),
        ("src.data.mt5_broker", "create_mt5_broker"),
        ("src.trading.execution_engine", "ExecutionEngine"),
        ("src.trading.position_manager", "PositionManager"),
        ("src.strategies.trend_strategy", "SimpleTrendStrategy"),
        ("src.risk.risk_calculator", "RiskCalculator"),
        ("src.risk.sl_tp_calculator", "StopLossTakeProfitCalculator"),
        ("src.health_check", "HealthChecker"),
    ]
    
    all_ok = True
    for module, class_name in imports_to_check:
        try:
            mod = __import__(module, fromlist=[class_name])
            getattr(mod, class_name)
            print(f"  ✓ {module}.{class_name}")
        except (ImportError, AttributeError) as e:
            print(f"  ❌ {module}.{class_name}: {e}")
            all_ok = False
    
    return all_ok


if __name__ == "__main__":
    os.chdir("c:\\Users\\macki\\Desktop\\TradingBot")
    
    # Run checks
    files_ok = check_critical_files()
    
    # Note: Import check requires proper environment setup, so we'll skip it
    # imports_ok = check_imports()
    
    sys.exit(0 if files_ok else 1)
