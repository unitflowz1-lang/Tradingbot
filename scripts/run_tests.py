#!/usr/bin/env python3
"""
Comprehensive Test Runner for AI Forex Trading Bot

This script runs all types of tests including:
1. Unit tests
2. Integration tests
3. Production integration tests
4. Performance tests
5. Security tests
6. Configuration validation tests
"""

import os
import sys
import subprocess
import argparse
import time
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone


class TestRunner:
    """Comprehensive test runner for the trading bot"""
    
    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.test_results = {}
        self.start_time = None
        self.end_time = None
    
    def run_command(self, command: List[str], description: str) -> Dict[str, Any]:
        """Run a command and return results"""
        print(f"\n{'='*60}")
        print(f"Running: {description}")
        print(f"Command: {' '.join(command)}")
        print(f"{'='*60}")
        
        start_time = time.time()
        
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=self.project_root
            )
            
            end_time = time.time()
            duration = end_time - start_time
            
            success = result.returncode == 0
            
            print(f"Duration: {duration:.2f} seconds")
            print(f"Exit Code: {result.returncode}")
            
            if success:
                print("✅ PASSED")
            else:
                print("❌ FAILED")
                print(f"Error Output:\n{result.stderr}")
            
            return {
                "success": success,
                "duration": duration,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": command
            }
            
        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            
            print(f"❌ ERROR: {e}")
            
            return {
                "success": False,
                "duration": duration,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "command": command
            }
    
    def run_unit_tests(self) -> Dict[str, Any]:
        """Run all unit tests"""
        test_files = [
            "test_*.py"
        ]
        
        command = [
            sys.executable, "-m", "pytest",
            "-v",
            "--tb=short",
            "--asyncio-mode=auto",
            "--maxfail=10"
        ] + test_files
        
        return self.run_command(command, "Unit Tests")
    
    def run_integration_tests(self) -> Dict[str, Any]:
        """Run integration tests"""
        integration_tests = [
            "test_integration_e2e.py",
            "test_integration_stress.py"
        ]
        
        command = [
            sys.executable, "-m", "pytest",
            "-v",
            "--tb=short",
            "--asyncio-mode=auto",
            "--maxfail=5"
        ] + integration_tests
        
        return self.run_command(command, "Integration Tests")
    
    def run_production_tests(self) -> Dict[str, Any]:
        """Run production integration tests"""
        command = [
            sys.executable, "-m", "pytest",
            "test_production_integration.py",
            "-v",
            "--tb=short",
            "--asyncio-mode=auto",
            "--maxfail=3"
        ]
        
        return self.run_command(command, "Production Integration Tests")
    
    def run_performance_tests(self) -> Dict[str, Any]:
        """Run performance tests"""
        # Create a simple performance test
        performance_test = """
import asyncio
import time
from src.analysis.signal_combiner import SignalCombiner
from src.models import SentimentResult, TechnicalSignal
from datetime import datetime, timezone

async def test_signal_processing_performance():
    signal_combiner = SignalCombiner()
    
    # Create test data
    sentiment = SentimentResult(
        symbol="EUR/USD",
        sentiment_score=0.6,
        confidence=0.8,
        reasoning="Test sentiment",
        sources=["Test"],
        timestamp=datetime.now(timezone.utc)
    )
    
    technical = TechnicalSignal(
        symbol="EUR/USD",
        signal_type="BUY",
        strength=0.7,
        indicators={"rsi": 65.0},
        timestamp=datetime.now(timezone.utc)
    )
    
    # Test processing speed
    start_time = time.time()
    
    for _ in range(1000):
        signal_combiner.combine_signals(sentiment, [technical], 1.0867, "EUR/USD")
    
    end_time = time.time()
    duration = end_time - start_time
    
    print(f"Processed 1000 signals in {duration:.2f} seconds")
    print(f"Average time per signal: {(duration/1000)*1000:.2f} ms")
    
    # Performance assertions
    assert duration < 10.0, f"Performance test failed: {duration:.2f}s > 10.0s"
    assert (duration/1000)*1000 < 10.0, f"Average time too high: {(duration/1000)*1000:.2f}ms"

if __name__ == "__main__":
    asyncio.run(test_signal_processing_performance())
"""
        
        # Write temporary test file
        test_file = self.project_root / "temp_performance_test.py"
        with open(test_file, "w") as f:
            f.write(performance_test)
        
        try:
            command = [sys.executable, "temp_performance_test.py"]
            result = self.run_command(command, "Performance Tests")
            
            # Clean up
            test_file.unlink()
            
            return result
            
        except Exception as e:
            # Clean up on error
            if test_file.exists():
                test_file.unlink()
            raise e
    
    def run_security_tests(self) -> Dict[str, Any]:
        """Run security tests"""
        security_test = """
import json
import os
from pathlib import Path

def test_security_configuration():
    # Test 1: Check for hardcoded secrets
    project_root = Path(__file__).parent
    
    # Check Python files for potential secrets
    python_files = list(project_root.rglob("*.py"))
    
    suspicious_patterns = [
        "password =",
        "api_key =",
        "secret =",
        "token ="
    ]
    
    issues = []
    
    for file_path in python_files:
        try:
            with open(file_path, 'r') as f:
                content = f.read()
                
            for pattern in suspicious_patterns:
                if pattern in content:
                    issues.append(f"Potential hardcoded secret in {file_path}: {pattern}")
        except Exception:
            pass
    
    # Test 2: Check configuration files
    config_files = [
        "config/config.dev.json",
        "config/config.staging.json"
    ]
    
    for config_file in config_files:
        config_path = project_root / config_file
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                
                # Check for empty or default values
                if config.get("llm", {}).get("api_key") == "":
                    issues.append(f"Empty API key in {config_file}")
                    
            except Exception as e:
                issues.append(f"Error reading {config_file}: {e}")
    
    # Test 3: Check environment variables
    required_env_vars = [
        "DB_PASSWORD",
        "LLM_API_KEY",
        "BROKER_API_KEY"
    ]
    
    for var in required_env_vars:
        if not os.getenv(var):
            issues.append(f"Missing environment variable: {var}")
    
    # Report results
    if issues:
        print("Security issues found:")
        for issue in issues:
            print(f"  - {issue}")
        assert False, f"Found {len(issues)} security issues"
    else:
        print("✅ No security issues found")

if __name__ == "__main__":
    test_security_configuration()
"""
        
        # Write temporary test file
        test_file = self.project_root / "temp_security_test.py"
        with open(test_file, "w") as f:
            f.write(security_test)
        
        try:
            command = [sys.executable, "temp_security_test.py"]
            result = self.run_command(command, "Security Tests")
            
            # Clean up
            test_file.unlink()
            
            return result
            
        except Exception as e:
            # Clean up on error
            if test_file.exists():
                test_file.unlink()
            raise e
    
    def run_configuration_validation(self) -> Dict[str, Any]:
        """Run configuration validation tests"""
        validation_test = """
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

try:
    from src.config import get_config_manager
    
    def test_configuration_validation():
        config_manager = get_config_manager()
        validation_summary = config_manager.get_validation_summary()
        
        print(f"Configuration validation result: {validation_summary}")
        
        if not validation_summary['valid']:
            print("Configuration validation failed:")
            for error in validation_summary['errors']:
                print(f"  - {error}")
            assert False, "Configuration validation failed"
        
        if validation_summary['warnings']:
            print("Configuration warnings:")
            for warning in validation_summary['warnings']:
                print(f"  - {warning}")
        
        print("✅ Configuration validation passed")
    
    test_configuration_validation()
    
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Configuration validation error: {e}")
    sys.exit(1)
"""
        
        # Write temporary test file
        test_file = self.project_root / "temp_config_test.py"
        with open(test_file, "w") as f:
            f.write(validation_test)
        
        try:
            command = [sys.executable, "temp_config_test.py"]
            result = self.run_command(command, "Configuration Validation")
            
            # Clean up
            test_file.unlink()
            
            return result
            
        except Exception as e:
            # Clean up on error
            if test_file.exists():
                test_file.unlink()
            raise e
    
    def run_code_quality_tests(self) -> Dict[str, Any]:
        """Run code quality checks"""
        quality_checks = []
        
        # Linting with flake8
        flake8_command = [
            sys.executable, "-m", "flake8",
            "src/",
            "--max-line-length=100",
            "--ignore=E501,W503"
        ]
        quality_checks.append(("Flake8 Linting", flake8_command))
        
        # Type checking with mypy
        mypy_command = [
            sys.executable, "-m", "mypy",
            "src/",
            "--ignore-missing-imports",
            "--no-strict-optional"
        ]
        quality_checks.append(("MyPy Type Checking", mypy_command))
        
        # Code formatting check with black
        black_command = [
            sys.executable, "-m", "black",
            "--check",
            "--diff",
            "src/"
        ]
        quality_checks.append(("Black Formatting Check", black_command))
        
        results = {}
        all_passed = True
        
        for description, command in quality_checks:
            result = self.run_command(command, description)
            results[description] = result
            if not result["success"]:
                all_passed = False
        
        return {
            "success": all_passed,
            "duration": sum(r["duration"] for r in results.values()),
            "exit_code": 0 if all_passed else 1,
            "stdout": "",
            "stderr": "",
            "command": ["code_quality_checks"],
            "sub_results": results
        }
    
    def run_all_tests(self, test_types: List[str]) -> Dict[str, Any]:
        """Run all specified test types"""
        self.start_time = time.time()
        
        test_functions = {
            "unit": self.run_unit_tests,
            "integration": self.run_integration_tests,
            "production": self.run_production_tests,
            "performance": self.run_performance_tests,
            "security": self.run_security_tests,
            "config": self.run_configuration_validation,
            "quality": self.run_code_quality_tests
        }
        
        results = {}
        
        for test_type in test_types:
            if test_type in test_functions:
                results[test_type] = test_functions[test_type]()
            else:
                print(f"❌ Unknown test type: {test_type}")
                results[test_type] = {
                    "success": False,
                    "duration": 0,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Unknown test type: {test_type}",
                    "command": []
                }
        
        self.end_time = time.time()
        self.test_results = results
        
        return results
    
    def generate_report(self) -> str:
        """Generate a comprehensive test report"""
        if not self.test_results:
            return "No test results available"
        
        total_duration = self.end_time - self.start_time if self.end_time else 0
        
        report = []
        report.append("=" * 80)
        report.append("AI FOREX TRADING BOT - TEST REPORT")
        report.append("=" * 80)
        report.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        report.append(f"Total Duration: {total_duration:.2f} seconds")
        report.append("")
        
        # Summary
        total_tests = len(self.test_results)
        passed_tests = sum(1 for r in self.test_results.values() if r["success"])
        failed_tests = total_tests - passed_tests
        
        report.append("SUMMARY")
        report.append("-" * 40)
        report.append(f"Total Test Suites: {total_tests}")
        report.append(f"Passed: {passed_tests}")
        report.append(f"Failed: {failed_tests}")
        report.append(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        report.append("")
        
        # Detailed Results
        report.append("DETAILED RESULTS")
        report.append("-" * 40)
        
        for test_type, result in self.test_results.items():
            status = "✅ PASSED" if result["success"] else "❌ FAILED"
            report.append(f"{test_type.upper():<15} {status}")
            report.append(f"{'Duration:':<15} {result['duration']:.2f}s")
            
            if not result["success"] and result["stderr"]:
                report.append(f"{'Error:':<15} {result['stderr'][:100]}...")
            report.append("")
        
        # Recommendations
        if failed_tests > 0:
            report.append("RECOMMENDATIONS")
            report.append("-" * 40)
            report.append("1. Review failed test outputs above")
            report.append("2. Fix any configuration issues")
            report.append("3. Address code quality issues")
            report.append("4. Re-run tests after fixes")
        else:
            report.append("🎉 ALL TESTS PASSED!")
            report.append("The system is ready for deployment.")
        
        report.append("=" * 80)
        
        return "\n".join(report)
    
    def save_report(self, filename: str = None) -> str:
        """Save test report to file"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"test_report_{timestamp}.txt"
        
        report = self.generate_report()
        
        report_path = self.project_root / "logs" / filename
        report_path.parent.mkdir(exist_ok=True)
        
        with open(report_path, "w") as f:
            f.write(report)
        
        return str(report_path)


def main():
    """Main test runner function"""
    parser = argparse.ArgumentParser(description="Run comprehensive tests for AI Forex Trading Bot")
    parser.add_argument("--types", nargs="+", 
                       choices=["unit", "integration", "production", "performance", "security", "config", "quality"],
                       default=["unit", "integration", "production"],
                       help="Types of tests to run")
    parser.add_argument("--report", action="store_true", help="Generate detailed test report")
    parser.add_argument("--save-report", metavar="FILENAME", help="Save report to file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    runner = TestRunner()
    
    print("🧪 AI Forex Trading Bot - Test Runner")
    print(f"Running tests: {', '.join(args.types)}")
    
    # Run tests
    results = runner.run_all_tests(args.types)
    
    # Generate and display report
    report = runner.generate_report()
    print("\n" + report)
    
    # Save report if requested
    if args.save_report or args.report:
        report_path = runner.save_report(args.save_report)
        print(f"\nReport saved to: {report_path}")
    
    # Exit with appropriate code
    total_tests = len(results)
    passed_tests = sum(1 for r in results.values() if r["success"])
    
    if passed_tests == total_tests:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n❌ {total_tests - passed_tests} test suite(s) failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main()) 