"""
Advanced alpha generation and portfolio optimization utilities.

This module provides practical building blocks for:
  - factor-based alpha generation
  - PCA-based dimensionality reduction
  - ensemble alpha blending
  - alpha decay measurement
  - Kelly-style sizing
  - simple feature-importance estimation
  - constrained portfolio weight optimization

The implementation favors transparent, dependency-light methods that fit the
current codebase and can be used by strategy, backtesting, or RL layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PCAResult:
    transformed: pd.DataFrame
    explained_variance_ratio: np.ndarray
    components: pd.DataFrame
    n_components: int


@dataclass(frozen=True)
class AlphaDecayResult:
    lag_correlations: Dict[int, float]
    decay_half_life: float
    decay_score: float
    is_fast_decay: bool


@dataclass(frozen=True)
class FeatureImportanceResult:
    linear_importance: pd.Series
    correlation_importance: pd.Series
    blended_importance: pd.Series


@dataclass(frozen=True)
class PortfolioOptimizationResult:
    weights: pd.Series
    expected_return: float
    portfolio_variance: float
    diversification_ratio: float
    kelly_scalar: float


class AdvancedAlphaPortfolioEngine:
    """Utility engine for alpha research and portfolio construction."""

    def __init__(
        self,
        risk_aversion: float = 3.0,
        max_weight: float = 0.35,
        min_weight: float = 0.0,
        max_kelly_fraction: float = 0.25,
    ):
        self.risk_aversion = float(max(risk_aversion, 1e-6))
        self.max_weight = float(max_weight)
        self.min_weight = float(min_weight)
        self.max_kelly_fraction = float(max_kelly_fraction)

    @staticmethod
    def _zscore(series: pd.Series, window: int) -> pd.Series:
        rolling_mean = series.rolling(window).mean()
        rolling_std = series.rolling(window).std(ddof=0).mask(series.rolling(window).std(ddof=0) == 0.0)
        return (series - rolling_mean) / rolling_std

    @staticmethod
    def _standardize_frame(frame: pd.DataFrame) -> pd.DataFrame:
        std = frame.std(ddof=0).mask(frame.std(ddof=0) == 0.0)
        return (frame - frame.mean()) / std

    def generate_factor_alphas(
        self,
        prices: pd.DataFrame,
        *,
        carry_map: Optional[Dict[str, float]] = None,
        momentum_window: int = 20,
        mean_reversion_window: int = 10,
        volatility_window: int = 20,
    ) -> pd.DataFrame:
        """
        Generate factor-style alpha features from a price matrix.

        Returns a multi-column DataFrame with one alpha per factor/symbol pair.
        """
        if prices.empty:
            return pd.DataFrame(index=prices.index)

        returns = prices.pct_change()
        factor_columns: Dict[str, pd.Series] = {}

        for symbol in prices.columns:
            px = prices[symbol].astype(float)
            ret = returns[symbol].astype(float)

            momentum = px.pct_change(momentum_window)
            reversal = -self._zscore(px, mean_reversion_window)
            realized_vol = ret.rolling(volatility_window).std(ddof=0)
            low_vol = -self._zscore(realized_vol, volatility_window)

            factor_columns[f"{symbol}__momentum"] = momentum
            factor_columns[f"{symbol}__mean_reversion"] = reversal
            factor_columns[f"{symbol}__low_vol"] = low_vol

            if carry_map and symbol in carry_map:
                factor_columns[f"{symbol}__carry"] = pd.Series(
                    float(carry_map[symbol]),
                    index=prices.index,
                    dtype=float,
                )

        return pd.DataFrame(factor_columns, index=prices.index)

    def apply_pca(
        self,
        features: pd.DataFrame,
        *,
        variance_threshold: float = 0.90,
    ) -> PCAResult:
        """Reduce feature dimensionality with PCA using numpy linear algebra."""
        clean = features.mask(np.isinf(features)).dropna()
        if clean.empty:
            return PCAResult(
                transformed=pd.DataFrame(index=features.index),
                explained_variance_ratio=np.array([], dtype=float),
                components=pd.DataFrame(),
                n_components=0,
            )

        standardized = self._standardize_frame(clean).fillna(0.0)
        cov = np.cov(standardized.to_numpy(dtype=float), rowvar=False)
        eigenvalues, eigenvectors = np.linalg.eigh(cov)
        order = np.argsort(eigenvalues)[::-1]
        eigenvalues = eigenvalues[order]
        eigenvectors = eigenvectors[:, order]

        total_variance = float(np.sum(np.maximum(eigenvalues, 0.0)))
        if total_variance <= 0.0:
            explained = np.zeros(len(eigenvalues), dtype=float)
        else:
            explained = np.maximum(eigenvalues, 0.0) / total_variance

        cumulative = np.cumsum(explained)
        n_components = int(np.searchsorted(cumulative, variance_threshold) + 1)
        n_components = max(1, min(n_components, standardized.shape[1]))

        component_matrix = eigenvectors[:, :n_components]
        transformed_values = standardized.to_numpy(dtype=float) @ component_matrix
        transformed = pd.DataFrame(
            transformed_values,
            index=standardized.index,
            columns=[f"PC{i+1}" for i in range(n_components)],
        )
        components = pd.DataFrame(
            component_matrix.T,
            index=transformed.columns,
            columns=standardized.columns,
        )

        return PCAResult(
            transformed=transformed,
            explained_variance_ratio=explained[:n_components],
            components=components,
            n_components=n_components,
        )

    def combine_alphas(
        self,
        alpha_signals: Dict[str, pd.Series],
        *,
        weights: Optional[Dict[str, float]] = None,
    ) -> pd.Series:
        """Blend multiple alphas into one ensemble alpha."""
        if not alpha_signals:
            return pd.Series(dtype=float)

        frame = pd.DataFrame(alpha_signals).mask(np.isinf(pd.DataFrame(alpha_signals)))
        frame = frame.dropna(how="all")
        if frame.empty:
            return pd.Series(dtype=float)

        z_frame = self._standardize_frame(frame).fillna(0.0)
        if weights:
            raw_weights = np.array(
                [float(weights.get(col, 0.0)) for col in z_frame.columns],
                dtype=float,
            )
        else:
            raw_weights = np.ones(len(z_frame.columns), dtype=float)

        if float(np.sum(np.abs(raw_weights))) <= 0.0:
            raw_weights = np.ones(len(z_frame.columns), dtype=float)

        normalized_weights = raw_weights / float(np.sum(np.abs(raw_weights)))
        blended = z_frame.to_numpy(dtype=float) @ normalized_weights
        return pd.Series(blended, index=z_frame.index, name="ensemble_alpha", dtype=float)

    def measure_alpha_decay(
        self,
        alpha_series: pd.Series,
        forward_returns: pd.Series,
        *,
        max_lag: int = 10,
    ) -> AlphaDecayResult:
        """
        Measure alpha decay by correlating today's alpha with future returns.
        """
        aligned = pd.concat(
            [alpha_series.rename("alpha"), forward_returns.rename("fwd")],
            axis=1,
        )
        aligned = aligned.mask(np.isinf(aligned)).dropna()
        if len(aligned) < max_lag + 5:
            empty_lags = {lag: 0.0 for lag in range(1, max_lag + 1)}
            return AlphaDecayResult(
                lag_correlations=empty_lags,
                decay_half_life=float("inf"),
                decay_score=0.0,
                is_fast_decay=True,
            )

        lag_corrs: Dict[int, float] = {}
        for lag in range(1, max_lag + 1):
            shifted = aligned["fwd"].shift(-lag)
            pair = pd.concat([aligned["alpha"], shifted.rename("shifted")], axis=1).dropna()
            if len(pair) < 5:
                lag_corrs[lag] = 0.0
            else:
                lag_corrs[lag] = float(pair["alpha"].corr(pair["shifted"]) or 0.0)

        initial_strength = abs(lag_corrs.get(1, 0.0))
        if initial_strength <= 1e-8:
            half_life = float("inf")
        else:
            half_life = float("inf")
            for lag, corr in lag_corrs.items():
                if abs(corr) <= initial_strength * 0.5:
                    half_life = float(lag)
                    break

        avg_strength = float(np.mean([abs(v) for v in lag_corrs.values()])) if lag_corrs else 0.0
        return AlphaDecayResult(
            lag_correlations=lag_corrs,
            decay_half_life=half_life,
            decay_score=avg_strength,
            is_fast_decay=bool(np.isfinite(half_life) and half_life <= 3),
        )

    def kelly_fraction(
        self,
        *,
        win_rate: float,
        payoff_ratio: float,
        confidence_scale: float = 1.0,
    ) -> float:
        """Compute a capped Kelly-style fraction."""
        p = float(np.clip(win_rate, 0.0, 1.0))
        b = float(max(payoff_ratio, 1e-8))
        q = 1.0 - p
        raw_kelly = ((b * p) - q) / b
        scaled = max(0.0, raw_kelly) * float(max(confidence_scale, 0.0))
        return float(min(self.max_kelly_fraction, scaled))

    def estimate_feature_importance(
        self,
        features: pd.DataFrame,
        target: pd.Series,
    ) -> FeatureImportanceResult:
        """
        Estimate feature importance using standardized linear coefficients and
        simple target correlations.
        """
        data = features.copy()
        data["__target__"] = target
        clean = data.mask(np.isinf(data)).dropna()
        if clean.empty:
            empty = pd.Series(dtype=float)
            return FeatureImportanceResult(empty, empty, empty)

        x = clean.drop(columns="__target__")
        y = clean["__target__"].astype(float)
        x_std = self._standardize_frame(x).fillna(0.0)
        y_centered = y - y.mean()

        design = x_std.to_numpy(dtype=float)
        target_vec = y_centered.to_numpy(dtype=float)
        beta = np.linalg.lstsq(design, target_vec, rcond=None)[0]
        linear = pd.Series(np.abs(beta), index=x.columns, dtype=float)
        if float(linear.sum()) > 0.0:
            linear = linear / float(linear.sum())

        correlation = x.apply(lambda col: abs(float(col.corr(y) or 0.0)))
        if float(correlation.sum()) > 0.0:
            correlation = correlation / float(correlation.sum())

        blended = (linear.reindex(x.columns, fill_value=0.0) + correlation.reindex(x.columns, fill_value=0.0)) / 2.0
        if float(blended.sum()) > 0.0:
            blended = blended / float(blended.sum())

        return FeatureImportanceResult(
            linear_importance=linear.sort_values(ascending=False),
            correlation_importance=correlation.sort_values(ascending=False),
            blended_importance=blended.sort_values(ascending=False),
        )

    def optimize_portfolio(
        self,
        expected_returns: pd.Series,
        covariance: pd.DataFrame,
        *,
        kelly_scalar: float = 1.0,
    ) -> PortfolioOptimizationResult:
        """
        Compute long-only, capped portfolio weights from expected returns and covariance.
        """
        mu = expected_returns.astype(float)
        cov = covariance.loc[mu.index, mu.index].astype(float)

        if mu.empty:
            empty = pd.Series(dtype=float)
            return PortfolioOptimizationResult(empty, 0.0, 0.0, 0.0, 0.0)

        cov_values = cov.to_numpy(dtype=float)
        reg = np.eye(len(mu), dtype=float) * 1e-6
        inv_cov = np.linalg.pinv(cov_values + reg)
        raw = inv_cov @ mu.to_numpy(dtype=float)
        raw = raw / self.risk_aversion
        raw = np.maximum(raw, self.min_weight)

        if float(np.sum(raw)) <= 0.0:
            raw = np.ones(len(mu), dtype=float)

        weights = raw / float(np.sum(raw))
        weights = np.clip(weights, self.min_weight, self.max_weight)
        weights = weights / float(np.sum(weights))

        kelly_scalar = float(np.clip(kelly_scalar, 0.0, 1.0))
        final_weights = pd.Series(weights * kelly_scalar, index=mu.index, dtype=float)

        exp_return = float(final_weights @ mu)
        variance = float(final_weights.to_numpy(dtype=float) @ cov_values @ final_weights.to_numpy(dtype=float))
        asset_vol = np.sqrt(np.maximum(np.diag(cov_values), 0.0))
        portfolio_vol = float(np.sqrt(max(variance, 0.0)))
        diversification_ratio = (
            float(final_weights.to_numpy(dtype=float) @ asset_vol) / portfolio_vol
            if portfolio_vol > 0.0
            else 0.0
        )

        return PortfolioOptimizationResult(
            weights=final_weights,
            expected_return=exp_return,
            portfolio_variance=variance,
            diversification_ratio=diversification_ratio,
            kelly_scalar=kelly_scalar,
        )

    def build_expected_returns_from_alpha(
        self,
        alpha_scores: pd.DataFrame,
        *,
        latest_only: bool = True,
    ) -> pd.Series:
        """
        Aggregate factor alphas into per-symbol expected returns.
        """
        if alpha_scores.empty:
            return pd.Series(dtype=float)

        source = alpha_scores.tail(1) if latest_only else alpha_scores
        symbol_scores: Dict[str, float] = {}
        for col in source.columns:
            if "__" not in col:
                continue
            symbol, _factor = col.split("__", 1)
            symbol_scores.setdefault(symbol, 0.0)
            symbol_scores[symbol] += float(source[col].mean() or 0.0)

        expected = pd.Series(symbol_scores, dtype=float)
        if not expected.empty and float(expected.abs().sum()) > 0.0:
            expected = expected / float(expected.abs().sum())
        return expected.sort_values(ascending=False)
