from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.pip_standardizer import PipStandardizer, calculate_true_spread_pips


def test_spread_to_pips_for_five_digit_pair():
    spread_pips = calculate_true_spread_pips(
        "USD/CAD",
        ask=1.38471,
        bid=1.38462,
        digits=5,
        point=0.00001,
    )
    assert spread_pips == 0.9


def test_spread_to_pips_for_three_digit_jpy_pair():
    spread_pips = calculate_true_spread_pips(
        "USD/JPY",
        ask=151.237,
        bid=151.230,
        digits=3,
        point=0.001,
    )
    assert spread_pips == 0.7


def test_normalize_symbol_with_suffix():
    assert PipStandardizer.normalize_symbol("USD/CAD", ".a") == "USDCAD.a"
    assert PipStandardizer.normalize_symbol("usdjpy", ".ecn") == "USDJPY.ecn"
    assert PipStandardizer.normalize_symbol("EURUSD.ecn", ".ecn") == "EURUSD.ECN"
