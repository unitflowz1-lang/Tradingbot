from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.mt5_manager import MT5Manager


def test_mt5_manager_formats_symbol_with_suffix():
    manager = MT5Manager(suffix=".a")
    assert manager.format_symbol("USD/CAD") == "USDCAD.a"
    assert manager.format_symbol("GBP-USD") == "GBPUSD.a"


def test_mt5_manager_formats_symbol_without_suffix():
    manager = MT5Manager(suffix="")
    assert manager.format_symbol("USD/JPY") == "USDJPY"
