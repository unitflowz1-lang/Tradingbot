from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.analysis.alpha_portfolio_optimizer import AdvancedAlphaPortfolioEngine


def _build_price_frame() -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=120, freq="D", tz="UTC")
    base = np.linspace(1.00, 1.25, 120)
    eur = base + np.sin(np.linspace(0, 10, 120)) * 0.02
    gbp = (base * 1.02) + np.sin(np.linspace(0, 9, 120)) * 0.018
    aud = 0.80 + np.sin(np.linspace(0, 14, 120)) * 0.03
    return pd.DataFrame(
        {
            "EUR/USD": eur,
            "GBP/USD": gbp,
            "AUD/USD": aud,
        },
        index=index,
    )


def test_generate_factor_alphas_creates_expected_columns():
    engine = AdvancedAlphaPortfolioEngine()
    prices = _build_price_frame()

    factors = engine.generate_factor_alphas(
        prices,
        carry_map={"EUR/USD": 1.0, "GBP/USD": 2.0},
    )

    assert "EUR/USD__momentum" in factors.columns
    assert "EUR/USD__mean_reversion" in factors.columns
    assert "EUR/USD__low_vol" in factors.columns
    assert "EUR/USD__carry" in factors.columns
    assert "GBP/USD__carry" in factors.columns


def test_apply_pca_reduces_dimensions():
    engine = AdvancedAlphaPortfolioEngine()
    prices = _build_price_frame()
    factors = engine.generate_factor_alphas(prices).dropna()

    result = engine.apply_pca(factors, variance_threshold=0.80)

    assert result.n_components >= 1
    assert result.n_components <= factors.shape[1]
    assert result.transformed.shape[1] == result.n_components
    assert float(np.sum(result.explained_variance_ratio)) <= 1.0 + 1e-8


def test_combine_alphas_blends_signals():
    engine = AdvancedAlphaPortfolioEngine()
    index = pd.date_range("2026-01-01", periods=5, freq="D", tz="UTC")
    alpha = engine.combine_alphas(
        {
            "momentum": pd.Series([1, 2, 3, 4, 5], index=index, dtype=float),
            "carry": pd.Series([2, 2, 2, 3, 4], index=index, dtype=float),
        },
        weights={"momentum": 0.7, "carry": 0.3},
    )

    assert len(alpha) == 5
    assert alpha.name == "ensemble_alpha"
    assert alpha.iloc[-1] > alpha.iloc[0]


def test_measure_alpha_decay_detects_fast_decay():
    engine = AdvancedAlphaPortfolioEngine()
    index = pd.date_range("2026-01-01", periods=50, freq="D", tz="UTC")
    alpha = pd.Series(np.sin(np.linspace(0, 4, 50)), index=index)
    forward_returns = alpha.shift(-1).fillna(0.0) * 0.8

    decay = engine.measure_alpha_decay(alpha, forward_returns, max_lag=5)

    assert 1 in decay.lag_correlations
    assert decay.decay_score >= 0.0


def test_kelly_fraction_is_capped_and_non_negative():
    engine = AdvancedAlphaPortfolioEngine(max_kelly_fraction=0.2)

    kelly = engine.kelly_fraction(win_rate=0.60, payoff_ratio=1.8, confidence_scale=0.8)

    assert 0.0 <= kelly <= 0.2


def test_estimate_feature_importance_returns_ranked_features():
    engine = AdvancedAlphaPortfolioEngine()
    prices = _build_price_frame()
    features = engine.generate_factor_alphas(prices).dropna()
    target = features["EUR/USD__momentum"].shift(-1).dropna()
    features = features.loc[target.index]

    importance = engine.estimate_feature_importance(features, target)

    assert not importance.blended_importance.empty
    assert abs(float(importance.blended_importance.sum()) - 1.0) < 1e-6


def test_optimize_portfolio_returns_valid_weights():
    engine = AdvancedAlphaPortfolioEngine(max_weight=0.6)
    expected_returns = pd.Series(
        {"EUR/USD": 0.08, "GBP/USD": 0.06, "AUD/USD": 0.04},
        dtype=float,
    )
    covariance = pd.DataFrame(
        [
            [0.040, 0.020, 0.010],
            [0.020, 0.050, 0.015],
            [0.010, 0.015, 0.030],
        ],
        index=expected_returns.index,
        columns=expected_returns.index,
        dtype=float,
    )

    result = engine.optimize_portfolio(expected_returns, covariance, kelly_scalar=0.75)

    assert not result.weights.empty
    assert float(result.weights.sum()) > 0.0
    assert (result.weights >= 0.0).all()
    assert result.expected_return >= 0.0


def test_build_expected_returns_from_alpha_aggregates_per_symbol():
    engine = AdvancedAlphaPortfolioEngine()
    prices = _build_price_frame()
    factors = engine.generate_factor_alphas(prices).dropna()

    expected = engine.build_expected_returns_from_alpha(factors)

    assert "EUR/USD" in expected.index
    assert "GBP/USD" in expected.index
    assert "AUD/USD" in expected.index
