from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis.ml_model import PriceMovementPredictor
from src.analysis.price_action_math import PriceActionMath, extract_price_action_features
from src.analysis.technical_indicators import TechnicalIndicators


def _build_bullish_pinbar_sequence() -> pd.DataFrame:
    rows = []
    base = 100.0
    for i in range(5):
        open_price = base + (i * 1.0)
        rows.append(
            {
                "open": open_price,
                "high": open_price + 0.15,
                "low": open_price - 0.60,
                "close": open_price + 0.10,
                "tick_volume": 250 + (i * 10),
            }
        )
        rows.append(
            {
                "open": open_price + 0.12,
                "high": open_price + 0.55,
                "low": open_price + 0.05,
                "close": open_price + 0.35,
                "tick_volume": 260 + (i * 10),
            }
        )

    last_open = base + 6.0
    rows.append(
        {
            "open": last_open,
            "high": last_open + 0.18,
            "low": last_open - 0.70,
            "close": last_open + 0.09,
            "tick_volume": 400,
        }
    )
    return pd.DataFrame(rows)


def test_extract_price_action_features_produces_normalized_finite_outputs():
    df = _build_bullish_pinbar_sequence()

    result = extract_price_action_features(df)

    required = {
        "body_ratio",
        "upper_wick_ratio",
        "lower_wick_ratio",
        "bullish_rejection_score",
        "bearish_rejection_score",
        "vpin_toxicity",
        "kurtosis_14",
        "micro_trend_slope_5",
        "micro_trend_slope_10",
        "log_return_1",
        "hurst_exponent_20",
        "rvi_14",
        "bullish_breakout_prob",
        "price_action_score",
    }
    assert required.issubset(result.columns)
    assert np.isfinite(result.to_numpy(dtype=float)).all()
    assert ((result["body_ratio"] >= 0.0) & (result["body_ratio"] <= 1.0)).all()
    assert ((result["upper_wick_ratio"] >= 0.0) & (result["upper_wick_ratio"] <= 1.0)).all()
    assert ((result["lower_wick_ratio"] >= 0.0) & (result["lower_wick_ratio"] <= 1.0)).all()


def test_get_attack_signal_detects_high_probability_bullish_rejection():
    df = _build_bullish_pinbar_sequence()

    signal = PriceActionMath.get_attack_signal(df)

    assert signal["action"] == "LONG"
    assert signal["probability"] > 0.65
    assert signal["confidence"] > 65.0


def test_ml_predictor_prepare_features_includes_price_action_columns():
    predictor = PriceMovementPredictor(symbol="EUR/USD")
    historical_data = []
    indicators = []

    for i in range(40):
        price = 1.1000 + (i * 0.0005)
        historical_data.append(
            SimpleNamespace(
                open=price,
                high=price + 0.0010,
                low=price - 0.0012,
                close=price + (0.0002 if i % 2 == 0 else -0.0001),
                volume=150 + i,
            )
        )
        indicators.append(
            TechnicalIndicators(
                symbol="EUR/USD",
                timestamp=pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=i),
                rsi=50.0 + (i % 5),
                adx=18.0 + (i % 7),
                williams_r=-45.0,
                macd_histogram=0.001,
                bollinger_upper=price + 0.0020,
                bollinger_lower=price - 0.0020,
                atr=0.0015,
            )
        )

    features = predictor.prepare_features(historical_data, indicators)

    expected_cols = {
        "body_ratio",
        "bullish_rejection_score",
        "momentum_strike",
        "micro_trend_vector",
        "log_return_1",
        "hurst_exponent_20",
        "rvi_14",
        "atr_relative",
        "bullish_breakout_prob",
        "price_action_score",
    }
    assert expected_cols.issubset(features.columns)
    assert np.isfinite(features.to_numpy(dtype=float)).all()


def test_ml_predictor_usdcad_uses_atr_relative_and_neutralizes_rvi():
    predictor = PriceMovementPredictor(symbol="USD/CAD")
    historical_data = []
    indicators = []

    for i in range(40):
        price = 1.2500 + (i * 0.0004)
        historical_data.append(
            SimpleNamespace(
                symbol="USD/CAD",
                open=price,
                high=price + 0.0010,
                low=price - 0.0010,
                close=price + 0.0002,
                volume=200 + i,
                spread=0.0002,
            )
        )
        indicators.append(
            TechnicalIndicators(
                symbol="USD/CAD",
                timestamp=pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=i),
                rsi=52.0,
                adx=20.0,
                williams_r=-45.0,
                macd_histogram=0.001,
                bollinger_upper=price + 0.0020,
                bollinger_lower=price - 0.0020,
                atr=0.0015,
            )
        )

    features = predictor.prepare_features(historical_data, indicators)

    assert "atr_relative" in features.columns
    assert "usdcad_body_ratio_focus" in features.columns
    assert "usdcad_tail_risk_focus" in features.columns
    assert "vpin_toxicity" in features.columns
    assert "kurtosis_14" in features.columns
    assert np.isfinite(features["atr_relative"].to_numpy(dtype=float)).all()
    assert (features["rvi_14"] == 50.0).all()
    assert (features["bearish_rejection_score"] == 0.0).all()


def test_ml_predictor_reuses_heuristic_signal_once_per_cycle():
    predictor = PriceMovementPredictor(symbol="EUR/USD")
    predictor._current_cycle_id = 7
    historical_data = [
        SimpleNamespace(close=1.1000),
        SimpleNamespace(close=1.1005),
    ]
    indicators = TechnicalIndicators(
        symbol="EUR/USD",
        timestamp=pd.Timestamp("2026-01-01"),
        rsi=35.0,
        adx=20.0,
        williams_r=-45.0,
        macd_histogram=0.001,
        bollinger_upper=1.1020,
        bollinger_lower=1.0980,
        atr=0.0015,
    )

    result_one = predictor.predict_with_details(historical_data, indicators)
    result_two = predictor.predict_with_details(historical_data, indicators)

    assert result_one == result_two
    assert predictor._last_heuristic_cycle_id == 7
