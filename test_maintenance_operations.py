"""
Unit tests for maintenance operations and system diagnostics
"""

import asyncio
import json
import tempfile
import shutil
import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime, timedelta
from pathlib import Path

from src.maintenance.backup_system import (
    BackupManager, BackupType, BackupInfo, get_backup_manager,
    start_backup_system, stop_backup_system
)
from src.maintenance.strategy_updater import (
    StrategyUpdater, StrategyUpdate, UpdateStatus, get_strategy_updater
)
from src.maintenance.diagnostics import (
    SystemDiagnostics, DiagnosticResult, DiagnosticLevel,
    get_diagnostics, run_quick_diagnostics, generate_troubleshooting_guide
)


class TestBackupManager:
    """Test cases for BackupManager class"""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def backup_manager(self, temp_dir):
        """Create BackupManager instance for testing"""
        return BackupManager(backup_dir=str(Path(temp_dir) / "backups"))
    
    def test_backup_manager_initialization(self, backup_manager):
        """Test BackupManager initialization"""
        assert backup_manager.backup_dir.exists()
        assert backup_manager.backup_history == []
        assert not backup_manager.running
        assert backup_manager._scheduler_task is None
    
    def test_backup_info_creation(self):
        """Test BackupInfo creation"""
        now = datetime.now()
        backup_info = BackupInfo(
            backup_id="test_backup",
            backup_type=BackupType.CONFIGURATION,
            timestamp=now,
            file_path="/path/to/backup.tar.gz",
            size_bytes=1024,
            checksum="abc123",
            metadata={"test": "data"}
        )
        
        assert backup_info.backup_id == "test_backup"
        assert backup_info.backup_type == BackupType.CONFIGURATION
        assert backup_info.timestamp == now
        assert backup_info.file_path == "/path/to/backup.tar.gz"
        assert backup_info.size_bytes == 1024
        assert backup_info.checksum == "abc123"
        assert backup_info.metadata == {"test": "data"}
    
    @pytest.mark.asyncio
    async def test_create_backup_configuration(self, backup_manager, temp_dir):
        """Test creating configuration backup"""
        # Create test config directory
        config_dir = Path(temp_dir) / "config"
        config_dir.mkdir()
        (config_dir / "test.json").write_text('{"test": "config"}')
        
        # Change to temp directory for test
        import os
        original_cwd = os.getcwd()
        os.chdir(temp_dir)
        
        try:
            backup_info = await backup_manager.backup_configuration()
            
            assert backup_info.backup_type == BackupType.CONFIGURATION
            assert backup_info.backup_id.startswith("config_")
            assert Path(backup_info.file_path).exists()
            assert backup_info.size_bytes > 0
            assert len(backup_manager.backup_history) == 1
        finally:
            os.chdir(original_cwd)
    
    @pytest.mark.asyncio
    async def test_create_backup_trade_history(self, backup_manager, temp_dir):
        """Test creating trade history backup"""
        # Create test data directory
        data_dir = Path(temp_dir) / "data"
        data_dir.mkdir()
        (data_dir / "trades.db").write_text("test trade data")
        
        import os
        original_cwd = os.getcwd()
        os.chdir(temp_dir)
        
        try:
            backup_info = await backup_manager.backup_trade_history()
            
            assert backup_info.backup_type == BackupType.TRADE_HISTORY
            assert backup_info.backup_id.startswith("trades_")
            assert Path(backup_info.file_path).exists()
            assert backup_info.size_bytes > 0
        finally:
            os.chdir(original_cwd)
    
    @pytest.mark.asyncio
    async def test_backup_manager_start_stop(self, backup_manager):
        """Test starting and stopping backup manager"""
        assert not backup_manager.running
        
        await backup_manager.start()
        assert backup_manager.running
        assert backup_manager._scheduler_task is not None
        
        await backup_manager.stop()
        assert not backup_manager.running
        # Task might be cancelled but not immediately set to None
        assert backup_manager._scheduler_task is None or backup_manager._scheduler_task.cancelled()
    
    def test_list_backups(self, backup_manager):
        """Test listing backups"""
        # Add test backup to history
        backup_info = BackupInfo(
            backup_id="test_backup",
            backup_type=BackupType.CONFIGURATION,
            timestamp=datetime.now(),
            file_path="/test/path",
            size_bytes=1024
        )
        backup_manager.backup_history.append(backup_info)
        
        # Test listing all backups
        all_backups = backup_manager.list_backups()
        assert len(all_backups) == 1
        assert all_backups[0].backup_id == "test_backup"
        
        # Test listing by type
        config_backups = backup_manager.list_backups(BackupType.CONFIGURATION)
        assert len(config_backups) == 1
        
        trade_backups = backup_manager.list_backups(BackupType.TRADE_HISTORY)
        assert len(trade_backups) == 0
    
    def test_get_backup_info(self, backup_manager):
        """Test getting backup info"""
        backup_info = BackupInfo(
            backup_id="test_backup",
            backup_type=BackupType.CONFIGURATION,
            timestamp=datetime.now(),
            file_path="/test/path",
            size_bytes=1024
        )
        backup_manager.backup_history.append(backup_info)
        
        # Test getting existing backup
        found_backup = backup_manager.get_backup_info("test_backup")
        assert found_backup is not None
        assert found_backup.backup_id == "test_backup"
        
        # Test getting non-existent backup
        not_found = backup_manager.get_backup_info("nonexistent")
        assert not_found is None
    
    @pytest.mark.asyncio
    async def test_cleanup_old_backups(self, backup_manager):
        """Test cleaning up old backups"""
        # Create old backup
        old_backup = BackupInfo(
            backup_id="old_backup",
            backup_type=BackupType.CONFIGURATION,
            timestamp=datetime.now() - timedelta(days=35),
            file_path=str(backup_manager.backup_dir / "old_backup.tar.gz"),
            size_bytes=1024
        )
        
        # Create recent backup
        recent_backup = BackupInfo(
            backup_id="recent_backup",
            backup_type=BackupType.CONFIGURATION,
            timestamp=datetime.now() - timedelta(days=5),
            file_path=str(backup_manager.backup_dir / "recent_backup.tar.gz"),
            size_bytes=1024
        )
        
        # Create backup files
        Path(old_backup.file_path).touch()
        Path(recent_backup.file_path).touch()
        
        backup_manager.backup_history = [old_backup, recent_backup]
        
        await backup_manager.cleanup_old_backups()
        
        # Old backup should be removed, recent should remain
        assert len(backup_manager.backup_history) == 1
        assert backup_manager.backup_history[0].backup_id == "recent_backup"
        assert not Path(old_backup.file_path).exists()
        assert Path(recent_backup.file_path).exists()
    
    def test_get_backup_statistics(self, backup_manager):
        """Test getting backup statistics"""
        # Add test backups
        backup1 = BackupInfo(
            backup_id="backup1",
            backup_type=BackupType.CONFIGURATION,
            timestamp=datetime.now() - timedelta(days=1),
            file_path="/test/path1",
            size_bytes=1024
        )
        backup2 = BackupInfo(
            backup_id="backup2",
            backup_type=BackupType.TRADE_HISTORY,
            timestamp=datetime.now(),
            file_path="/test/path2",
            size_bytes=2048
        )
        
        backup_manager.backup_history = [backup1, backup2]
        
        stats = backup_manager.get_backup_statistics()
        
        assert stats["total_backups"] == 2
        assert stats["total_size_bytes"] == 3072
        assert stats["by_type"]["configuration"]["count"] == 1
        assert stats["by_type"]["trade_history"]["count"] == 1
        assert stats["oldest_backup"] is not None
        assert stats["newest_backup"] is not None


class TestStrategyUpdater:
    """Test cases for StrategyUpdater class"""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def strategy_updater(self, temp_dir):
        """Create StrategyUpdater instance for testing"""
        return StrategyUpdater(strategies_dir=str(Path(temp_dir) / "strategies"))
    
    def test_strategy_updater_initialization(self, strategy_updater):
        """Test StrategyUpdater initialization"""
        assert strategy_updater.strategies_dir.exists()
        assert strategy_updater.active_strategies == {}
        assert strategy_updater.strategy_versions == {}
        assert strategy_updater.update_history == []
    
    def test_register_strategy(self, strategy_updater):
        """Test registering a strategy"""
        mock_strategy = Mock()
        strategy_updater.register_strategy("test_strategy", mock_strategy, "1.0.0")
        
        assert "test_strategy" in strategy_updater.active_strategies
        assert strategy_updater.active_strategies["test_strategy"] == mock_strategy
        assert strategy_updater.strategy_versions["test_strategy"] == "1.0.0"
    
    def test_unregister_strategy(self, strategy_updater):
        """Test unregistering a strategy"""
        mock_strategy = Mock()
        strategy_updater.register_strategy("test_strategy", mock_strategy, "1.0.0")
        strategy_updater.unregister_strategy("test_strategy")
        
        assert "test_strategy" not in strategy_updater.active_strategies
        assert "test_strategy" not in strategy_updater.strategy_versions
    
    def test_add_remove_update_callback(self, strategy_updater):
        """Test adding and removing update callbacks"""
        callback = Mock()
        
        strategy_updater.add_update_callback(callback)
        assert callback in strategy_updater.update_callbacks
        
        strategy_updater.remove_update_callback(callback)
        assert callback not in strategy_updater.update_callbacks
    
    @pytest.mark.asyncio
    async def test_update_strategy_parameters(self, strategy_updater):
        """Test updating strategy parameters"""
        mock_strategy = AsyncMock()
        strategy_updater.register_strategy("test_strategy", mock_strategy, "1.0.0")
        
        parameters = {"param1": "value1", "param2": 42}
        result = await strategy_updater.update_strategy_parameters("test_strategy", parameters)
        
        assert result is True
        mock_strategy.update_parameters.assert_called_once_with(parameters)
    
    @pytest.mark.asyncio
    async def test_update_strategy_parameters_not_found(self, strategy_updater):
        """Test updating parameters for non-existent strategy"""
        result = await strategy_updater.update_strategy_parameters("nonexistent", {})
        assert result is False
    
    def test_get_active_strategies(self, strategy_updater):
        """Test getting active strategies"""
        mock_strategy = Mock()
        strategy_updater.register_strategy("test_strategy", mock_strategy, "1.0.0")
        
        active = strategy_updater.get_active_strategies()
        assert active == {"test_strategy": "1.0.0"}
    
    def test_get_strategy_instance(self, strategy_updater):
        """Test getting strategy instance"""
        mock_strategy = Mock()
        strategy_updater.register_strategy("test_strategy", mock_strategy, "1.0.0")
        
        instance = strategy_updater.get_strategy_instance("test_strategy")
        assert instance == mock_strategy
        
        not_found = strategy_updater.get_strategy_instance("nonexistent")
        assert not_found is None
    
    def test_list_updates(self, strategy_updater):
        """Test listing updates"""
        update1 = StrategyUpdate(
            update_id="update1",
            strategy_name="strategy1",
            version="1.0.0",
            timestamp=datetime.now(),
            status=UpdateStatus.COMPLETED,
            description="Test update"
        )
        update2 = StrategyUpdate(
            update_id="update2",
            strategy_name="strategy2",
            version="1.0.0",
            timestamp=datetime.now(),
            status=UpdateStatus.COMPLETED,
            description="Test update"
        )
        
        strategy_updater.update_history = [update1, update2]
        
        # Test listing all updates
        all_updates = strategy_updater.list_updates()
        assert len(all_updates) == 2
        
        # Test listing by strategy name
        strategy1_updates = strategy_updater.list_updates("strategy1")
        assert len(strategy1_updates) == 1
        assert strategy1_updates[0].update_id == "update1"
    
    def test_get_update_info(self, strategy_updater):
        """Test getting update info"""
        update = StrategyUpdate(
            update_id="test_update",
            strategy_name="test_strategy",
            version="1.0.0",
            timestamp=datetime.now(),
            status=UpdateStatus.COMPLETED,
            description="Test update"
        )
        strategy_updater.update_history = [update]
        
        found_update = strategy_updater.get_update_info("test_update")
        assert found_update is not None
        assert found_update.update_id == "test_update"
        
        not_found = strategy_updater.get_update_info("nonexistent")
        assert not_found is None
    
    def test_get_update_statistics(self, strategy_updater):
        """Test getting update statistics"""
        updates = [
            StrategyUpdate(
                update_id="update1",
                strategy_name="strategy1",
                version="1.0.0",
                timestamp=datetime.now(),
                status=UpdateStatus.COMPLETED,
                description="Test"
            ),
            StrategyUpdate(
                update_id="update2",
                strategy_name="strategy1",
                version="1.1.0",
                timestamp=datetime.now(),
                status=UpdateStatus.FAILED,
                description="Test"
            ),
            StrategyUpdate(
                update_id="update3",
                strategy_name="strategy2",
                version="1.0.0",
                timestamp=datetime.now(),
                status=UpdateStatus.ROLLED_BACK,
                description="Test"
            )
        ]
        
        strategy_updater.update_history = updates
        strategy_updater.strategy_versions = {"strategy1": "1.0.0", "strategy2": "1.0.0"}
        strategy_updater.active_strategies = {"strategy1": Mock(), "strategy2": Mock()}
        
        stats = strategy_updater.get_update_statistics()
        
        assert stats["total_updates"] == 3
        assert stats["successful_updates"] == 1
        assert stats["failed_updates"] == 1
        assert stats["rollbacks"] == 1
        assert stats["active_strategies"] == 2
        assert "strategy1" in stats["by_strategy"]
        assert "strategy2" in stats["by_strategy"]


class TestSystemDiagnostics:
    """Test cases for SystemDiagnostics class"""
    
    @pytest.fixture
    def diagnostics(self):
        """Create SystemDiagnostics instance for testing"""
        return SystemDiagnostics()
    
    def test_diagnostics_initialization(self, diagnostics):
        """Test SystemDiagnostics initialization"""
        assert diagnostics.diagnostic_results == []
    
    def test_diagnostic_result_creation(self):
        """Test DiagnosticResult creation"""
        result = DiagnosticResult(
            check_name="test_check",
            level=DiagnosticLevel.INFO,
            status="OK",
            message="Test message",
            details={"test": "data"}
        )
        
        assert result.check_name == "test_check"
        assert result.level == DiagnosticLevel.INFO
        assert result.status == "OK"
        assert result.message == "Test message"
        assert result.details == {"test": "data"}
        assert result.timestamp is not None
    
    @pytest.mark.asyncio
    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    async def test_check_system_resources(self, mock_memory, mock_cpu, diagnostics):
        """Test system resources check"""
        # Mock normal resource usage
        mock_cpu.return_value = 50.0
        mock_memory.return_value = Mock(percent=60.0, total=8*1024**3, available=3*1024**3)
        
        await diagnostics._check_system_resources()
        
        assert len(diagnostics.diagnostic_results) == 2
        cpu_result = next(r for r in diagnostics.diagnostic_results if r.check_name == "cpu_usage")
        memory_result = next(r for r in diagnostics.diagnostic_results if r.check_name == "memory_usage")
        
        assert cpu_result.level == DiagnosticLevel.INFO
        assert memory_result.level == DiagnosticLevel.INFO
    
    @pytest.mark.asyncio
    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    async def test_check_system_resources_high_usage(self, mock_memory, mock_cpu, diagnostics):
        """Test system resources check with high usage"""
        # Mock high resource usage
        mock_cpu.return_value = 95.0
        mock_memory.return_value = Mock(percent=95.0, total=8*1024**3, available=0.4*1024**3)
        
        await diagnostics._check_system_resources()
        
        cpu_result = next(r for r in diagnostics.diagnostic_results if r.check_name == "cpu_usage")
        memory_result = next(r for r in diagnostics.diagnostic_results if r.check_name == "memory_usage")
        
        assert cpu_result.level == DiagnosticLevel.CRITICAL
        assert memory_result.level == DiagnosticLevel.CRITICAL
    
    @pytest.mark.asyncio
    @patch('psutil.disk_usage')
    async def test_check_disk_space(self, mock_disk, diagnostics):
        """Test disk space check"""
        # Mock normal disk usage
        mock_disk.return_value = Mock(
            total=100*1024**3,
            used=50*1024**3,
            free=50*1024**3
        )
        
        await diagnostics._check_disk_space()
        
        assert len(diagnostics.diagnostic_results) == 1
        result = diagnostics.diagnostic_results[0]
        assert result.check_name == "disk_space"
        assert result.level == DiagnosticLevel.INFO
    
    @pytest.mark.asyncio
    @patch('socket.socket')
    async def test_check_network_connectivity(self, mock_socket, diagnostics):
        """Test network connectivity check"""
        # Mock successful connection
        mock_sock = Mock()
        mock_sock.connect_ex.return_value = 0
        mock_socket.return_value = mock_sock
        
        await diagnostics._check_network_connectivity()
        
        # Should have results for each test host
        network_results = [r for r in diagnostics.diagnostic_results if r.check_name.startswith("network_")]
        assert len(network_results) > 0
        
        for result in network_results:
            assert result.level == DiagnosticLevel.INFO
            assert result.status == "OK"
    
    @pytest.mark.asyncio
    async def test_check_database_connection(self, diagnostics):
        """Test database connection check"""
        await diagnostics._check_database_connection()
        
        assert len(diagnostics.diagnostic_results) == 1
        result = diagnostics.diagnostic_results[0]
        assert result.check_name == "database_connection"
        assert result.level == DiagnosticLevel.INFO
    
    @pytest.mark.asyncio
    @patch('requests.get')
    async def test_check_api_endpoints(self, mock_get, diagnostics):
        """Test API endpoints check"""
        # Mock successful API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_get.return_value = mock_response
        
        await diagnostics._check_api_endpoints()
        
        api_results = [r for r in diagnostics.diagnostic_results if r.check_name.startswith("api_")]
        assert len(api_results) > 0
        
        for result in api_results:
            assert result.level == DiagnosticLevel.INFO
            assert result.status == "OK"
    
    @pytest.mark.asyncio
    @patch('os.access')
    @patch('pathlib.Path.exists')
    async def test_check_file_permissions(self, mock_exists, mock_access, diagnostics):
        """Test file permissions check"""
        # Mock existing paths with proper permissions
        mock_exists.return_value = True
        mock_access.return_value = True
        
        await diagnostics._check_file_permissions()
        
        permission_results = [r for r in diagnostics.diagnostic_results if r.check_name.startswith("permissions_")]
        assert len(permission_results) > 0
        
        for result in permission_results:
            assert result.level == DiagnosticLevel.INFO
            assert result.status == "OK"
    
    @pytest.mark.asyncio
    @patch('psutil.Process')
    async def test_check_process_status(self, mock_process, diagnostics):
        """Test process status check"""
        # Mock process information
        mock_proc = Mock()
        mock_proc.status.return_value = "running"
        mock_proc.cpu_percent.return_value = 25.0
        mock_proc.memory_info.return_value = Mock(rss=100*1024**2)
        mock_proc.num_threads.return_value = 4
        mock_proc.pid = 1234
        mock_process.return_value = mock_proc
        
        await diagnostics._check_process_status()
        
        assert len(diagnostics.diagnostic_results) == 1
        result = diagnostics.diagnostic_results[0]
        assert result.check_name == "process_status"
        assert result.level == DiagnosticLevel.INFO
        assert result.status == "OK"
    
    @patch('platform.system')
    @patch('platform.release')
    @patch('psutil.cpu_count')
    @patch('psutil.virtual_memory')
    def test_get_system_info(self, mock_memory, mock_cpu_count, mock_release, mock_system, diagnostics):
        """Test getting system information"""
        # Mock system information
        mock_system.return_value = "Linux"
        mock_release.return_value = "5.4.0"
        mock_cpu_count.return_value = 4
        mock_memory.return_value = Mock(total=8*1024**3)
        
        with patch('psutil.disk_usage') as mock_disk:
            mock_disk.return_value = Mock(total=100*1024**3)
            
            system_info = diagnostics.get_system_info()
            
            assert "platform" in system_info
            assert "hardware" in system_info
            assert "network" in system_info
            assert "process" in system_info
            assert "timestamp" in system_info
    
    def test_generate_diagnostic_report(self, diagnostics):
        """Test generating diagnostic report"""
        # Add test results
        diagnostics.diagnostic_results = [
            DiagnosticResult("test1", DiagnosticLevel.INFO, "OK", "Test message 1"),
            DiagnosticResult("test2", DiagnosticLevel.WARNING, "WARNING", "Test message 2"),
            DiagnosticResult("test3", DiagnosticLevel.ERROR, "ERROR", "Test message 3")
        ]
        
        report = diagnostics.generate_diagnostic_report()
        
        assert "summary" in report
        assert "results_by_level" in report
        assert "system_info" in report
        assert report["summary"]["total_checks"] == 3
        assert len(report["results_by_level"]["info"]) == 1
        assert len(report["results_by_level"]["warning"]) == 1
        assert len(report["results_by_level"]["error"]) == 1


class TestMaintenanceIntegration:
    """Integration tests for maintenance components"""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.mark.asyncio
    async def test_backup_and_diagnostics_integration(self, temp_dir):
        """Test integration between backup system and diagnostics"""
        backup_manager = BackupManager(backup_dir=str(Path(temp_dir) / "backups"))
        diagnostics = SystemDiagnostics()
        
        # Create some test data
        config_dir = Path(temp_dir) / "config"
        config_dir.mkdir()
        (config_dir / "test.json").write_text('{"test": "config"}')
        
        import os
        original_cwd = os.getcwd()
        os.chdir(temp_dir)
        
        try:
            # Create backup
            await backup_manager.backup_configuration()
            
            # Run diagnostics
            await diagnostics.run_full_diagnostics()
            
            # Check that backup status is included in diagnostics
            backup_results = [r for r in diagnostics.diagnostic_results if r.check_name == "backup_status"]
            assert len(backup_results) == 1
            
        finally:
            os.chdir(original_cwd)
    
    def test_global_instances(self):
        """Test global instance functions"""
        # Test backup manager
        manager1 = get_backup_manager()
        manager2 = get_backup_manager()
        assert manager1 is manager2  # Should be singleton
        
        # Test strategy updater
        updater1 = get_strategy_updater()
        updater2 = get_strategy_updater()
        assert updater1 is updater2  # Should be singleton
        
        # Test diagnostics
        diag1 = get_diagnostics()
        diag2 = get_diagnostics()
        assert diag1 is diag2  # Should be singleton
    
    @pytest.mark.asyncio
    async def test_start_stop_backup_system(self):
        """Test starting and stopping backup system"""
        manager = await start_backup_system()
        assert manager.running
        
        await stop_backup_system()
        assert not manager.running
    
    @pytest.mark.asyncio
    async def test_run_quick_diagnostics(self):
        """Test running quick diagnostics"""
        results = await run_quick_diagnostics()
        assert isinstance(results, list)
        assert len(results) > 0
        
        for result in results:
            assert isinstance(result, DiagnosticResult)
    
    def test_generate_troubleshooting_guide(self):
        """Test generating troubleshooting guide"""
        guide = generate_troubleshooting_guide()
        assert isinstance(guide, dict)
        assert "common_issues" in guide
        assert "diagnostic_steps" in guide
        assert "contact_info" in guide


if __name__ == "__main__":
    pytest.main([__file__])
