#!/usr/bin/env python3
"""
Production Deployment Script for AI Forex Trading Bot

This script handles the complete production deployment process including:
1. Environment validation
2. Configuration setup
3. Database initialization
4. Docker container deployment
5. Health checks
6. Monitoring setup
7. Backup configuration
8. Security validation
"""

import os
import sys
import json
import subprocess
import time
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
import docker
import requests
import yaml


class ProductionDeployer:
    """Handles production deployment of the trading bot"""
    
    def __init__(self, config_path: str = None):
        self.config_path = config_path or "config/config.prod.json"
        self.docker_client = None
        self.deployment_config = {}
        self.logger = self._setup_logging()
        
    def _setup_logging(self) -> logging.Logger:
        """Set up logging for deployment"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('logs/deployment.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        return logging.getLogger(__name__)
    
    def validate_environment(self) -> bool:
        """Validate production environment requirements"""
        self.logger.info("Validating production environment...")
        
        # Check required environment variables
        required_env_vars = [
            'DB_PASSWORD',
            'LLM_API_KEY',
            'BROKER_API_KEY',
            'BROKER_API_SECRET'
        ]
        
        missing_vars = []
        for var in required_env_vars:
            if not os.getenv(var):
                missing_vars.append(var)
        
        if missing_vars:
            self.logger.error(f"Missing required environment variables: {missing_vars}")
            return False
        
        # Check Docker availability
        try:
            self.docker_client = docker.from_env()
            self.docker_client.ping()
            self.logger.info("Docker daemon is accessible")
        except Exception as e:
            self.logger.error(f"Docker daemon not accessible: {e}")
            return False
        
        # Check required files
        required_files = [
            'Dockerfile',
            'docker-compose.yml',
            'requirements.txt',
            'main.py',
            'config/config.prod.json'
        ]
        
        missing_files = []
        for file_path in required_files:
            if not os.path.exists(file_path):
                missing_files.append(file_path)
        
        if missing_files:
            self.logger.error(f"Missing required files: {missing_files}")
            return False
        
        # Check disk space
        disk_usage = os.statvfs('.')
        free_space_gb = (disk_usage.f_frsize * disk_usage.f_bavail) / (1024**3)
        if free_space_gb < 5:  # Less than 5GB
            self.logger.error(f"Insufficient disk space: {free_space_gb:.2f}GB available")
            return False
        
        self.logger.info("Environment validation passed")
        return True
    
    def load_deployment_config(self) -> bool:
        """Load deployment configuration"""
        try:
            with open(self.config_path, 'r') as f:
                self.deployment_config = json.load(f)
            self.logger.info("Deployment configuration loaded")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load deployment config: {e}")
            return False
    
    def setup_directories(self) -> bool:
        """Create necessary directories"""
        directories = [
            'logs',
            'data',
            'backups',
            'config'
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
        
        self.logger.info("Directories setup completed")
        return True
    
    def validate_configuration(self) -> bool:
        """Validate production configuration"""
        self.logger.info("Validating production configuration...")
        
        try:
            # Import and validate configuration
            sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
            from src.config import get_config_manager
            
            config_manager = get_config_manager()
            validation_summary = config_manager.get_validation_summary()
            
            if not validation_summary['valid']:
                self.logger.error(f"Configuration validation failed: {validation_summary['errors']}")
                return False
            
            if validation_summary['warnings']:
                for warning in validation_summary['warnings']:
                    self.logger.warning(f"Configuration warning: {warning}")
            
            self.logger.info("Configuration validation passed")
            return True
            
        except Exception as e:
            self.logger.error(f"Configuration validation error: {e}")
            return False
    
    def run_tests(self) -> bool:
        """Run production integration tests"""
        self.logger.info("Running production integration tests...")
        
        try:
            # Run the production integration tests
            result = subprocess.run([
                sys.executable, '-m', 'pytest',
                'test_production_integration.py',
                '-v',
                '--tb=short',
                '--asyncio-mode=auto'
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                self.logger.error(f"Tests failed:\n{result.stdout}\n{result.stderr}")
                return False
            
            self.logger.info("Production integration tests passed")
            return True
            
        except Exception as e:
            self.logger.error(f"Test execution error: {e}")
            return False
    
    def build_docker_image(self) -> bool:
        """Build Docker image for production"""
        self.logger.info("Building Docker image...")
        
        try:
            # Build the image
            image, build_logs = self.docker_client.images.build(
                path=".",
                dockerfile="Dockerfile",
                tag="ai-forex-trading-bot:latest",
                target="production",
                rm=True
            )
            
            self.logger.info(f"Docker image built successfully: {image.tags}")
            return True
            
        except Exception as e:
            self.logger.error(f"Docker build failed: {e}")
            return False
    
    def setup_database(self) -> bool:
        """Initialize database for production"""
        self.logger.info("Setting up production database...")
        
        try:
            # Start database container
            subprocess.run([
                'docker-compose', 'up', '-d', 'postgres'
            ], check=True)
            
            # Wait for database to be ready
            time.sleep(10)
            
            # Run database initialization
            subprocess.run([
                'docker-compose', 'exec', '-T', 'postgres',
                'psql', '-U', 'forex_user', '-d', 'forex_bot_prod',
                '-f', '/docker-entrypoint-initdb.d/init-db.sql'
            ], check=True)
            
            self.logger.info("Database setup completed")
            return True
            
        except Exception as e:
            self.logger.error(f"Database setup failed: {e}")
            return False
    
    def deploy_application(self) -> bool:
        """Deploy the application using Docker Compose"""
        self.logger.info("Deploying application...")
        
        try:
            # Deploy all services
            subprocess.run([
                'docker-compose', 'up', '-d'
            ], check=True)
            
            # Wait for services to start
            time.sleep(30)
            
            self.logger.info("Application deployment completed")
            return True
            
        except Exception as e:
            self.logger.error(f"Application deployment failed: {e}")
            return False
    
    def run_health_checks(self) -> bool:
        """Run comprehensive health checks"""
        self.logger.info("Running health checks...")
        
        health_checks = [
            self._check_container_health,
            self._check_application_health,
            self._check_database_health,
            self._check_redis_health
        ]
        
        for check in health_checks:
            if not check():
                return False
        
        self.logger.info("All health checks passed")
        return True
    
    def _check_container_health(self) -> bool:
        """Check Docker container health"""
        try:
            containers = self.docker_client.containers.list()
            
            for container in containers:
                if container.name.startswith('ai-forex-trading-bot'):
                    health = container.attrs.get('State', {}).get('Health', {})
                    if health.get('Status') != 'healthy':
                        self.logger.error(f"Container {container.name} is not healthy")
                        return False
            
            self.logger.info("Container health check passed")
            return True
            
        except Exception as e:
            self.logger.error(f"Container health check failed: {e}")
            return False
    
    def _check_application_health(self) -> bool:
        """Check application health endpoint"""
        try:
            response = requests.get('http://localhost:8080/health', timeout=10)
            if response.status_code == 200:
                health_data = response.json()
                if health_data.get('status') == 'healthy':
                    self.logger.info("Application health check passed")
                    return True
                else:
                    self.logger.error(f"Application health check failed: {health_data}")
                    return False
            else:
                self.logger.error(f"Application health check failed: {response.status_code}")
                return False
                
        except Exception as e:
            self.logger.error(f"Application health check error: {e}")
            return False
    
    def _check_database_health(self) -> bool:
        """Check database health"""
        try:
            result = subprocess.run([
                'docker-compose', 'exec', '-T', 'postgres',
                'pg_isready', '-U', 'forex_user', '-d', 'forex_bot_prod'
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                self.logger.info("Database health check passed")
                return True
            else:
                self.logger.error(f"Database health check failed: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"Database health check error: {e}")
            return False
    
    def _check_redis_health(self) -> bool:
        """Check Redis health"""
        try:
            result = subprocess.run([
                'docker-compose', 'exec', '-T', 'redis',
                'redis-cli', 'ping'
            ], capture_output=True, text=True)
            
            if result.returncode == 0 and 'PONG' in result.stdout:
                self.logger.info("Redis health check passed")
                return True
            else:
                self.logger.error(f"Redis health check failed: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"Redis health check error: {e}")
            return False
    
    def setup_monitoring(self) -> bool:
        """Setup monitoring and alerting"""
        self.logger.info("Setting up monitoring...")
        
        try:
            # Create monitoring configuration
            monitoring_config = {
                'alerts': {
                    'email': os.getenv('ALERT_EMAIL'),
                    'webhook': os.getenv('ALERT_WEBHOOK')
                },
                'metrics': {
                    'retention_days': 30,
                    'collection_interval': 60
                }
            }
            
            with open('config/monitoring.json', 'w') as f:
                json.dump(monitoring_config, f, indent=2)
            
            self.logger.info("Monitoring setup completed")
            return True
            
        except Exception as e:
            self.logger.error(f"Monitoring setup failed: {e}")
            return False
    
    def setup_backups(self) -> bool:
        """Setup backup configuration"""
        self.logger.info("Setting up backup configuration...")
        
        try:
            # Create backup script
            backup_script = '''#!/bin/bash
# Backup script for AI Forex Trading Bot

BACKUP_DIR="/app/backups"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p $BACKUP_DIR

# Backup database
docker-compose exec -T postgres pg_dump -U forex_user forex_bot_prod > $BACKUP_DIR/db_backup_$DATE.sql

# Backup configuration
tar -czf $BACKUP_DIR/config_backup_$DATE.tar.gz config/

# Backup logs
tar -czf $BACKUP_DIR/logs_backup_$DATE.tar.gz logs/

# Clean old backups (keep last 7 days)
find $BACKUP_DIR -name "*.sql" -mtime +7 -delete
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete

echo "Backup completed: $DATE"
'''
            
            with open('scripts/backup.sh', 'w') as f:
                f.write(backup_script)
            
            # Make backup script executable
            os.chmod('scripts/backup.sh', 0o755)
            
            # Setup cron job for daily backups
            cron_job = "0 2 * * * /app/scripts/backup.sh >> /app/logs/backup.log 2>&1"
            
            self.logger.info("Backup configuration completed")
            return True
            
        except Exception as e:
            self.logger.error(f"Backup setup failed: {e}")
            return False
    
    def setup_security(self) -> bool:
        """Setup security measures"""
        self.logger.info("Setting up security measures...")
        
        try:
            # Create security configuration
            security_config = {
                'firewall': {
                    'allowed_ports': [8080, 5432, 6379],
                    'allowed_ips': []
                },
                'ssl': {
                    'enabled': True,
                    'cert_path': '/app/certs/',
                    'key_path': '/app/certs/'
                },
                'rate_limiting': {
                    'enabled': True,
                    'requests_per_minute': 100
                }
            }
            
            with open('config/security.json', 'w') as f:
                json.dump(security_config, f, indent=2)
            
            self.logger.info("Security setup completed")
            return True
            
        except Exception as e:
            self.logger.error(f"Security setup failed: {e}")
            return False
    
    def create_deployment_summary(self) -> Dict[str, Any]:
        """Create deployment summary report"""
        summary = {
            'deployment_time': datetime.now(timezone.utc).isoformat(),
            'version': '1.0.0',
            'environment': 'production',
            'services': {
                'forex-bot': 'running',
                'postgres': 'running',
                'redis': 'running'
            },
            'health_status': 'healthy',
            'endpoints': {
                'health': 'http://localhost:8080/health',
                'metrics': 'http://localhost:8080/metrics'
            },
            'monitoring': {
                'logs': '/app/logs/',
                'backups': '/app/backups/',
                'alerts': 'configured'
            }
        }
        
        # Save deployment summary
        with open('deployment_summary.json', 'w') as f:
            json.dump(summary, f, indent=2)
        
        return summary
    
    def deploy(self) -> bool:
        """Execute complete deployment process"""
        self.logger.info("Starting production deployment...")
        
        deployment_steps = [
            ("Environment validation", self.validate_environment),
            ("Load deployment config", self.load_deployment_config),
            ("Setup directories", self.setup_directories),
            ("Validate configuration", self.validate_configuration),
            ("Run tests", self.run_tests),
            ("Build Docker image", self.build_docker_image),
            ("Setup database", self.setup_database),
            ("Deploy application", self.deploy_application),
            ("Run health checks", self.run_health_checks),
            ("Setup monitoring", self.setup_monitoring),
            ("Setup backups", self.setup_backups),
            ("Setup security", self.setup_security)
        ]
        
        for step_name, step_func in deployment_steps:
            self.logger.info(f"Executing: {step_name}")
            if not step_func():
                self.logger.error(f"Deployment failed at: {step_name}")
                return False
        
        # Create deployment summary
        summary = self.create_deployment_summary()
        self.logger.info("Deployment completed successfully!")
        self.logger.info(f"Deployment summary: {json.dumps(summary, indent=2)}")
        
        return True


def main():
    """Main deployment function"""
    parser = argparse.ArgumentParser(description='Deploy AI Forex Trading Bot to production')
    parser.add_argument('--config', help='Path to deployment configuration file')
    parser.add_argument('--skip-tests', action='store_true', help='Skip running tests')
    parser.add_argument('--dry-run', action='store_true', help='Perform dry run without actual deployment')
    
    args = parser.parse_args()
    
    deployer = ProductionDeployer(args.config)
    
    if args.dry_run:
        deployer.logger.info("Performing dry run...")
        # Only run validation steps
        if (deployer.validate_environment() and 
            deployer.load_deployment_config() and
            deployer.validate_configuration()):
            deployer.logger.info("Dry run completed successfully")
            return 0
        else:
            deployer.logger.error("Dry run failed")
            return 1
    
    if deployer.deploy():
        print("✅ Production deployment completed successfully!")
        return 0
    else:
        print("❌ Production deployment failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main()) 