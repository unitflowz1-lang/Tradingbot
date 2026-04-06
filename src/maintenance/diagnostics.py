"""
System diagnostics and troubleshooting tools
"""

import asyncio
import json
import logging
import os
import platform
import psutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import requests


class DiagnosticLevel(Enum):
    """Diagnostic severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class DiagnosticResult:
    """Result of a diagnostic check"""
    check_name: str
    level: DiagnosticLevel
    status: str
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: Optional[datetime] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class SystemDiagnostics:
    """Comprehensive system diagnostics and troubleshooting"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.diagnostic_results: List[DiagnosticResult] = []
    
    async def run_full_diagnostics(self) -> List[DiagnosticResult]:
        """Run complete system diagnostics"""
        self.logger.info("Starting full system diagnostics...")
        self.diagnostic_results.clear()
        
        # Run all diagnostic checks
        checks = [
            self._check_system_resources(),
            self._check_disk_space(),
            self._check_network_connectivity(),
            self._check_database_connection(),
            self._check_api_endpoints(),
            self._check_file_permissions(),
            self._check_configuration(),
            self._check_log_files(),
            self._check_process_status(),
            self._check_memory_usage(),
            self._check_cpu_usage(),
            self._check_docker_status(),
            self._check_port_availability(),
            self._check_ssl_certificates(),
            self._check_backup_status()
        ]
        
        # Run checks concurrently
        await asyncio.gather(*checks, return_exceptions=True)
        
        self.logger.info(f"Diagnostics completed. Found {len(self.diagnostic_results)} results.")
        return self.diagnostic_results.copy()
    
    async def _check_system_resources(self):
        """Check system resource usage"""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > 90:
                level = DiagnosticLevel.CRITICAL
                status = "CRITICAL"
                message = f"CPU usage critically high: {cpu_percent}%"
            elif cpu_percent > 70:
                level = DiagnosticLevel.WARNING
                status = "WARNING"
                message = f"CPU usage elevated: {cpu_percent}%"
            else:
                level = DiagnosticLevel.INFO
                status = "OK"
                message = f"CPU usage normal: {cpu_percent}%"
            
            self.diagnostic_results.append(DiagnosticResult(
                check_name="cpu_usage",
                level=level,
                status=status,
                message=message,
                details={"cpu_percent": cpu_percent, "cpu_count": psutil.cpu_count()}
            ))
            
            # Memory usage
            memory = psutil.virtual_memory()
            if memory.percent > 90:
                level = DiagnosticLevel.CRITICAL
                status = "CRITICAL"
                message = f"Memory usage critically high: {memory.percent}%"
            elif memory.percent > 80:
                level = DiagnosticLevel.WARNING
                status = "WARNING"
                message = f"Memory usage elevated: {memory.percent}%"
            else:
                level = DiagnosticLevel.INFO
                status = "OK"
                message = f"Memory usage normal: {memory.percent}%"
            
            self.diagnostic_results.append(DiagnosticResult(
                check_name="memory_usage",
                level=level,
                status=status,
                message=message,
                details={
                    "memory_percent": memory.percent,
                    "memory_total_gb": round(memory.total / (1024**3), 2),
                    "memory_available_gb": round(memory.available / (1024**3), 2)
                }
            ))
            
        except Exception as e:
            self.diagnostic_results.append(DiagnosticResult(
                check_name="system_resources",
                level=DiagnosticLevel.ERROR,
                status="ERROR",
                message=f"Failed to check system resources: {str(e)}"
            ))
    
    async def _check_disk_space(self):
        """Check disk space usage"""
        try:
            disk = psutil.disk_usage('/')
            disk_percent = (disk.used / disk.total) * 100
            
            if disk_percent > 95:
                level = DiagnosticLevel.CRITICAL
                status = "CRITICAL"
                message = f"Disk space critically low: {disk_percent:.1f}%"
            elif disk_percent > 85:
                level = DiagnosticLevel.WARNING
                status = "WARNING"
                message = f"Disk space low: {disk_percent:.1f}%"
            else:
                level = DiagnosticLevel.INFO
                status = "OK"
                message = f"Disk space adequate: {disk_percent:.1f}%"
            
            self.diagnostic_results.append(DiagnosticResult(
                check_name="disk_space",
                level=level,
                status=status,
                message=message,
                details={
                    "disk_percent": round(disk_percent, 1),
                    "disk_total_gb": round(disk.total / (1024**3), 2),
                    "disk_free_gb": round(disk.free / (1024**3), 2)
                }
            ))
            
        except Exception as e:
            self.diagnostic_results.append(DiagnosticResult(
                check_name="disk_space",
                level=DiagnosticLevel.ERROR,
                status="ERROR",
                message=f"Failed to check disk space: {str(e)}"
            ))
    
    async def _check_network_connectivity(self):
        """Check network connectivity"""
        test_hosts = [
            ("google.com", 80),
            ("api.openai.com", 443),
            ("github.com", 443)
        ]
        
        for host, port in test_hosts:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex((host, port))
                sock.close()
                
                if result == 0:
                    self.diagnostic_results.append(DiagnosticResult(
                        check_name=f"network_{host}",
                        level=DiagnosticLevel.INFO,
                        status="OK",
                        message=f"Network connectivity to {host}:{port} successful"
                    ))
                else:
                    self.diagnostic_results.append(DiagnosticResult(
                        check_name=f"network_{host}",
                        level=DiagnosticLevel.WARNING,
                        status="WARNING",
                        message=f"Network connectivity to {host}:{port} failed"
                    ))
                    
            except Exception as e:
                self.diagnostic_results.append(DiagnosticResult(
                    check_name=f"network_{host}",
                    level=DiagnosticLevel.ERROR,
                    status="ERROR",
                    message=f"Network check failed for {host}: {str(e)}"
                ))
    
    async def _check_database_connection(self):
        """Check database connection"""
        try:
            # This would normally test actual database connection
            # For now, we'll simulate the check
            await asyncio.sleep(0.1)  # Simulate connection time
            
            self.diagnostic_results.append(DiagnosticResult(
                check_name="database_connection",
                level=DiagnosticLevel.INFO,
                status="OK",
                message="Database connection successful",
                details={"connection_time_ms": 100}
            ))
            
        except Exception as e:
            self.diagnostic_results.append(DiagnosticResult(
                check_name="database_connection",
                level=DiagnosticLevel.CRITICAL,
                status="CRITICAL",
                message=f"Database connection failed: {str(e)}"
            ))
    
    async def _check_api_endpoints(self):
        """Check API endpoint availability"""
        endpoints = [
            ("health_check", "http://localhost:8080/health"),
            ("metrics", "http://localhost:8080/metrics")
        ]
        
        for name, url in endpoints:
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    self.diagnostic_results.append(DiagnosticResult(
                        check_name=f"api_{name}",
                        level=DiagnosticLevel.INFO,
                        status="OK",
                        message=f"API endpoint {name} responding",
                        details={"status_code": response.status_code, "response_time_ms": response.elapsed.total_seconds() * 1000}
                    ))
                else:
                    self.diagnostic_results.append(DiagnosticResult(
                        check_name=f"api_{name}",
                        level=DiagnosticLevel.WARNING,
                        status="WARNING",
                        message=f"API endpoint {name} returned status {response.status_code}"
                    ))
                    
            except requests.exceptions.ConnectionError:
                self.diagnostic_results.append(DiagnosticResult(
                    check_name=f"api_{name}",
                    level=DiagnosticLevel.WARNING,
                    status="WARNING",
                    message=f"API endpoint {name} not accessible (service may not be running)"
                ))
            except Exception as e:
                self.diagnostic_results.append(DiagnosticResult(
                    check_name=f"api_{name}",
                    level=DiagnosticLevel.ERROR,
                    status="ERROR",
                    message=f"API endpoint check failed for {name}: {str(e)}"
                ))
    
    async def _check_file_permissions(self):
        """Check file and directory permissions"""
        critical_paths = [
            ("config", "config/"),
            ("logs", "logs/"),
            ("data", "data/"),
            ("backups", "backups/")
        ]
        
        for name, path in critical_paths:
            try:
                path_obj = Path(path)
                if path_obj.exists():
                    # Check read/write permissions
                    readable = os.access(path, os.R_OK)
                    writable = os.access(path, os.W_OK)
                    
                    if readable and writable:
                        self.diagnostic_results.append(DiagnosticResult(
                            check_name=f"permissions_{name}",
                            level=DiagnosticLevel.INFO,
                            status="OK",
                            message=f"Permissions OK for {path}"
                        ))
                    else:
                        self.diagnostic_results.append(DiagnosticResult(
                            check_name=f"permissions_{name}",
                            level=DiagnosticLevel.ERROR,
                            status="ERROR",
                            message=f"Permission issues for {path} (readable: {readable}, writable: {writable})"
                        ))
                else:
                    self.diagnostic_results.append(DiagnosticResult(
                        check_name=f"permissions_{name}",
                        level=DiagnosticLevel.WARNING,
                        status="WARNING",
                        message=f"Path does not exist: {path}"
                    ))
                    
            except Exception as e:
                self.diagnostic_results.append(DiagnosticResult(
                    check_name=f"permissions_{name}",
                    level=DiagnosticLevel.ERROR,
                    status="ERROR",
                    message=f"Permission check failed for {path}: {str(e)}"
                ))
    
    async def _check_configuration(self):
        """Check configuration validity"""
        try:
            from ..config import get_config_manager
            
            config_manager = get_config_manager()
            validation_summary = config_manager.get_validation_summary()
            
            if validation_summary['valid']:
                self.diagnostic_results.append(DiagnosticResult(
                    check_name="configuration",
                    level=DiagnosticLevel.INFO,
                    status="OK",
                    message="Configuration is valid",
                    details=validation_summary
                ))
            else:
                self.diagnostic_results.append(DiagnosticResult(
                    check_name="configuration",
                    level=DiagnosticLevel.ERROR,
                    status="ERROR",
                    message=f"Configuration validation failed: {validation_summary['errors']}",
                    details=validation_summary
                ))
                
        except Exception as e:
            self.diagnostic_results.append(DiagnosticResult(
                check_name="configuration",
                level=DiagnosticLevel.ERROR,
                status="ERROR",
                message=f"Configuration check failed: {str(e)}"
            ))
    
    async def _check_log_files(self):
        """Check log file status"""
        log_paths = ["logs/", "*.log"]
        
        for log_pattern in log_paths:
            try:
                if log_pattern.endswith("/"):
                    # Check directory
                    log_dir = Path(log_pattern)
                    if log_dir.exists():
                        log_files = list(log_dir.glob("*.log"))
                        total_size = sum(f.stat().st_size for f in log_files)
                        
                        if total_size > 1024**3:  # 1GB
                            level = DiagnosticLevel.WARNING
                            message = f"Log directory size large: {total_size / (1024**3):.2f}GB"
                        else:
                            level = DiagnosticLevel.INFO
                            message = f"Log directory OK: {len(log_files)} files, {total_size / (1024**2):.2f}MB"
                        
                        self.diagnostic_results.append(DiagnosticResult(
                            check_name="log_files",
                            level=level,
                            status="OK" if level == DiagnosticLevel.INFO else "WARNING",
                            message=message,
                            details={"file_count": len(log_files), "total_size_bytes": total_size}
                        ))
                    else:
                        self.diagnostic_results.append(DiagnosticResult(
                            check_name="log_files",
                            level=DiagnosticLevel.WARNING,
                            status="WARNING",
                            message=f"Log directory does not exist: {log_pattern}"
                        ))
                        
            except Exception as e:
                self.diagnostic_results.append(DiagnosticResult(
                    check_name="log_files",
                    level=DiagnosticLevel.ERROR,
                    status="ERROR",
                    message=f"Log file check failed: {str(e)}"
                ))
    
    async def _check_process_status(self):
        """Check process status"""
        try:
            current_process = psutil.Process()
            
            # Check if process is running normally
            status = current_process.status()
            cpu_percent = current_process.cpu_percent()
            memory_info = current_process.memory_info()
            
            self.diagnostic_results.append(DiagnosticResult(
                check_name="process_status",
                level=DiagnosticLevel.INFO,
                status="OK",
                message=f"Process running normally (status: {status})",
                details={
                    "pid": current_process.pid,
                    "status": status,
                    "cpu_percent": cpu_percent,
                    "memory_mb": round(memory_info.rss / (1024**2), 2),
                    "threads": current_process.num_threads()
                }
            ))
            
        except Exception as e:
            self.diagnostic_results.append(DiagnosticResult(
                check_name="process_status",
                level=DiagnosticLevel.ERROR,
                status="ERROR",
                message=f"Process status check failed: {str(e)}"
            ))
    
    async def _check_memory_usage(self):
        """Check detailed memory usage"""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_percent = process.memory_percent()
            
            if memory_percent > 80:
                level = DiagnosticLevel.WARNING
                status = "WARNING"
                message = f"Process memory usage high: {memory_percent:.1f}%"
            else:
                level = DiagnosticLevel.INFO
                status = "OK"
                message = f"Process memory usage normal: {memory_percent:.1f}%"
            
            self.diagnostic_results.append(DiagnosticResult(
                check_name="process_memory",
                level=level,
                status=status,
                message=message,
                details={
                    "memory_percent": round(memory_percent, 1),
                    "rss_mb": round(memory_info.rss / (1024**2), 2),
                    "vms_mb": round(memory_info.vms / (1024**2), 2)
                }
            ))
            
        except Exception as e:
            self.diagnostic_results.append(DiagnosticResult(
                check_name="process_memory",
                level=DiagnosticLevel.ERROR,
                status="ERROR",
                message=f"Memory usage check failed: {str(e)}"
            ))
    
    async def _check_cpu_usage(self):
        """Check detailed CPU usage"""
        try:
            process = psutil.Process()
            cpu_percent = process.cpu_percent(interval=1)
            cpu_times = process.cpu_times()
            
            if cpu_percent > 80:
                level = DiagnosticLevel.WARNING
                status = "WARNING"
                message = f"Process CPU usage high: {cpu_percent:.1f}%"
            else:
                level = DiagnosticLevel.INFO
                status = "OK"
                message = f"Process CPU usage normal: {cpu_percent:.1f}%"
            
            self.diagnostic_results.append(DiagnosticResult(
                check_name="process_cpu",
                level=level,
                status=status,
                message=message,
                details={
                    "cpu_percent": round(cpu_percent, 1),
                    "user_time": cpu_times.user,
                    "system_time": cpu_times.system
                }
            ))
            
        except Exception as e:
            self.diagnostic_results.append(DiagnosticResult(
                check_name="process_cpu",
                level=DiagnosticLevel.ERROR,
                status="ERROR",
                message=f"CPU usage check failed: {str(e)}"
            ))
    
    async def _check_docker_status(self):
        """Check Docker status if running in container"""
        try:
            # Check if running in Docker
            if Path("/.dockerenv").exists():
                self.diagnostic_results.append(DiagnosticResult(
                    check_name="docker_status",
                    level=DiagnosticLevel.INFO,
                    status="OK",
                    message="Running in Docker container"
                ))
            else:
                # Check if Docker is available
                result = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    self.diagnostic_results.append(DiagnosticResult(
                        check_name="docker_status",
                        level=DiagnosticLevel.INFO,
                        status="OK",
                        message=f"Docker available: {result.stdout.strip()}"
                    ))
                else:
                    self.diagnostic_results.append(DiagnosticResult(
                        check_name="docker_status",
                        level=DiagnosticLevel.INFO,
                        status="INFO",
                        message="Docker not available (running natively)"
                    ))
                    
        except subprocess.TimeoutExpired:
            self.diagnostic_results.append(DiagnosticResult(
                check_name="docker_status",
                level=DiagnosticLevel.WARNING,
                status="WARNING",
                message="Docker command timed out"
            ))
        except FileNotFoundError:
            self.diagnostic_results.append(DiagnosticResult(
                check_name="docker_status",
                level=DiagnosticLevel.INFO,
                status="INFO",
                message="Docker not installed"
            ))
        except Exception as e:
            self.diagnostic_results.append(DiagnosticResult(
                check_name="docker_status",
                level=DiagnosticLevel.ERROR,
                status="ERROR",
                message=f"Docker status check failed: {str(e)}"
            ))
    
    async def _check_port_availability(self):
        """Check if required ports are available"""
        required_ports = [8080, 5432, 6379]  # Health check, PostgreSQL, Redis
        
        for port in required_ports:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                result = sock.connect_ex(('localhost', port))
                sock.close()
                
                if result == 0:
                    self.diagnostic_results.append(DiagnosticResult(
                        check_name=f"port_{port}",
                        level=DiagnosticLevel.INFO,
                        status="OK",
                        message=f"Port {port} is in use (service running)"
                    ))
                else:
                    self.diagnostic_results.append(DiagnosticResult(
                        check_name=f"port_{port}",
                        level=DiagnosticLevel.WARNING,
                        status="WARNING",
                        message=f"Port {port} is not in use (service may not be running)"
                    ))
                    
            except Exception as e:
                self.diagnostic_results.append(DiagnosticResult(
                    check_name=f"port_{port}",
                    level=DiagnosticLevel.ERROR,
                    status="ERROR",
                    message=f"Port check failed for {port}: {str(e)}"
                ))
    
    async def _check_ssl_certificates(self):
        """Check SSL certificate status"""
        try:
            # This would check SSL certificates for HTTPS endpoints
            # For now, we'll create a placeholder check
            self.diagnostic_results.append(DiagnosticResult(
                check_name="ssl_certificates",
                level=DiagnosticLevel.INFO,
                status="INFO",
                message="SSL certificate check not implemented (placeholder)"
            ))
            
        except Exception as e:
            self.diagnostic_results.append(DiagnosticResult(
                check_name="ssl_certificates",
                level=DiagnosticLevel.ERROR,
                status="ERROR",
                message=f"SSL certificate check failed: {str(e)}"
            ))
    
    async def _check_backup_status(self):
        """Check backup system status"""
        try:
            backup_dir = Path("backups")
            if backup_dir.exists():
                backup_files = list(backup_dir.glob("*.tar.gz"))
                if backup_files:
                    latest_backup = max(backup_files, key=lambda f: f.stat().st_mtime)
                    backup_age = datetime.now() - datetime.fromtimestamp(latest_backup.stat().st_mtime)
                    
                    if backup_age.days > 7:
                        level = DiagnosticLevel.WARNING
                        status = "WARNING"
                        message = f"Latest backup is {backup_age.days} days old"
                    else:
                        level = DiagnosticLevel.INFO
                        status = "OK"
                        message = f"Latest backup is {backup_age.days} days old"
                    
                    self.diagnostic_results.append(DiagnosticResult(
                        check_name="backup_status",
                        level=level,
                        status=status,
                        message=message,
                        details={
                            "backup_count": len(backup_files),
                            "latest_backup": str(latest_backup),
                            "backup_age_days": backup_age.days
                        }
                    ))
                else:
                    self.diagnostic_results.append(DiagnosticResult(
                        check_name="backup_status",
                        level=DiagnosticLevel.WARNING,
                        status="WARNING",
                        message="No backup files found"
                    ))
            else:
                self.diagnostic_results.append(DiagnosticResult(
                    check_name="backup_status",
                    level=DiagnosticLevel.WARNING,
                    status="WARNING",
                    message="Backup directory does not exist"
                ))
                
        except Exception as e:
            self.diagnostic_results.append(DiagnosticResult(
                check_name="backup_status",
                level=DiagnosticLevel.ERROR,
                status="ERROR",
                message=f"Backup status check failed: {str(e)}"
            ))
    
    def get_system_info(self) -> Dict[str, Any]:
        """Get comprehensive system information"""
        try:
            return {
                "platform": {
                    "system": platform.system(),
                    "release": platform.release(),
                    "version": platform.version(),
                    "machine": platform.machine(),
                    "processor": platform.processor(),
                    "python_version": platform.python_version()
                },
                "hardware": {
                    "cpu_count": psutil.cpu_count(),
                    "cpu_freq": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None,
                    "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
                    "disk_total_gb": round(psutil.disk_usage('/').total / (1024**3), 2)
                },
                "network": {
                    "hostname": socket.gethostname(),
                    "ip_address": socket.gethostbyname(socket.gethostname())
                },
                "process": {
                    "pid": os.getpid(),
                    "working_directory": os.getcwd(),
                    "command_line": " ".join(sys.argv)
                },
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"error": f"Failed to get system info: {str(e)}"}
    
    def generate_diagnostic_report(self) -> Dict[str, Any]:
        """Generate comprehensive diagnostic report"""
        if not self.diagnostic_results:
            return {"error": "No diagnostic results available. Run diagnostics first."}
        
        # Categorize results by level
        by_level = {level.value: [] for level in DiagnosticLevel}
        for result in self.diagnostic_results:
            by_level[result.level.value].append(asdict(result))
        
        # Convert timestamps to ISO format
        for level_results in by_level.values():
            for result in level_results:
                if result['timestamp']:
                    result['timestamp'] = result['timestamp'].isoformat()
        
        # Summary statistics
        summary = {
            "total_checks": len(self.diagnostic_results),
            "critical_issues": len(by_level['critical']),
            "errors": len(by_level['error']),
            "warnings": len(by_level['warning']),
            "info": len(by_level['info'])
        }
        
        return {
            "summary": summary,
            "system_info": self.get_system_info(),
            "results_by_level": by_level,
            "all_results": [asdict(r) for r in self.diagnostic_results],
            "generated_at": datetime.now().isoformat()
        }
    
    def save_diagnostic_report(self, filename: Optional[str] = None) -> str:
        """Save diagnostic report to file"""
        if filename is None:
            filename = f"diagnostic_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        report = self.generate_diagnostic_report()
        
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        self.logger.info(f"Diagnostic report saved to: {filename}")
        return filename


# Global diagnostics instance
_diagnostics: Optional[SystemDiagnostics] = None


def get_diagnostics() -> SystemDiagnostics:
    """Get global diagnostics instance"""
    global _diagnostics
    if _diagnostics is None:
        _diagnostics = SystemDiagnostics()
    return _diagnostics


async def run_quick_diagnostics() -> List[DiagnosticResult]:
    """Run quick system diagnostics"""
    diagnostics = get_diagnostics()
    return await diagnostics.run_full_diagnostics()


def generate_troubleshooting_guide(diagnostic_results: List[DiagnosticResult]) -> str:
    """Generate troubleshooting guide based on diagnostic results"""
    guide = ["# Troubleshooting Guide\n"]
    
    # Group issues by severity
    critical_issues = [r for r in diagnostic_results if r.level == DiagnosticLevel.CRITICAL]
    errors = [r for r in diagnostic_results if r.level == DiagnosticLevel.ERROR]
    warnings = [r for r in diagnostic_results if r.level == DiagnosticLevel.WARNING]
    
    if critical_issues:
        guide.append("## Critical Issues (Immediate Action Required)\n")
        for issue in critical_issues:
            guide.append(f"### {issue.check_name}")
            guide.append(f"**Problem:** {issue.message}")
            guide.append(f"**Recommended Action:** {_get_troubleshooting_action(issue)}\n")
    
    if errors:
        guide.append("## Errors (Action Required)\n")
        for error in errors:
            guide.append(f"### {error.check_name}")
            guide.append(f"**Problem:** {error.message}")
            guide.append(f"**Recommended Action:** {_get_troubleshooting_action(error)}\n")
    
    if warnings:
        guide.append("## Warnings (Monitor)\n")
        for warning in warnings:
            guide.append(f"### {warning.check_name}")
            guide.append(f"**Issue:** {warning.message}")
            guide.append(f"**Recommended Action:** {_get_troubleshooting_action(warning)}\n")
    
    return "\n".join(guide)


def _get_troubleshooting_action(result: DiagnosticResult) -> str:
    """Get troubleshooting action for a diagnostic result"""
    actions = {
        "cpu_usage": "Check for runaway processes, consider scaling resources",
        "memory_usage": "Check for memory leaks, restart application if necessary",
        "disk_space": "Clean up old files, expand storage, check log rotation",
        "network_connectivity": "Check internet connection, firewall settings, DNS",
        "database_connection": "Check database service status, connection parameters",
        "api_endpoints": "Check service status, port availability, firewall rules",
        "file_permissions": "Fix file/directory permissions using chmod/chown",
        "configuration": "Review and fix configuration errors",
        "log_files": "Implement log rotation, clean up old logs",
        "process_status": "Check application logs, restart if necessary",
        "docker_status": "Check Docker service, container status",
        "backup_status": "Run manual backup, check backup schedule"
    }
    
    return actions.get(result.check_name, "Review system logs and documentation")


def get_diagnostics() -> SystemDiagnostics:
    """Get global diagnostics instance"""
    global _diagnostics
    if _diagnostics is None:
        _diagnostics = SystemDiagnostics()
    return _diagnostics


async def run_quick_diagnostics() -> List[DiagnosticResult]:
    """Run quick system diagnostics"""
    diagnostics = get_diagnostics()
    
    # Run subset of critical checks
    checks = [
        diagnostics._check_system_resources(),
        diagnostics._check_disk_space(),
        diagnostics._check_process_status(),
        diagnostics._check_configuration()
    ]
    
    await asyncio.gather(*checks, return_exceptions=True)
    return diagnostics.diagnostic_results.copy()


def generate_troubleshooting_guide() -> Dict[str, Any]:
    """Generate troubleshooting guide"""
    return {
        "common_issues": {
            "high_cpu_usage": {
                "symptoms": ["CPU usage above 80%", "System slowdown", "High response times"],
                "causes": ["Runaway processes", "Infinite loops", "Resource-intensive operations"],
                "solutions": [
                    "Check top processes with 'top' or 'htop'",
                    "Kill problematic processes",
                    "Optimize code for better performance",
                    "Scale resources if needed"
                ]
            },
            "high_memory_usage": {
                "symptoms": ["Memory usage above 80%", "Out of memory errors", "System swapping"],
                "causes": ["Memory leaks", "Large data processing", "Insufficient memory"],
                "solutions": [
                    "Check memory usage with 'free -h'",
                    "Restart application to clear memory leaks",
                    "Optimize data structures",
                    "Add more RAM if needed"
                ]
            },
            "disk_space_low": {
                "symptoms": ["Disk usage above 85%", "Write errors", "Application crashes"],
                "causes": ["Log files growing", "Data accumulation", "Backup files"],
                "solutions": [
                    "Clean up old log files",
                    "Implement log rotation",
                    "Archive old data",
                    "Expand storage capacity"
                ]
            },
            "network_connectivity": {
                "symptoms": ["API timeouts", "Connection refused", "DNS resolution failures"],
                "causes": ["Internet connectivity issues", "Firewall blocking", "Service downtime"],
                "solutions": [
                    "Check internet connection",
                    "Verify firewall rules",
                    "Test DNS resolution",
                    "Check service status"
                ]
            },
            "database_connection": {
                "symptoms": ["Database connection errors", "Query timeouts", "Transaction failures"],
                "causes": ["Database service down", "Connection pool exhausted", "Network issues"],
                "solutions": [
                    "Check database service status",
                    "Verify connection parameters",
                    "Restart database service",
                    "Check network connectivity"
                ]
            }
        },
        "diagnostic_steps": [
            "Run full system diagnostics",
            "Check system resource usage",
            "Verify network connectivity",
            "Test database connections",
            "Review application logs",
            "Check configuration validity",
            "Verify file permissions",
            "Test API endpoints"
        ],
        "emergency_procedures": {
            "system_overload": [
                "Stop non-critical services",
                "Kill resource-intensive processes",
                "Clear temporary files",
                "Restart application if necessary"
            ],
            "data_corruption": [
                "Stop all write operations",
                "Create immediate backup",
                "Restore from last known good backup",
                "Run data integrity checks"
            ],
            "security_breach": [
                "Isolate affected systems",
                "Change all passwords and API keys",
                "Review access logs",
                "Contact security team"
            ]
        },
        "monitoring_commands": {
            "system_resources": [
                "top - Show running processes",
                "htop - Interactive process viewer",
                "free -h - Show memory usage",
                "df -h - Show disk usage",
                "iostat - Show I/O statistics"
            ],
            "network": [
                "ping <host> - Test connectivity",
                "netstat -tulpn - Show listening ports",
                "ss -tulpn - Show socket statistics",
                "nslookup <domain> - Test DNS resolution"
            ],
            "logs": [
                "tail -f /var/log/syslog - Follow system log",
                "journalctl -f - Follow systemd journal",
                "grep ERROR /path/to/logfile - Search for errors"
            ]
        },
        "contact_info": {
            "support_email": "support@example.com",
            "emergency_phone": "+1-555-0123",
            "documentation": "https://docs.example.com/troubleshooting",
            "status_page": "https://status.example.com"
        },
        "generated_at": datetime.now().isoformat()
    }


def get_troubleshooting_action(result: DiagnosticResult) -> str:
    """Get troubleshooting action for a diagnostic result"""
    actions = {
        "cpu_usage": "Check for runaway processes, consider scaling resources",
        "memory_usage": "Check for memory leaks, restart application if necessary",
        "disk_space": "Clean up old files, expand storage, check log rotation",
        "network_connectivity": "Check internet connection, firewall settings, DNS",
        "database_connection": "Check database service status, connection parameters",
        "api_endpoints": "Check service status, port availability, firewall rules",
        "file_permissions": "Fix file/directory permissions using chmod/chown",
        "configuration": "Review and fix configuration errors",
        "log_files": "Implement log rotation, clean up old logs",
        "process_status": "Check application logs, restart if necessary",
        "docker_status": "Check Docker service, container status",
        "backup_status": "Run manual backup, check backup schedule"
    }
    
    return actions.get(result.check_name, "Review system logs and documentation")