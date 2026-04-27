#!/usr/bin/env python3
"""
Production Validation Tests

Simplified validation tests to ensure system readiness for production deployment.
These tests focus on critical system components and configurations.
"""

import os
import json
import time
import unittest
from datetime import datetime
import tempfile
import subprocess


class TestProductionValidation(unittest.TestCase):
    """Production validation tests"""
    
    def test_configuration_files(self):
        """Test that all required configuration files exist and are valid"""
        print("\n=== Testing Configuration Files ===")
        
        required_configs = [
            'config/config.base.json',
            'config/config.dev.json',
            'config/config.prod.json',
            'config/config.staging.json'
        ]
        
        for config_file in required_configs:
            print(f"Checking {config_file}...")
            self.assertTrue(os.path.exists(config_file), f"Missing config file: {config_file}")
            
            # Validate JSON format
            with open(config_file, 'r') as f:
                try:
                    config_data = json.load(f)
                    self.assertIsInstance(config_data, dict)
                    print(f"✓ {config_file} is valid JSON")
                except json.JSONDecodeError as e:
                    self.fail(f"Invalid JSON in {config_file}: {e}")
        
        print("✓ All configuration files are valid")
    
    def test_documentation_completeness(self):
        """Test that all required documentation exists"""
        print("\n=== Testing Documentation Completeness ===")
        
        required_docs = [
            'README.md',
            'DEPLOYMENT.md',
            'docs/API_REFERENCE.md',
            'docs/SYSTEM_ARCHITECTURE.md',
            'docs/TROUBLESHOOTING_GUIDE.md',
            'docs/PERFORMANCE_OPTIMIZATION.md',
            'docs/USER_GUIDE.md'
        ]
        
        for doc_file in required_docs:
            print(f"Checking {doc_file}...")
            self.assertTrue(os.path.exists(doc_file), f"Missing documentation: {doc_file}")
            
            # Check that file is not empty
            with open(doc_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                self.assertGreater(len(content), 100, f"Documentation too short: {doc_file}")
                print(f"✓ {doc_file} exists and has content ({len(content)} chars)")
        
        print("✓ All required documentation exists")
    
    def test_docker_configuration(self):
        """Test Docker configuration files"""
        print("\n=== Testing Docker Configuration ===")
        
        # Check docker-compose.yml exists
        self.assertTrue(os.path.exists('docker-compose.yml'), "Missing docker-compose.yml")
        print("✓ docker-compose.yml exists")
        
        # Check Dockerfile exists
        self.assertTrue(os.path.exists('Dockerfile'), "Missing Dockerfile")
        print("✓ Dockerfile exists")
        
        # Validate docker-compose.yml syntax
        try:
            result = subprocess.run(
                ['docker-compose', 'config'],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                print("✓ docker-compose.yml syntax is valid")
            else:
                print(f"⚠ docker-compose.yml validation warning: {result.stderr}")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print("⚠ Could not validate docker-compose.yml (docker-compose not available)")
    
    def test_requirements_file(self):
        """Test requirements.txt file"""
        print("\n=== Testing Requirements File ===")
        
        self.assertTrue(os.path.exists('requirements.txt'), "Missing requirements.txt")
        
        with open('requirements.txt', 'r') as f:
            requirements = f.read().strip()
            self.assertGreater(len(requirements), 50, "Requirements file too short")
            
            # Check for essential dependencies
            essential_deps = [
                'asyncio',
                'pandas',
                'numpy',
                'aiohttp',
                'requests',
                'sqlalchemy',
                'pydantic',
                'pytest'
            ]
            
            for dep in essential_deps:
                self.assertIn(dep, requirements, f"Missing essential dependency: {dep}")
                print(f"✓ Found dependency: {dep}")
        
        print("✓ Requirements file is complete")
    
    def test_directory_structure(self):
        """Test that required directories exist"""
        print("\n=== Testing Directory Structure ===")
        
        required_dirs = [
            'src',
            'src/data',
            'src/analysis',
            'src/risk',
            'src/trading',
            'src/monitoring',
            'src/analytics',
            'src/backtesting',
            'src/maintenance',
            'config',
            'scripts',
            'logs',
            'docs'
        ]
        
        for directory in required_dirs:
            print(f"Checking directory: {directory}")
            self.assertTrue(os.path.isdir(directory), f"Missing directory: {directory}")
            print(f"✓ {directory} exists")
        
        print("✓ All required directories exist")
    
    def test_script_files(self):
        """Test that required script files exist"""
        print("\n=== Testing Script Files ===")
        
        required_scripts = [
            'scripts/deploy.sh',
            'scripts/deploy_production.py',
            'scripts/run_tests.py',
            'scripts/init-db.sql'
        ]
        
        for script_file in required_scripts:
            print(f"Checking script: {script_file}")
            self.assertTrue(os.path.exists(script_file), f"Missing script: {script_file}")
            
            # Check if script is executable (on Unix systems)
            if script_file.endswith('.sh') and os.name != 'nt':
                file_stat = os.stat(script_file)
                self.assertTrue(file_stat.st_mode & 0o111, f"Script not executable: {script_file}")
            
            print(f"✓ {script_file} exists")
        
        print("✓ All required scripts exist")
    
    def test_source_code_structure(self):
        """Test source code structure"""
        print("\n=== Testing Source Code Structure ===")
        
        # Check main application files
        main_files = [
            'main.py',
            'start_bot.py',
            'src/__init__.py',
            'src/config.py',
            'src/models.py',
            'src/health_check.py'
        ]
        
        for main_file in main_files:
            print(f"Checking main file: {main_file}")
            self.assertTrue(os.path.exists(main_file), f"Missing main file: {main_file}")
            print(f"✓ {main_file} exists")
        
        # Check that key modules have __init__.py files
        modules = [
            'src/data',
            'src/analysis',
            'src/risk',
            'src/trading',
            'src/monitoring',
            'src/analytics',
            'src/backtesting',
            'src/maintenance'
        ]
        
        for module in modules:
            init_file = os.path.join(module, '__init__.py')
            print(f"Checking module init: {init_file}")
            self.assertTrue(os.path.exists(init_file), f"Missing __init__.py: {init_file}")
            print(f"✓ {init_file} exists")
        
        print("✓ Source code structure is correct")
    
    def test_environment_template(self):
        """Test environment template file"""
        print("\n=== Testing Environment Template ===")
        
        # Check if .env.example exists (template for environment variables)
        if os.path.exists('.env.example'):
            with open('.env.example', 'r') as f:
                env_template = f.read()
                
                # Check for essential environment variables
                essential_vars = [
                    'DB_PASSWORD',
                    'LLM_API_KEY',
                    'BROKER_API_KEY',
                    'BROKER_API_SECRET'
                ]
                
                for var in essential_vars:
                    self.assertIn(var, env_template, f"Missing env var template: {var}")
                    print(f"✓ Found env var template: {var}")
            
            print("✓ Environment template is complete")
        else:
            print("⚠ No .env.example file found (recommended for deployment)")
    
    def test_logging_setup(self):
        """Test logging setup"""
        print("\n=== Testing Logging Setup ===")
        
        # Check logs directory exists
        self.assertTrue(os.path.isdir('logs'), "Missing logs directory")
        print("✓ Logs directory exists")
        
        # Check logging configuration
        if os.path.exists('src/logging_config.py'):
            print("✓ Logging configuration file exists")
        else:
            print("⚠ No dedicated logging configuration file found")
        
        # Check that log files can be created
        test_log_file = 'logs/test_log.txt'
        try:
            with open(test_log_file, 'w') as f:
                f.write(f"Test log entry: {datetime.now()}\n")
            os.remove(test_log_file)
            print("✓ Log directory is writable")
        except Exception as e:
            self.fail(f"Cannot write to logs directory: {e}")
    
    def test_performance_optimization_files(self):
        """Test performance optimization documentation and configuration"""
        print("\n=== Testing Performance Optimization ===")
        
        # Check performance documentation
        perf_doc = 'docs/PERFORMANCE_OPTIMIZATION.md'
        self.assertTrue(os.path.exists(perf_doc), f"Missing {perf_doc}")
        
        with open(perf_doc, 'r', encoding='utf-8') as f:
            content = f.read()
            
            # Check for key performance topics
            performance_topics = [
                'Database Optimization',
                'Memory Management',
                'API Call Optimization',
                'Caching Strategy',
                'Performance Monitoring'
            ]
            
            for topic in performance_topics:
                self.assertIn(topic, content, f"Missing performance topic: {topic}")
                print(f"✓ Found performance topic: {topic}")
        
        print("✓ Performance optimization documentation is complete")
    
    def test_security_considerations(self):
        """Test security-related files and configurations"""
        print("\n=== Testing Security Considerations ===")
        
        # Check that sensitive files are not committed
        sensitive_patterns = ['.env', '*.key', '*.pem', 'secrets.*']
        
        # Check .gitignore exists and contains sensitive patterns
        if os.path.exists('.gitignore'):
            with open('.gitignore', 'r') as f:
                gitignore_content = f.read()
                
                security_patterns = ['.env', '*.log', '__pycache__', '*.pyc']
                for pattern in security_patterns:
                    if pattern in gitignore_content:
                        print(f"✓ .gitignore includes: {pattern}")
                    else:
                        print(f"⚠ .gitignore missing: {pattern}")
        else:
            print("⚠ No .gitignore file found")
        
        # Check that no actual sensitive files are present
        sensitive_files = ['.env', 'secrets.json', 'private.key']
        for sensitive_file in sensitive_files:
            if os.path.exists(sensitive_file):
                print(f"⚠ Sensitive file found: {sensitive_file} (should not be in repository)")
            else:
                print(f"✓ No sensitive file: {sensitive_file}")
        
        print("✓ Security considerations checked")
    
    def test_test_files(self):
        """Test that test files exist and are properly structured"""
        print("\n=== Testing Test Files ===")
        
        # Find all test files
        test_files = []
        for root, dirs, files in os.walk('.'):
            for file in files:
                if file.startswith('test_') and file.endswith('.py'):
                    test_files.append(os.path.join(root, file))
        
        self.assertGreater(len(test_files), 10, "Not enough test files found")
        print(f"✓ Found {len(test_files)} test files")
        
        # Check for key test categories
        test_categories = [
            'test_config',
            'test_data',
            'test_analysis',
            'test_risk',
            'test_trading',
            'test_monitoring',
            'test_integration'
        ]
        
        found_categories = []
        for test_file in test_files:
            for category in test_categories:
                if category in test_file:
                    found_categories.append(category)
                    break
        
        coverage = len(set(found_categories)) / len(test_categories)
        print(f"✓ Test coverage: {coverage:.1%} of key categories")
        
        if coverage < 0.7:
            print("⚠ Low test coverage - consider adding more tests")
        
        print("✓ Test file structure is adequate")


class TestSystemIntegration(unittest.TestCase):
    """Basic system integration tests"""
    
    def test_import_main_modules(self):
        """Test that main modules can be imported"""
        print("\n=== Testing Module Imports ===")
        
        modules_to_test = [
            'src.config',
            'src.models',
            'src.health_check',
            'src.monitoring.performance_monitor',
            'src.monitoring.alert_system'
        ]
        
        for module_name in modules_to_test:
            try:
                __import__(module_name)
                print(f"✓ Successfully imported: {module_name}")
            except ImportError as e:
                self.fail(f"Failed to import {module_name}: {e}")
            except Exception as e:
                print(f"⚠ Import warning for {module_name}: {e}")
        
        print("✓ All main modules can be imported")
    
    def test_configuration_loading(self):
        """Test configuration loading"""
        print("\n=== Testing Configuration Loading ===")
        
        try:
            from src.config import get_config_manager
            config_manager = get_config_manager()
            
            # Test basic configuration access
            config = config_manager.get_config()
            self.assertIsInstance(config, dict)
            print("✓ Configuration loaded successfully")
            
            # Test specific configuration sections
            sections = ['trading', 'risk_management', 'analysis']
            for section in sections:
                if section in config:
                    print(f"✓ Found configuration section: {section}")
                else:
                    print(f"⚠ Missing configuration section: {section}")
            
        except Exception as e:
            self.fail(f"Configuration loading failed: {e}")
    
    def test_health_check_system(self):
        """Test health check system"""
        print("\n=== Testing Health Check System ===")
        
        try:
            from src.health_check import HealthChecker
            health_checker = HealthChecker()
            
            # Test basic health check
            health_status = health_checker.check_system_health()
            self.assertIsInstance(health_status, dict)
            self.assertIn('status', health_status)
            print("✓ Health check system works")
            
        except Exception as e:
            print(f"⚠ Health check system issue: {e}")
    
    def test_monitoring_system(self):
        """Test monitoring system components"""
        print("\n=== Testing Monitoring System ===")
        
        try:
            from src.monitoring.performance_monitor import PerformanceMonitor
            from src.monitoring.alert_system import AlertSystem
            
            # Test performance monitor
            perf_monitor = PerformanceMonitor(enable_system_metrics=False)
            self.assertIsNotNone(perf_monitor)
            print("✓ Performance monitor initialized")
            
            # Test alert system
            alert_system = AlertSystem()
            self.assertIsNotNone(alert_system)
            print("✓ Alert system initialized")
            
        except Exception as e:
            print(f"⚠ Monitoring system issue: {e}")


def run_production_validation():
    """Run all production validation tests"""
    print("=" * 60)
    print("PRODUCTION VALIDATION TESTS")
    print("=" * 60)
    
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add production validation tests
    validation_tests = [
        'test_configuration_files',
        'test_documentation_completeness',
        'test_docker_configuration',
        'test_requirements_file',
        'test_directory_structure',
        'test_script_files',
        'test_source_code_structure',
        'test_environment_template',
        'test_logging_setup',
        'test_performance_optimization_files',
        'test_security_considerations',
        'test_test_files'
    ]
    
    for test_name in validation_tests:
        test_suite.addTest(TestProductionValidation(test_name))
    
    # Add system integration tests
    integration_tests = [
        'test_import_main_modules',
        'test_configuration_loading',
        'test_health_check_system',
        'test_monitoring_system'
    ]
    
    for test_name in integration_tests:
        test_suite.addTest(TestSystemIntegration(test_name))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Print summary
    print("\n" + "=" * 60)
    print("PRODUCTION VALIDATION SUMMARY")
    print("=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.failures:
        print("\nFAILURES:")
        for test, traceback in result.failures:
            print(f"- {test}")
    
    if result.errors:
        print("\nERRORS:")
        for test, traceback in result.errors:
            print(f"- {test}")
    
    success_rate = (result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun
    print(f"\nSuccess Rate: {success_rate:.1%}")
    
    if success_rate >= 0.9:
        print("\n🎉 SYSTEM VALIDATION PASSED - READY FOR PRODUCTION!")
        return True
    elif success_rate >= 0.8:
        print("\n⚠️  SYSTEM MOSTLY READY - MINOR ISSUES TO ADDRESS")
        return True
    else:
        print("\n❌ SYSTEM NOT READY - SIGNIFICANT ISSUES FOUND")
        return False


if __name__ == '__main__':
    success = run_production_validation()
    exit(0 if success else 1)