"""
Automated backup system for configuration and trade history
"""

import asyncio
import json
import logging
import os
import shutil
import tarfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import schedule


class BackupType(Enum):
    """Types of backups"""
    CONFIGURATION = "configuration"
    TRADE_HISTORY = "trade_history"
    DATABASE = "database"
    LOGS = "logs"
    FULL_SYSTEM = "full_system"


@dataclass
class BackupInfo:
    """Information about a backup"""
    backup_id: str
    backup_type: BackupType
    timestamp: datetime
    file_path: str
    size_bytes: int
    checksum: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class BackupManager:
    """Manages automated backups of system components"""
    
    def __init__(self, backup_dir: str = "backups"):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(exist_ok=True)
        self.logger = logging.getLogger(__name__)
        self.backup_history: List[BackupInfo] = []
        self.running = False
        self._scheduler_task: Optional[asyncio.Task] = None
        
        # Backup retention settings
        self.retention_days = {
            BackupType.CONFIGURATION: 30,
            BackupType.TRADE_HISTORY: 90,
            BackupType.DATABASE: 7,
            BackupType.LOGS: 14,
            BackupType.FULL_SYSTEM: 30
        }
        
        # Load existing backup history
        self._load_backup_history()
        
        # Setup backup schedule
        self._setup_backup_schedule()
    
    def _load_backup_history(self):
        """Load backup history from file"""
        history_file = self.backup_dir / "backup_history.json"
        if history_file.exists():
            try:
                with open(history_file, 'r') as f:
                    data = json.load(f)
                    self.backup_history = [
                        BackupInfo(
                            backup_id=item['backup_id'],
                            backup_type=BackupType(item['backup_type']),
                            timestamp=datetime.fromisoformat(item['timestamp']),
                            file_path=item['file_path'],
                            size_bytes=item['size_bytes'],
                            checksum=item.get('checksum'),
                            metadata=item.get('metadata')
                        )
                        for item in data
                    ]
            except Exception as e:
                self.logger.error(f"Failed to load backup history: {e}")
    
    def _save_backup_history(self):
        """Save backup history to file"""
        history_file = self.backup_dir / "backup_history.json"
        try:
            data = []
            for backup in self.backup_history:
                item = asdict(backup)
                item['backup_type'] = backup.backup_type.value
                item['timestamp'] = backup.timestamp.isoformat()
                data.append(item)
            
            with open(history_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save backup history: {e}")
    
    def _setup_backup_schedule(self):
        """Setup automated backup schedule"""
        # Daily configuration backup at 2 AM
        schedule.every().day.at("02:00").do(
            lambda: asyncio.create_task(self.backup_configuration())
        )
        
        # Weekly trade history backup on Sunday at 3 AM
        schedule.every().sunday.at("03:00").do(
            lambda: asyncio.create_task(self.backup_trade_history())
        )
        
        # Daily database backup at 1 AM
        schedule.every().day.at("01:00").do(
            lambda: asyncio.create_task(self.backup_database())
        )
        
        # Weekly log backup on Saturday at 11 PM
        schedule.every().saturday.at("23:00").do(
            lambda: asyncio.create_task(self.backup_logs())
        )
        
        # Monthly full system backup on 1st at midnight (using weekly as approximation)
        schedule.every(4).weeks.do(
            lambda: asyncio.create_task(self.backup_full_system())
        )
    
    async def start(self):
        """Start the backup manager"""
        self.running = True
        self._scheduler_task = asyncio.create_task(self._run_scheduler())
        self.logger.info("Backup manager started")
    
    async def stop(self):
        """Stop the backup manager"""
        self.running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        self.logger.info("Backup manager stopped")
    
    async def _run_scheduler(self):
        """Run the backup scheduler"""
        while self.running:
            try:
                schedule.run_pending()
                await asyncio.sleep(60)  # Check every minute
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in backup scheduler: {e}")
                await asyncio.sleep(60)
    
    async def backup_configuration(self) -> BackupInfo:
        """Backup configuration files"""
        self.logger.info("Starting configuration backup...")
        
        backup_id = f"config_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_file = self.backup_dir / f"{backup_id}.tar.gz"
        
        try:
            with tarfile.open(backup_file, 'w:gz') as tar:
                # Backup config directory
                if Path("config").exists():
                    tar.add("config", arcname="config")
                
                # Backup environment files
                for env_file in [".env", ".env.prod", ".env.staging"]:
                    if Path(env_file).exists():
                        tar.add(env_file, arcname=env_file)
            
            backup_info = BackupInfo(
                backup_id=backup_id,
                backup_type=BackupType.CONFIGURATION,
                timestamp=datetime.now(),
                file_path=str(backup_file),
                size_bytes=backup_file.stat().st_size,
                metadata={"config_files": ["config/", ".env*"]}
            )
            
            self.backup_history.append(backup_info)
            self._save_backup_history()
            
            self.logger.info(f"Configuration backup completed: {backup_file}")
            return backup_info
            
        except Exception as e:
            self.logger.error(f"Configuration backup failed: {e}")
            if backup_file.exists():
                backup_file.unlink()
            raise
    
    async def backup_trade_history(self) -> BackupInfo:
        """Backup trade history data"""
        self.logger.info("Starting trade history backup...")
        
        backup_id = f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_file = self.backup_dir / f"{backup_id}.tar.gz"
        
        try:
            with tarfile.open(backup_file, 'w:gz') as tar:
                # Backup data directory
                if Path("data").exists():
                    tar.add("data", arcname="data")
                
                # Backup any CSV exports or trade files
                for pattern in ["*.csv", "trades_*.json", "positions_*.json"]:
                    for file_path in Path(".").glob(pattern):
                        tar.add(file_path, arcname=file_path.name)
            
            backup_info = BackupInfo(
                backup_id=backup_id,
                backup_type=BackupType.TRADE_HISTORY,
                timestamp=datetime.now(),
                file_path=str(backup_file),
                size_bytes=backup_file.stat().st_size,
                metadata={"data_files": ["data/", "*.csv", "trades_*.json"]}
            )
            
            self.backup_history.append(backup_info)
            self._save_backup_history()
            
            self.logger.info(f"Trade history backup completed: {backup_file}")
            return backup_info
            
        except Exception as e:
            self.logger.error(f"Trade history backup failed: {e}")
            if backup_file.exists():
                backup_file.unlink()
            raise
    
    async def backup_database(self) -> BackupInfo:
        """Backup database"""
        self.logger.info("Starting database backup...")
        
        backup_id = f"db_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_file = self.backup_dir / f"{backup_id}.sql"
        
        try:
            # This would normally use pg_dump or similar
            # For now, we'll create a placeholder
            with open(backup_file, 'w') as f:
                f.write(f"-- Database backup created at {datetime.now()}\n")
                f.write("-- This is a placeholder for actual database backup\n")
            
            backup_info = BackupInfo(
                backup_id=backup_id,
                backup_type=BackupType.DATABASE,
                timestamp=datetime.now(),
                file_path=str(backup_file),
                size_bytes=backup_file.stat().st_size,
                metadata={"database": "forex_bot", "format": "sql"}
            )
            
            self.backup_history.append(backup_info)
            self._save_backup_history()
            
            self.logger.info(f"Database backup completed: {backup_file}")
            return backup_info
            
        except Exception as e:
            self.logger.error(f"Database backup failed: {e}")
            if backup_file.exists():
                backup_file.unlink()
            raise
    
    async def backup_logs(self) -> BackupInfo:
        """Backup log files"""
        self.logger.info("Starting logs backup...")
        
        backup_id = f"logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_file = self.backup_dir / f"{backup_id}.tar.gz"
        
        try:
            with tarfile.open(backup_file, 'w:gz') as tar:
                # Backup logs directory
                if Path("logs").exists():
                    tar.add("logs", arcname="logs")
                
                # Backup any standalone log files
                for log_file in Path(".").glob("*.log"):
                    tar.add(log_file, arcname=log_file.name)
            
            backup_info = BackupInfo(
                backup_id=backup_id,
                backup_type=BackupType.LOGS,
                timestamp=datetime.now(),
                file_path=str(backup_file),
                size_bytes=backup_file.stat().st_size,
                metadata={"log_files": ["logs/", "*.log"]}
            )
            
            self.backup_history.append(backup_info)
            self._save_backup_history()
            
            self.logger.info(f"Logs backup completed: {backup_file}")
            return backup_info
            
        except Exception as e:
            self.logger.error(f"Logs backup failed: {e}")
            if backup_file.exists():
                backup_file.unlink()
            raise
    
    async def backup_full_system(self) -> BackupInfo:
        """Backup entire system"""
        self.logger.info("Starting full system backup...")
        
        backup_id = f"full_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_file = self.backup_dir / f"{backup_id}.tar.gz"
        
        try:
            with tarfile.open(backup_file, 'w:gz') as tar:
                # Exclude certain directories and files
                exclude_patterns = {
                    "__pycache__",
                    ".git",
                    ".pytest_cache",
                    "node_modules",
                    "backups",
                    "*.pyc",
                    "*.pyo"
                }
                
                def exclude_filter(tarinfo):
                    for pattern in exclude_patterns:
                        if pattern in tarinfo.name:
                            return None
                    return tarinfo
                
                # Add all files except excluded ones
                for item in Path(".").iterdir():
                    if item.name not in exclude_patterns:
                        tar.add(item, arcname=item.name, filter=exclude_filter)
            
            backup_info = BackupInfo(
                backup_id=backup_id,
                backup_type=BackupType.FULL_SYSTEM,
                timestamp=datetime.now(),
                file_path=str(backup_file),
                size_bytes=backup_file.stat().st_size,
                metadata={"backup_type": "full_system", "excluded": list(exclude_patterns)}
            )
            
            self.backup_history.append(backup_info)
            self._save_backup_history()
            
            self.logger.info(f"Full system backup completed: {backup_file}")
            return backup_info
            
        except Exception as e:
            self.logger.error(f"Full system backup failed: {e}")
            if backup_file.exists():
                backup_file.unlink()
            raise
    
    async def restore_backup(self, backup_id: str, target_dir: Optional[str] = None) -> bool:
        """Restore from backup"""
        backup_info = self.get_backup_info(backup_id)
        if not backup_info:
            self.logger.error(f"Backup not found: {backup_id}")
            return False
        
        backup_file = Path(backup_info.file_path)
        if not backup_file.exists():
            self.logger.error(f"Backup file not found: {backup_file}")
            return False
        
        target_path = Path(target_dir) if target_dir else Path(".")
        
        try:
            self.logger.info(f"Restoring backup {backup_id} to {target_path}")
            
            if backup_info.backup_type == BackupType.DATABASE:
                # Handle database restore
                self.logger.info("Database restore would be handled here")
            else:
                # Handle file restore
                with tarfile.open(backup_file, 'r:gz') as tar:
                    tar.extractall(path=target_path)
            
            self.logger.info(f"Backup {backup_id} restored successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to restore backup {backup_id}: {e}")
            return False
    
    def get_backup_info(self, backup_id: str) -> Optional[BackupInfo]:
        """Get information about a specific backup"""
        for backup in self.backup_history:
            if backup.backup_id == backup_id:
                return backup
        return None
    
    def list_backups(self, backup_type: Optional[BackupType] = None) -> List[BackupInfo]:
        """List available backups"""
        if backup_type:
            return [b for b in self.backup_history if b.backup_type == backup_type]
        return self.backup_history.copy()
    
    async def cleanup_old_backups(self):
        """Clean up old backups based on retention policy"""
        self.logger.info("Starting backup cleanup...")
        
        cleaned_count = 0
        for backup_type, retention_days in self.retention_days.items():
            cutoff_date = datetime.now() - timedelta(days=retention_days)
            
            old_backups = [
                b for b in self.backup_history
                if b.backup_type == backup_type and b.timestamp < cutoff_date
            ]
            
            for backup in old_backups:
                try:
                    backup_file = Path(backup.file_path)
                    if backup_file.exists():
                        backup_file.unlink()
                    
                    self.backup_history.remove(backup)
                    cleaned_count += 1
                    self.logger.info(f"Removed old backup: {backup.backup_id}")
                    
                except Exception as e:
                    self.logger.error(f"Failed to remove backup {backup.backup_id}: {e}")
        
        if cleaned_count > 0:
            self._save_backup_history()
            self.logger.info(f"Cleaned up {cleaned_count} old backups")
        else:
            self.logger.info("No old backups to clean up")
    
    def get_backup_statistics(self) -> Dict[str, Any]:
        """Get backup statistics"""
        stats = {
            "total_backups": len(self.backup_history),
            "total_size_bytes": sum(b.size_bytes for b in self.backup_history),
            "by_type": {},
            "oldest_backup": None,
            "newest_backup": None
        }
        
        # Statistics by type
        for backup_type in BackupType:
            type_backups = [b for b in self.backup_history if b.backup_type == backup_type]
            stats["by_type"][backup_type.value] = {
                "count": len(type_backups),
                "total_size_bytes": sum(b.size_bytes for b in type_backups)
            }
        
        # Oldest and newest backups
        if self.backup_history:
            sorted_backups = sorted(self.backup_history, key=lambda b: b.timestamp)
            stats["oldest_backup"] = sorted_backups[0].timestamp.isoformat()
            stats["newest_backup"] = sorted_backups[-1].timestamp.isoformat()
        
        return stats


# Global backup manager instance
_backup_manager: Optional[BackupManager] = None


def get_backup_manager(backup_dir: str = "backups") -> BackupManager:
    """Get global backup manager instance"""
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = BackupManager(backup_dir)
    return _backup_manager


async def start_backup_system(backup_dir: str = "backups") -> BackupManager:
    """Start the backup system"""
    manager = get_backup_manager(backup_dir)
    await manager.start()
    return manager


async def stop_backup_system():
    """Stop the backup system"""
    global _backup_manager
    if _backup_manager:
        await _backup_manager.stop()
        _backup_manager = None