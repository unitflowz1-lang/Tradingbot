#!/usr/bin/env python3
"""
Simple test to verify maintenance operations work
"""

import asyncio
import tempfile
import shutil
from pathlib import Path

from src.maintenance.backup_system import BackupManager, BackupType
from src.maintenance.strategy_updater import StrategyUpdater
from src.maintenance.diagnostics import SystemDiagnostics


async def test_backup_system():
    """Test backup system functionality"""
    print("Testing backup system...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        backup_manager = BackupManager(backup_dir=str(Path(temp_dir) / "backups"))
        
        # Test initialization
        assert backup_manager.backup_dir.exists()
        assert backup_manager.backup_history == []
        print("✓ Backup manager initialization")
        
        # Test start/stop
        await backup_manager.start()
        assert backup_manager.running
        await backup_manager.stop()
        assert not backup_manager.running
        print("✓ Backup manager start/stop")
        
        # Test backup statistics
        stats = backup_manager.get_backup_statistics()
        assert "total_backups" in stats
        print("✓ Backup statistics")
    
    print("Backup system tests passed!")


def test_strategy_updater():
    """Test strategy updater functionality"""
    print("Testing strategy updater...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        strategy_updater = StrategyUpdater(strategies_dir=str(Path(temp_dir) / "strategies"))
        
        # Test initialization
        assert strategy_updater.strategies_dir.exists()
        assert strategy_updater.active_strategies == {}
        print("✓ Strategy updater initialization")
        
        # Test strategy registration
        class MockStrategy:
            async def update_parameters(self, params):
                pass
        
        mock_strategy = MockStrategy()
        strategy_updater.register_strategy("test_strategy", mock_strategy, "1.0.0")
        assert "test_strategy" in strategy_updater.active_strategies
        print("✓ Strategy registration")
        
        # Test getting active strategies
        active = strategy_updater.get_active_strategies()
        assert active == {"test_strategy": "1.0.0"}
        print("✓ Get active strategies")
        
        # Test statistics
        stats = strategy_updater.get_update_statistics()
        assert "total_updates" in stats
        print("✓ Update statistics")
    
    print("Strategy updater tests passed!")


async def test_diagnostics():
    """Test diagnostics functionality"""
    print("Testing diagnostics...")
    
    diagnostics = SystemDiagnostics()
    
    # Test initialization
    assert diagnostics.diagnostic_results == []
    print("✓ Diagnostics initialization")
    
    # Test system info
    system_info = diagnostics.get_system_info()
    assert "platform" in system_info
    assert "hardware" in system_info
    print("✓ System info")
    
    # Test individual checks
    await diagnostics._check_system_resources()
    assert len(diagnostics.diagnostic_results) > 0
    print("✓ System resources check")
    
    # Test diagnostic report
    report = diagnostics.generate_diagnostic_report()
    assert "summary" in report
    assert "system_info" in report
    print("✓ Diagnostic report")
    
    print("Diagnostics tests passed!")


async def main():
    """Run all tests"""
    print("Running maintenance operations tests...\n")
    
    try:
        await test_backup_system()
        print()
        
        test_strategy_updater()
        print()
        
        await test_diagnostics()
        print()
        
        print("All maintenance operations tests passed! ✅")
        
    except Exception as e:
        print(f"Test failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())