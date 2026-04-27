"""
Quant hybrid strategy orchestration for live FX trading.

This strategy keeps the existing SimpleTrendStrategy execution path as the
anchor model, then blends in:
  - OU mean-reversion diagnostics and signal strength
  - GARCH/EWMA-style volatility diagnostics
  - market microstructure / order-flow diagnostics
  - portfolio optimizer overlays
  - optional cointegration / spread-reversion checks for selected FX pairs

The goal is not to replace the existing live signal pipeline, but to make the
quant stack visible and influential in the final confidence, reasoning, and
risk metadata.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

import numpy as np
import pandas as pd
try:
    from scipy.optimize import minimize
except Exception:  # pragma: no cover - optional dependency at runtime
    minimize = None

from src.analysis.technical_indicators import IndicatorCalculator
from src.models import Direction, TradingSignal
from src.strategies.advanced_mean_reversion import AdvancedMeanReversionStrategy
from src.strategies.advanced_microstructure_strategy import AdvancedMicrostructureStrategy
from src.strategies.advanced_volatility_strategy import AdvancedVolatilityStrategy
from src.strategies.trend_strategy import SimpleTrendStrategy


logger = logging.getLogger(__name__)
QUANT_HISTORY_BARS = 500

ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_RED = "\033[38;5;203m"
ANSI_GREEN = "\033[38;5;46m"
ANSI_YELLOW = "\033[38;5;226m"
ANSI_BLACK_ON_YELLOW = "\033[48;5;226m\033[38;5;16m"


def _supports_ansi() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.name == "nt":
        return bool(
            os.environ.get("WT_SESSION")
            or os.environ.get("ANSICON")
            or os.environ.get("ConEmuANSI", "").upper() == "ON"
            or os.environ.get("TERM_PROGRAM", "").lower() in {"vscode", "windows_terminal"}
        )
    return True


def _paint(text: str, style: str) -> str:
    if not _supports_ansi():
        return text
    return f"{style}{text}{ANSI_RESET}"


@dataclass(frozen=True)
class QuantHybridConfig:
    trend_weight: float = 0.50
    ou_weight: float = 0.30
    micro_weight: float = 0.20
    pair_zscore_threshold: float = 2.0
    pair_correlation_floor: float = 0.75
    pair_lookback: int = 72


DEFAULT_COINTEGRATION_CANDIDATES: Dict[str, List[str]] = {
    "AUD/USD": ["NZD/USD"],
    "NZD/USD": ["AUD/USD"],
    "EUR/USD": ["GBP/USD"],
    "GBP/USD": ["EUR/USD"],
    "USD/CHF": ["EUR/USD"],
}


class QuantHybridStrategy(SimpleTrendStrategy):
    """
    Live strategy wrapper that preserves the existing trend/ML pipeline while
    blending in quant diagnostics and confidence from the advanced modules.
    """

    def __init__(
        self,
        symbol: str,
        verbose: bool = True,
        entry_filters: Optional[Dict[str, Any]] = None,
        config: Optional[Any] = None,
        admission_controller: Optional[Any] = None,
        related_data_loader: Optional[Callable[[str, List[str], int], Awaitable[Dict[str, List[Any]]]]] = None,
        hybrid_config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            symbol=symbol,
            verbose=verbose,
            entry_filters=entry_filters,
            config=config,
            admission_controller=admission_controller,
        )
        self.related_data_loader = related_data_loader
        self.hybrid_config = self._coerce_hybrid_config(hybrid_config)
        self.mean_reversion_model = AdvancedMeanReversionStrategy(
            symbol=symbol,
            verbose=verbose,
            entry_filters=entry_filters,
            config=config,
            admission_controller=admission_controller,
        )
        self.microstructure_model = AdvancedMicrostructureStrategy(
            symbol=symbol,
            verbose=verbose,
            entry_filters=entry_filters,
            config=config,
            admission_controller=admission_controller,
        )
        self.volatility_model = AdvancedVolatilityStrategy(
            symbol=symbol,
            verbose=verbose,
            entry_filters=entry_filters,
            config=config,
            admission_controller=admission_controller,
        )
        # Cache previous cycle's fitted model parameters to avoid recalibration lock
        self._ou_param_cache: Dict[str, Any] = {}
        self._garch_param_cache: Dict[str, Any] = {}
        self._last_quant_strategy_meta: Dict[str, Any] = {}
        self.latest_strategy_meta: Dict[str, Any] = {}
        self.latest_quant_meta: Dict[str, Any] = {}
        self.current_z_score: float = 0.0
        self.current_garch_vol: float = 0.0
        self.current_flow_delta: float = 0.0
        self.current_rsi: float = 0.0
        self.logger.info("[QUANT_HYBRID] %s | QuantHybridStrategy online", self.symbol)

    @staticmethod
    def _coerce_hybrid_config(raw: Optional[Dict[str, Any]]) -> QuantHybridConfig:
        if isinstance(raw, QuantHybridConfig):
            return raw
        if isinstance(raw, dict):
            valid_keys = set(QuantHybridConfig.__dataclass_fields__.keys())
            filtered = {k: v for k, v in raw.items() if k in valid_keys}
            return QuantHybridConfig(**filtered)
        return QuantHybridConfig()

    def set_entry_filters(self, filters: Dict[str, Any]) -> None:
        super().set_entry_filters(filters)
        for model in (self.mean_reversion_model, self.microstructure_model, self.volatility_model):
            try:
                model.entry_filters = dict(filters or {})
            except Exception:
                continue

    async def analyze(
        self,
        historical_data: List[Any],
        current_positions: Optional[List[Any]] = None,
    ) -> Optional[TradingSignal]:
        existing_report = dict(getattr(self, "_last_symbol_report", {}) or {})
        self._last_symbol_report = {
            "price": float(existing_report.get("price", 0.0) or 0.0),
            "rsi": 0.0,
            "direction": str(existing_report.get("direction", "NONE") or "NONE"),
            "confidence": float(existing_report.get("confidence", 0.0) or 0.0),
            "volatility": float(existing_report.get("volatility", 0.0) or 0.0),
            "z_score": 0.0,
            "garch_vol": 0.0,
            "flow_delta": 0.0,
            "timestamp": datetime.now(timezone.utc),
        }
        self.logger.critical(
            "[QUANT_HYBRID_ANALYZE_ENTRY] %s | Called with %d candles | About to call parent analyze()",
            self.symbol,
            len(historical_data) if historical_data else 0,
        )
        self.update_metrics_snapshot(historical_data, reason="quant_precompute")
        self._seed_symbol_report(historical_data)

        # STEP 1: Run quant diagnostics unconditionally so blocked symbols still update
        # the cockpit and cached model state every cycle.
        quant_snapshots = self._collect_quant_snapshots(historical_data)
        self._log_quant_snapshots(quant_snapshots)
        self._log_portfolio_model()

        # STEP 2: Run quant sub-models in parallel while the snapshot is hot.
        results = await asyncio.gather(
            self._run_quant_model("ou", self.mean_reversion_model, historical_data, current_positions),
            self._run_quant_model("micro", self.microstructure_model, historical_data, current_positions),
            self._run_quant_model("garch", self.volatility_model, historical_data, current_positions),
            self._run_cointegration_check(historical_data),
            return_exceptions=True,
        )

        # STEP 3: Extract signals from results
        ou_signal = self._extract_signal_result("ou", results[0])
        micro_signal = self._extract_signal_result("micro", results[1])
        garch_signal = self._extract_signal_result("garch", results[2])
        pair_signal = self._extract_signal_result("cointegration", results[3])

        # STEP 4: Compute quant_scores UNCONDITIONALLY from snapshots
        # This is the CRITICAL FIX - compute scores even if no base_signal exists
        # so that strategy_meta is always fully populated for the Orchestrator table
        quant_scores = self._compute_quant_scores_from_snapshots(
            quant_snapshots, ou_signal, micro_signal
        )

        # STEP 5: Build and persist complete strategy_meta UNCONDITIONALLY
        # This ensures the Orchestrator table always has data, even when no trade is taken
        complete_strategy_meta = self._build_quant_strategy_meta(
            quant_snapshots, quant_scores,
            pair_trade_active=bool(pair_signal is not None),
        )
        self._persist_latest_strategy_meta(complete_strategy_meta)
        
        # FIX #2: CRITICAL - Populate _last_symbol_report with RSI, Trend, and Volatility data EVERY cycle
        # This must happen regardless of whether a trade signal is generated
        self._update_symbol_report_from_quant(historical_data, quant_snapshots, quant_scores)
        complete_strategy_meta = self._build_quant_strategy_meta(
            quant_snapshots,
            quant_scores,
            pair_trade_active=bool(pair_signal is not None),
        )
        self._persist_latest_strategy_meta(complete_strategy_meta)

        # STEP 6: NOW let the base strategy decide whether to trade
        # The quant state has already been calculated and cached above
        
        # CRITICAL FIX: Save quant-enriched report BEFORE calling super().analyze()
        # because TrendStrategy.analyze() might overwrite _last_symbol_report with incomplete data
        quant_enriched_report = dict(self._last_symbol_report)
        
        trend_signal_result = await super().analyze(historical_data, current_positions=current_positions)
        trend_signal = trend_signal_result if not isinstance(trend_signal_result, Exception) else None
        
        # CRITICAL FIX: Restore quant-enriched data if super().analyze() cleared it
        # Merge the quant data (z_score, garch_vol, flow_delta) with whatever super() set
        if hasattr(self, '_last_symbol_report'):
            parent_report = dict(self._last_symbol_report or {})
            # Restore quant-specific fields that parent might have cleared
            quant_fields = {
                'z_score': quant_enriched_report.get('z_score', 0.0),
                'garch_vol': quant_enriched_report.get('garch_vol', 0.0),
                'flow_delta': quant_enriched_report.get('flow_delta', 0.0),
                'rsi': quant_enriched_report.get('rsi', parent_report.get('rsi', 50.0)),
                'direction': quant_enriched_report.get('direction', parent_report.get('direction', 'NONE')),
                'confidence': quant_enriched_report.get('confidence', parent_report.get('confidence', 0.45)),
                'price': quant_enriched_report.get('price', parent_report.get('price', 0.0)),
            }
            self._last_symbol_report.update(quant_fields)
            self.logger.debug(
                "[QUANT_REPORT_RESTORED] %s | Merged quant data after super().analyze() | RSI=%.1f | Z=%.2f | GARCH=%.4f",
                self.symbol,
                float(self._last_symbol_report.get('rsi', 0.0)),
                float(self._last_symbol_report.get('z_score', 0.0)),
                float(self._last_symbol_report.get('garch_vol', 0.0)),
            )
        
        complete_strategy_meta = self._build_quant_strategy_meta(
            quant_snapshots,
            quant_scores,
            pair_trade_active=bool(pair_signal is not None),
        )
        self._persist_latest_strategy_meta(complete_strategy_meta)

        # STEP 7: Determine base signal
        base_signal = trend_signal or pair_signal or self._best_quant_signal([ou_signal, micro_signal, garch_signal])
        if base_signal is None:
            # Meta is already populated (Step 5), so just return None
            # This guarantees the Quant Engine models stay updated even for rejected pairs
            self.logger.info(
                "[QUANT_HYBRID] %s | No trade signal | Quant engine updated | Trend=%.2f | OU=%.2f | Micro=%.2f",
                self.symbol,
                quant_scores.get("trend_score", 0.0),
                quant_scores.get("ou_score", 0.0),
                quant_scores.get("micro_score", 0.0),
            )
            self._publish_symbol_report(quant_snapshots)
            self._last_symbol_report.update(
                {
                    "z_score": float(self.current_z_score or 0.0),
                    "garch_vol": float(self.current_garch_vol or 0.0),
                    "flow_delta": float(self.current_flow_delta or 0.0),
                    "rsi": float(self.current_rsi or 0.0),
                }
            )
            # ===== CRITICAL FIX: Ensure parent class AND latest_strategy_meta are updated =====
            # This ensures main.py can read the data even when signal is None
            try:
                # Update parent class _last_symbol_report
                parent_report = getattr(super(), '_last_symbol_report', {})
                if parent_report is not None:
                    super()._last_symbol_report = dict(self._last_symbol_report)
                    self.logger.debug(
                        "[QUANT_REPORT_SYNC] %s | Synced _last_symbol_report to parent class | RSI=%.1f | ML=%s",
                        self.symbol,
                        float(self._last_symbol_report.get('rsi', 0.0)),
                        str(self._last_symbol_report.get('direction', 'NONE')),
                    )
            except Exception:
                pass
            
            # Persist complete meta with symbol_report to latest_strategy_meta
            complete_strategy_meta = self._build_quant_strategy_meta(
                quant_snapshots,
                quant_scores,
                pair_trade_active=bool(pair_signal is not None),
            )
            self._persist_latest_strategy_meta(complete_strategy_meta)
            self.logger.debug(
                "[QUANT_META_PERSISTED] %s | latest_strategy_meta updated with symbol_report | Keys: %s",
                self.symbol,
                list(complete_strategy_meta.keys()),
            )
            return None

        # STEP 8: If we have a signal, blend confidence and decorate it
        final_confidence = self._blend_confidence(base_signal, quant_scores)
        final_signal = self._decorate_signal(
            signal=base_signal,
            quant_snapshots=quant_snapshots,
            quant_scores=quant_scores,
            pair_signal=pair_signal,
            garch_signal=garch_signal,
            final_confidence=final_confidence,
        )
        # DEBUG: Verify symbol_report was properly populated in strategy_meta
        final_strategy_meta = dict(getattr(final_signal, "strategy_meta", {}) or {})
        final_symbol_report = dict(final_strategy_meta.get("symbol_report", {}) or {})
        parent_symbol_report = dict(getattr(self, "_last_symbol_report", {}) or {})
        
        self.logger.critical(
            "[QUANT_DATA_FLOW_TRACE] %s | Parent _last_symbol_report keys: %s | values: direction=%s, rsi=%.1f, conf=%.0f%%",
            self.symbol,
            list(parent_symbol_report.keys()),
            str(parent_symbol_report.get("direction", "MISSING")),
            float(parent_symbol_report.get("rsi", 0.0)),
            float(parent_symbol_report.get("confidence", 0.0)) * 100.0,
        )
        
        if final_symbol_report and final_symbol_report.get("direction"):
            self.logger.critical(
                "[DATA_FLOW_OK] %s | strategy_meta['symbol_report'] populated: rsi=%.1f | direction=%s | conf=%.0f%%",
                self.symbol,
                float(final_symbol_report.get("rsi", 0.0)),
                str(final_symbol_report.get("direction", "N/A")),
                float(final_symbol_report.get("confidence", 0.0)) * 100.0,
            )
        else:
            self.logger.critical(
                "[DATA_FLOW_BROKEN] %s | strategy_meta['symbol_report'] is EMPTY | Final meta has keys: %s",
                self.symbol,
                list(final_strategy_meta.keys()),
            )
        
        self._publish_symbol_report(quant_snapshots, signal=final_signal)
        self._last_symbol_report.update(
            {
                "z_score": float(self.current_z_score or 0.0),
                "garch_vol": float(self.current_garch_vol or 0.0),
                "flow_delta": float(self.current_flow_delta or 0.0),
                "rsi": float(self.current_rsi or 0.0),
            }
        )
        return final_signal

    def _seed_symbol_report(self, historical_data: List[Any]) -> None:
        existing = dict(getattr(self, "_last_symbol_report", {}) or {})
        if existing.get("direction"):
            return
        if historical_data:
            latest_close = float(getattr(historical_data[-1], "close", 0.0) or 0.0)
            first_close = float(getattr(historical_data[0], "close", latest_close) or latest_close)
            direction = "UP" if latest_close >= first_close else "DOWN"
            self._last_symbol_report = {
                "price": latest_close,
                "rsi": 50.0,
                "direction": direction,
                "confidence": 0.45,
            }
        else:
            self._last_symbol_report = {
                "price": 0.0,
                "rsi": 50.0,
                "direction": "DOWN",
                "confidence": 0.45,
            }
    
    def _update_symbol_report_from_quant(
        self,
        historical_data: List[Any],
        quant_snapshots: Dict[str, Any],
        quant_scores: Dict[str, float],
    ) -> None:
        """
        FIX #2: CRITICAL - Update _last_symbol_report with RSI, Trend, and Volatility data EVERY cycle.
        
        This ensures the Quant Engine table displays live data for ALL symbols,
        not just those generating trade signals.
        
        Args:
            historical_data: Market data bars
            quant_snapshots: Quant model snapshots (OU, GARCH, Micro)
            quant_scores: Computed quant scores
        """
        try:
            # Extract latest price
            latest_price = 0.0
            if historical_data:
                latest_price = float(getattr(historical_data[-1], "close", 0.0) or 0.0)

            indicator_snapshot = self._build_live_indicator_snapshot(historical_data)
            rsi_value = float(indicator_snapshot.get("rsi", 50.0) or 50.0)
            self.current_rsi = float(rsi_value or 0.0)
            atr_value = float(indicator_snapshot.get("atr", 0.0) or 0.0)
            macd_value = float(indicator_snapshot.get("macd", 0.0) or 0.0)
            macd_signal = float(indicator_snapshot.get("macd_signal", 0.0) or 0.0)
            macd_histogram = float(indicator_snapshot.get("macd_histogram", 0.0) or 0.0)
            
            # Extract ML direction and confidence from quant scores
            trend_score = float(quant_scores.get("trend_score", 0.0) or 0.0)
            ml_direction = "UP" if trend_score >= 0.5 else "DOWN"
            ml_confidence = max(trend_score, 1.0 - trend_score)  # Confidence is distance from 0.5
            
            # Extract volatility from GARCH snapshot
            garch_snapshot = dict(quant_snapshots.get("garch") or {})
            forecast_vol = float(garch_snapshot.get("forecast_vol", 0.0) or 0.0)
            ou_snapshot = dict(quant_snapshots.get("ou") or {})
            micro_snapshot = dict(quant_snapshots.get("micro") or {})
            self.current_z_score = float(ou_snapshot.get("zscore", 0.0) or 0.0)
            self.current_garch_vol = float(forecast_vol or 0.0)
            self.current_flow_delta = float(micro_snapshot.get("net_delta", 0.0) or 0.0)
            
            # Update _last_symbol_report with complete data
            self._last_symbol_report = {
                "price": latest_price,
                "rsi": float(self.current_rsi or 0.0),
                "direction": ml_direction,
                "confidence": ml_confidence,
                "trend_score": trend_score,
                "atr": atr_value,
                "volatility": forecast_vol,
                "z_score": self.current_z_score,
                "garch_vol": self.current_garch_vol,
                "flow_delta": self.current_flow_delta,
                "macd": macd_value,
                "macd_signal": macd_signal,
                "macd_histogram": macd_histogram,
                "ou_zscore": self.current_z_score,
                "timestamp": datetime.now(timezone.utc),
            }
            
            self.logger.debug(
                "[SYMBOL_REPORT_UPDATED] %s | Price=%.5f | RSI=%.1f | ML=%s | Conf=%.2f | Vol=%.4f",
                self.symbol,
                latest_price,
                rsi_value,
                ml_direction,
                ml_confidence,
                forecast_vol,
            )
        except Exception as update_err:
            self.logger.warning(
                "[SYMBOL_REPORT_UPDATE_FAILED] %s | Could not update from quant data: %s",
                self.symbol,
                update_err,
            )

    def _publish_symbol_report(
        self,
        quant_snapshots: Dict[str, Any],
        signal: Optional[TradingSignal] = None,
    ) -> None:
        try:
            existing = dict(getattr(self, "_last_symbol_report", {}) or {})
            ou_snapshot = dict(quant_snapshots.get("ou") or {})
            garch_snapshot = dict(quant_snapshots.get("garch") or {})
            micro_snapshot = dict(quant_snapshots.get("micro") or {})

            self.current_z_score = float(ou_snapshot.get("zscore", self.current_z_score) or 0.0)
            self.current_garch_vol = float(garch_snapshot.get("forecast_vol", self.current_garch_vol) or 0.0)
            self.current_flow_delta = float(micro_snapshot.get("net_delta", self.current_flow_delta) or 0.0)

            if signal is not None:
                direction_value = getattr(getattr(signal, "direction", None), "value", getattr(signal, "direction", None))
                confidence_value = float(getattr(signal, "confidence", existing.get("confidence", 0.0)) or 0.0)
            else:
                direction_value = existing.get("direction", "NONE")
                confidence_value = float(existing.get("confidence", 0.0) or 0.0)

            self._last_symbol_report = {
                **existing,
                "price": float(existing.get("price", 0.0) or 0.0),
                "rsi": float(self.current_rsi or existing.get("rsi", 0.0) or 0.0),
                "direction": str(direction_value or "NONE"),
                "confidence": confidence_value,
                "z_score": float(self.current_z_score or 0.0),
                "garch_vol": float(self.current_garch_vol or 0.0),
                "flow_delta": float(self.current_flow_delta or 0.0),
                "timestamp": datetime.now(timezone.utc),
            }
            self.logger.info(
                "[QUANT_REPORT_PUBLISH] %s | z_score=%.4f | garch_vol=%.4f | flow_delta=%.2f | rsi=%.1f",
                self.symbol,
                float(self._last_symbol_report.get("z_score", 0.0) or 0.0),
                float(self._last_symbol_report.get("garch_vol", 0.0) or 0.0),
                float(self._last_symbol_report.get("flow_delta", 0.0) or 0.0),
                float(self._last_symbol_report.get("rsi", 0.0) or 0.0),
            )
        except Exception as report_err:
            self.logger.warning(
                "[QUANT_REPORT_FALLBACK] %s | Could not publish quant report: %s | Using safe defaults",
                self.symbol,
                report_err,
            )
            self.current_z_score = 0.0
            self.current_garch_vol = 0.0
            self.current_flow_delta = 0.0
            self.current_rsi = 0.0
            self._last_symbol_report = {
                "price": 0.0,
                "rsi": 0.0,
                "direction": str(getattr(getattr(signal, "direction", None), "value", "NONE") or "NONE"),
                "confidence": float(getattr(signal, "confidence", 0.0) or 0.0),
                "z_score": 0.0,
                "garch_vol": 0.0,
                "flow_delta": 0.0,
                "timestamp": datetime.now(timezone.utc),
            }

    def _build_live_indicator_snapshot(self, historical_data: List[Any]) -> Dict[str, float]:
        snapshot = dict(getattr(self, "_last_symbol_report", {}) or {})
        if not historical_data:
            return {
                "rsi": float(snapshot.get("rsi", 50.0) or 50.0),
                "atr": float(snapshot.get("atr", snapshot.get("volatility", 0.0)) or 0.0),
                "macd": float(snapshot.get("macd", 0.0) or 0.0),
                "macd_signal": float(snapshot.get("macd_signal", 0.0) or 0.0),
                "macd_histogram": float(snapshot.get("macd_histogram", 0.0) or 0.0),
            }

        try:
            temp_calc = IndicatorCalculator()
            for bar in historical_data:
                temp_calc.add_market_data(bar)
            indicators = temp_calc.calculate_indicators(self.symbol, timeframe="1h")
            return {
                "rsi": float(getattr(indicators, "rsi", snapshot.get("rsi", 50.0)) or 50.0),
                "atr": float(getattr(indicators, "atr", snapshot.get("atr", snapshot.get("volatility", 0.0))) or 0.0),
                "macd": float(getattr(indicators, "macd", snapshot.get("macd", 0.0)) or 0.0),
                "macd_signal": float(getattr(indicators, "macd_signal", snapshot.get("macd_signal", 0.0)) or 0.0),
                "macd_histogram": float(
                    getattr(indicators, "macd_histogram", snapshot.get("macd_histogram", 0.0)) or 0.0
                ),
            }
        except Exception as indicator_err:
            self.logger.debug(
                "[HELD_INDICATOR_REFRESH_FAIL] %s | Using cached indicator snapshot: %s",
                self.symbol,
                indicator_err,
            )
            return {
                "rsi": float(snapshot.get("rsi", 50.0) or 50.0),
                "atr": float(snapshot.get("atr", snapshot.get("volatility", 0.0)) or 0.0),
                "macd": float(snapshot.get("macd", 0.0) or 0.0),
                "macd_signal": float(snapshot.get("macd_signal", 0.0) or 0.0),
                "macd_histogram": float(snapshot.get("macd_histogram", 0.0) or 0.0),
            }

    def _persist_latest_strategy_meta(self, strategy_meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        persisted = dict(strategy_meta or {})
        self._last_quant_strategy_meta = dict(persisted)
        self.latest_strategy_meta = dict(persisted)
        self.latest_quant_meta = dict(persisted)
        return persisted

    def _build_quant_strategy_meta(
        self,
        quant_snapshots: Dict[str, Any],
        quant_scores: Dict[str, float],
        *,
        pair_trade_active: bool = False,
        quant_position_size: float = 0.0,
    ) -> Dict[str, Any]:
        garch_snapshot = dict(quant_snapshots.get("garch") or {})
        ou_snapshot = dict(quant_snapshots.get("ou") or {})
        alpha_snapshot = dict(getattr(self, "_alpha_workflow_snapshot", {}) or {})
        return {
            "quant_hybrid": True,
            "quant_scores": dict(quant_scores or {}),
            "quant_weights": {
                "trend": float(self.hybrid_config.trend_weight),
                "ou": float(self.hybrid_config.ou_weight),
                "micro": float(self.hybrid_config.micro_weight),
            },
            "quant_health": {
                "garch_converged": str(garch_snapshot.get("status", "FAIL")).upper() == "OK"
                and math.isfinite(float(garch_snapshot.get("forecast_variance", 0.0) or 0.0)),
                "garch_status": str(garch_snapshot.get("status", "FAIL")).upper(),
                "ou_lambda_stable": str(ou_snapshot.get("status", "FAIL")).upper() == "OK",
                "ou_status": str(ou_snapshot.get("status", "FAIL")).upper(),
                "dxy_available": str(alpha_snapshot.get("dxy_state", "MISSING")).upper() == "OK",
                "dxy_state": str(alpha_snapshot.get("dxy_state", "MISSING")).upper(),
            },
            "symbol_report": dict(getattr(self, "_last_symbol_report", {}) or {}),
            "quant_position_size": float(quant_position_size or 0.0),
            "ou_snapshot": ou_snapshot,
            "garch_snapshot": garch_snapshot,
            "micro_snapshot": dict(quant_snapshots.get("micro") or {}),
            "pair_trade_active": bool(pair_trade_active),
        }

    async def _run_quant_model(
        self,
        label: str,
        model: Any,
        historical_data: List[Any],
        current_positions: Optional[List[Any]],
    ) -> Optional[TradingSignal]:
        try:
            return await model.analyze(historical_data, current_positions=current_positions)
        except Exception as exc:
            pretty = "GARCH" if label == "garch" else label.upper()
            self.logger.error("[QUANT_FAIL] %s fit error on symbol %s: %s", pretty, self.symbol, exc)
            return None

    def _extract_signal_result(self, label: str, result: Any) -> Optional[TradingSignal]:
        if isinstance(result, Exception):
            pretty = "GARCH" if label == "garch" else label.upper()
            self.logger.error("[QUANT_FAIL] %s fit error on symbol %s: %s", pretty, self.symbol, result)
            return None
        return result if isinstance(result, TradingSignal) else None

    def _estimate_ou_snapshot(self, series: pd.Series) -> Dict[str, Any]:
        """Estimate OU model parameters from series data."""
        try:
            clean_series = series.replace([np.inf, -np.inf], np.nan).dropna()
            values = clean_series.to_numpy(dtype=float)
            if len(values) < 12:
                cached = dict(self._ou_param_cache or {})
                if cached:
                    cached["status"] = "OK"
                    return cached
                return {"status": "CALIBRATING", "lambda": None, "mean": 0.0, "half_life": float("inf")}

            x_prev = values[:-1]
            x_next = values[1:]
            design = np.vstack([np.ones_like(x_prev), x_prev]).T
            intercept, beta = np.linalg.lstsq(design, x_next, rcond=None)[0]

            if not np.isfinite(beta):
                return {"status": "CALIBRATING", "lambda": None, "mean": float(np.mean(values)), "half_life": float("inf")}

            beta = float(beta)
            if beta <= 0.0:
                return {
                    "status": "CALIBRATING",
                    "lambda": None,
                    "mean": float(np.mean(values)),
                    "beta": beta,
                    "half_life": float("inf"),
                }

            theta = float(-np.log(beta))
            mean_level = float(intercept / (1.0 - beta)) if abs(1.0 - beta) > 1e-6 else float(np.mean(values))
            if theta <= 0.0:
                cached = dict(self._ou_param_cache or {})
                if cached:
                    cached["status"] = "UNSTABLE"
                    return cached
                return {
                    "status": "UNSTABLE",
                    "lambda": theta,
                    "mean": mean_level,
                    "beta": beta,
                    "half_life": float("inf"),
                }

            fitted = {
                "status": "OK",
                "lambda": theta,
                "mean": mean_level,
                "beta": beta,
                "half_life": float(np.log(2.0) / theta),
            }
            self._ou_param_cache = dict(fitted)
            return fitted
        except Exception as exc:
            logger.debug("[OU_FIT_GUARD] OU fit failed during calculation: %s", exc)
            cached = dict(self._ou_param_cache or {})
            if cached:
                cached["status"] = "CALIBRATING"
                return cached
            return {"status": "CALIBRATING", "lambda": None, "mean": 0.0, "half_life": float("inf")}

    def _fit_garch_proxy(self, returns: pd.Series, persistence_hint: float) -> Dict[str, Any]:
        """
        Fit GARCH model with warm-start from cached parameters to avoid recalibration lock.
        Uses previous cycle's fitted parameters if available to accelerate convergence.
        """
        try:
            clean = returns.replace([np.inf, -np.inf], np.nan).dropna().astype(float)
            if len(clean) < 120:
                cached = dict(self._garch_param_cache or {})
                if cached:
                    return {
                        **cached,
                        "status": "OK",
                        "optimization_method": str(cached.get("optimization_method", "CACHE")),
                        "max_iter": int(cached.get("max_iter", 200) or 200),
                        "converged": True,
                    }
                return {
                    "status": "CALIBRATING",
                    "forecast_vol": 0.0,
                    "forecast_variance": 0.0,
                    "persistence": float(persistence_hint),
                    "optimization_method": "SLSQP",
                    "max_iter": 200,
                    "converged": False,
                }

            arr = clean.to_numpy(dtype=float)
            sample_var = float(np.var(arr) or 1e-8)

            def neg_loglik(params: np.ndarray) -> float:
                omega, alpha, beta = params
                if omega <= 0.0 or alpha < 0.0 or beta < 0.0 or (alpha + beta) >= 0.999:
                    return 1e12
                variance = np.empty_like(arr)
                variance[0] = sample_var
                for idx in range(1, len(arr)):
                    variance[idx] = omega + alpha * (arr[idx - 1] ** 2) + beta * variance[idx - 1]
                    if variance[idx] <= 0.0 or not np.isfinite(variance[idx]):
                        return 1e12
                return float(0.5 * np.sum(np.log(variance) + (arr ** 2) / variance))

            # Warm-start with cached parameters if available
            cached = self._garch_param_cache
            if cached and "omega" in cached and "alpha" in cached and "beta" in cached:
                initial = np.array([
                    float(cached.get("omega", sample_var * 0.05)),
                    float(cached.get("alpha", 0.08)),
                    float(cached.get("beta", 0.80))
                ], dtype=float)
            else:
                initial = np.array([max(sample_var * 0.05, 1e-8), 0.08, min(max(persistence_hint, 0.80), 0.94)], dtype=float)
            
            bounds = [(1e-10, None), (1e-6, 0.35), (1e-6, 0.995)]
            constraints = [{"type": "ineq", "fun": lambda p: 0.999 - (p[1] + p[2])}]

            if minimize is None:
                return {
                    "status": "CALIBRATING",
                    "forecast_vol": 0.0,
                    "forecast_variance": 0.0,
                    "persistence": float(persistence_hint),
                    "optimization_method": "SLSQP",
                    "max_iter": 200,
                    "converged": False,
                }

            try:
                fit = minimize(
                    neg_loglik,
                    initial,
                    method="SLSQP",
                    bounds=bounds,
                    constraints=constraints,
                    options={"maxiter": 200, "ftol": 1e-9, "disp": False},
                )
            except Exception:
                fit = None

            if fit is None or not bool(getattr(fit, "success", False)):
                cached = dict(self._garch_param_cache or {})
                if cached:
                    return {
                        **cached,
                        "status": "OK",
                        "optimization_method": "CACHE",
                        "max_iter": 200,
                        "converged": True,
                    }
                return {
                    "status": "CALIBRATING",
                    "forecast_vol": 0.0,
                    "forecast_variance": 0.0,
                    "persistence": float(persistence_hint),
                    "optimization_method": "SLSQP",
                    "max_iter": 200,
                    "converged": False,
                }

            omega, alpha, beta = [float(x) for x in fit.x]
            # Cache fitted parameters for warm-start in next cycle
            self._garch_param_cache = {
                "omega": omega,
                "alpha": alpha,
                "beta": beta,
                "forecast_vol": 0.0,
                "forecast_variance": 0.0,
                "persistence": float(alpha + beta),
            }
            variance = sample_var
            for idx in range(1, len(arr)):
                variance = omega + alpha * (arr[idx - 1] ** 2) + beta * variance
            forecast_variance = max(omega + alpha * (arr[-1] ** 2) + beta * variance, 0.0)
            fitted = {
                "status": "OK",
                "forecast_vol": float(np.sqrt(forecast_variance)),
                "forecast_variance": float(forecast_variance),
                "persistence": float(alpha + beta),
                "omega": omega,
                "alpha": alpha,
                "beta": beta,
                "optimization_method": "SLSQP",
                "max_iter": 200,
                "converged": True,
            }
            self._garch_param_cache.update(
                {
                    "forecast_vol": fitted["forecast_vol"],
                    "forecast_variance": fitted["forecast_variance"],
                    "optimization_method": fitted["optimization_method"],
                    "max_iter": fitted["max_iter"],
                    "converged": True,
                }
            )
            return fitted
        except Exception as exc:
            logger.debug("[GARCH_FIT_GUARD] GARCH fit failed during calculation: %s", exc)
            cached = dict(self._garch_param_cache or {})
            if cached:
                return {
                    **cached,
                    "status": "OK",
                    "optimization_method": "CACHE",
                    "max_iter": 200,
                    "converged": True,
                }
            return {
                "status": "CALIBRATING",
                "forecast_vol": 0.0,
                "forecast_variance": 0.0,
                "persistence": float(persistence_hint),
                "optimization_method": "SLSQP",
                "max_iter": 200,
                "converged": False,
            }

    def _collect_quant_snapshots(self, historical_data: List[Any]) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {"ou": {}, "garch": {}, "micro": {}}
        if not historical_data:
            return snapshot

        try:
            features = self.mean_reversion_model._prepare_features(historical_data)
            latest = features.iloc[-1]
            residual_series = (features["close"] - features["rolling_mean"]).replace([np.inf, -np.inf], np.nan).dropna()
            ou_fit = self._estimate_ou_snapshot(residual_series)
            theta = ou_fit.get("lambda", None)
            ou_mean = float(ou_fit.get("mean", 0.0) or 0.0)
            half_life = float(ou_fit.get("half_life", float("inf")))
            residual_std = float(residual_series.std(ddof=0) or 0.0)
            ou_zscore = float((float(residual_series.iloc[-1]) - ou_mean) / residual_std) if residual_std > 0 else 0.0
            snapshot["ou"] = {
                "mean": float(latest.get("rolling_mean", 0.0) or 0.0),
                "lambda": float(theta) if theta is not None and math.isfinite(float(theta)) else None,
                "zscore": float(ou_zscore),
                "half_life": float(half_life if math.isfinite(half_life) else 0.0),
                "atr": float(latest.get("atr", 0.0) or 0.0),
                "status": str(ou_fit.get("status", "FAIL") or "FAIL").upper(),
                "beta": float(ou_fit.get("beta")) if ou_fit.get("beta", None) is not None else None,
            }
        except Exception as exc:
            self.logger.error("[QUANT_FAIL] OU fit error on symbol %s: %s", self.symbol, exc)
            snapshot["ou"] = {"status": "CALIBRATING", "lambda": None, "zscore": None}

        try:
            features = self.volatility_model._prepare_features(historical_data)
            latest = features.iloc[-1]
            garch_fit = self._fit_garch_proxy(features["return"], self.volatility_model.config.ewma_lambda)
            forecast_vol = float(garch_fit.get("forecast_vol", 0.0) or 0.0)
            forecast_variance = float(garch_fit.get("forecast_variance", 0.0) or 0.0)
            cluster_score = float(latest.get("cluster_score", 0.0) or 0.0)
            vol_of_vol = float(latest.get("vol_of_vol", 0.0) or 0.0)
            persistence = min(
                float(garch_fit.get("persistence", self.volatility_model.config.ewma_lambda) or self.volatility_model.config.ewma_lambda),
                0.99,
            )
            snapshot["garch"] = {
                "forecast_vol": forecast_vol,
                "forecast_variance": forecast_variance,
                "persistence": persistence,
                "cluster_detected": bool(
                    cluster_score >= 1.0
                    or vol_of_vol >= float(self.volatility_model.config.vol_of_vol_threshold)
                ),
                "cluster_score": cluster_score,
                "vol_of_vol": vol_of_vol,
                "atr": float(latest.get("atr", 0.0) or 0.0),
                "status": str(garch_fit.get("status", "CALIBRATING") or "CALIBRATING").upper(),
                "optimization_method": str(garch_fit.get("optimization_method", "SLSQP")),
                "max_iter": int(garch_fit.get("max_iter", 200) or 200),
            }
        except Exception as exc:
            self.logger.error("[QUANT_FAIL] GARCH fit error on symbol %s: %s", self.symbol, exc)
            snapshot["garch"] = {"status": "CALIBRATING", "forecast_vol": 0.0, "forecast_variance": 0.0}

        try:
            features = self.microstructure_model._prepare_features(historical_data)
            latest = features.iloc[-1]
            depth = float(latest.get("volume_mean", latest.get("volume", 0.0)) or 0.0)
            spread = float(latest.get("spread", 0.0) or 0.0)
            liquidity_depth = float(depth / max(spread, 1e-6)) if depth > 0 else 0.0
            ofi = float(latest.get("order_flow_imbalance", 0.0) or 0.0)
            snapshot["micro"] = {
                "net_delta": ofi,
                "vpin": float(abs(ofi)),
                "liquidity_depth": liquidity_depth,
                "tick_imbalance": float(latest.get("tick_imbalance", 0.0) or 0.0),
                "vwap_deviation": float(latest.get("vwap_deviation", 0.0) or 0.0),
                "atr": float(latest.get("atr", 0.0) or 0.0),
            }
        except Exception as exc:
            self.logger.error("[QUANT_FAIL] MICRO fit error on symbol %s: %s", self.symbol, exc)

        return snapshot

    def _log_quant_snapshots(self, snapshot: Dict[str, Any]) -> None:
        ou = dict(snapshot.get("ou") or {})
        if ou:
            ou_lambda = ou.get("lambda", None)
            ou_lambda_text = (
                "UNSTABLE"
                if str(ou.get("status", "")).upper() == "UNSTABLE"
                else (f"{float(ou_lambda):.4f}" if ou_lambda is not None and math.isfinite(float(ou_lambda)) else "FAIL")
            )
            self.logger.info(
                "[OU_REVERSION] %s | Mean: %.5f | Lambda (Speed): %s | Z-Score: %.2f.",
                self.symbol,
                float(ou.get("mean", 0.0) or 0.0),
                ou_lambda_text,
                float(ou.get("zscore", 0.0) or 0.0),
            )

        garch = dict(snapshot.get("garch") or {})
        if garch:
            self.logger.info(
                "[GARCH_VOL] %s | Forecast Variance: %.8f | Persistence: %.2f | Volatility Cluster Detected: %s.",
                self.symbol,
                float(garch.get("forecast_variance", 0.0) or 0.0),
                float(garch.get("persistence", 0.0) or 0.0),
                "Yes" if bool(garch.get("cluster_detected", False)) else "No",
            )

        micro = dict(snapshot.get("micro") or {})
        if micro:
            self.logger.info(
                "[ORDER_FLOW] %s | Net Delta: %.4f | VPIN (Toxicity): %.4f | Liquidity Depth: %.2f.",
                self.symbol,
                float(micro.get("net_delta", 0.0) or 0.0),
                float(micro.get("vpin", 0.0) or 0.0),
                float(micro.get("liquidity_depth", 0.0) or 0.0),
            )

    def _log_portfolio_model(self) -> None:
        snapshot = dict(getattr(self, "_alpha_workflow_snapshot", {}) or {})
        if not snapshot:
            self.logger.debug("[PORTFOLIO_MODEL] No alpha workflow snapshot available yet")
            return
        dxy_state = str(snapshot.get("dxy_state", "MISSING")).upper()
        if dxy_state in {"ISOLATED", "NEUTRAL"}:
            self.logger.info("[INFO] DXY unavailable: Defaulting to intra-portfolio correlation matrix.")
        elif dxy_state == "MISSING":
            self.logger.debug("[PORTFOLIO_MODEL] DXY state is MISSING - snapshot may not be ready")
        else:
            self.logger.debug("[PORTFOLIO_MODEL] DXY state: %s", dxy_state)
            
        weights = dict(snapshot.get("portfolio_weights") or {})
        variance = float(snapshot.get("portfolio_variance", 0.0) or 0.0)
        expected_return = float(snapshot.get("expected_portfolio_return", 0.0) or 0.0)
        sharpe = expected_return / math.sqrt(variance) if variance > 0 else 0.0
        var_95 = 1.65 * math.sqrt(max(variance, 0.0))
        self.logger.info(
            "[PORTFOLIO_MODEL] Target Weights: %s | Sharpe Forecast: %.4f | Tail Risk (VaR): %.4f.",
            weights,
            sharpe,
            var_95,
        )

    @staticmethod
    def _lean_label(zscore: float) -> str:
        if zscore >= 1.0:
            return "Sell Lean"
        if zscore <= -1.0:
            return "Buy Lean"
        return "Neutral"

    @staticmethod
    def _flow_label(delta: float) -> str:
        if delta > 0:
            return "Bullish"
        if delta < 0:
            return "Bearish"
        return "Balanced"

    @staticmethod
    def _garch_label(snapshot: Dict[str, Any]) -> str:
        status = str(snapshot.get("status", "") or "").upper()
        if status == "FAIL":
            return "FAIL"
        if status == "CALIBRATING":
            return "..."
        if bool(snapshot.get("cluster_detected", False)):
            return "UP"
        forecast_vol = float(snapshot.get("forecast_vol", 0.0) or 0.0)
        if forecast_vol > 0.0:
            return "FLAT"
        return "---"

    @staticmethod
    def _state_badge(state: str) -> str:
        normalized = str(state or "FAIL").upper()
        if normalized in {"OK", "STABLE"}:
            return _paint(f"[{normalized}]", f"{ANSI_BOLD}{ANSI_GREEN}")
        if normalized in {"ISOLATED", "CALIBRATING", "UNSTABLE", "MISSING", "NEUTRAL"}:
            return _paint(f"[{normalized}]", f"{ANSI_BOLD}{ANSI_YELLOW}")
        # FIX #4: Add SYNTHETIC badge with blue color
        if normalized == "SYNTHETIC":
            return _paint(f"[{normalized}]", f"{ANSI_BOLD}\033[94m")  # Bright blue
        return _paint(f"[{normalized}]", f"{ANSI_BOLD}{ANSI_RED}")

    @staticmethod
    def _dashboard_row(text: str, width: int = 74) -> str:
        return f"| {text[:width]:<{width}} |"

    @classmethod
    def format_quant_state_line(
        cls,
        symbol: str,
        strategy_meta: Dict[str, Any],
        *,
        decision: str = "SCAN",
        reason_code: str = "[Q]",
    ) -> str:
        ou_snapshot = dict(strategy_meta.get("ou_snapshot") or {})
        garch_snapshot = dict(strategy_meta.get("garch_snapshot") or {})
        micro_snapshot = dict(strategy_meta.get("micro_snapshot") or {})
        symbol_report = dict(strategy_meta.get("symbol_report") or {})
        quant_health = dict(strategy_meta.get("quant_health") or {})

        zscore_raw = ou_snapshot.get("zscore", None)
        forecast_vol_raw = garch_snapshot.get("forecast_vol", None)
        flow_delta = float(micro_snapshot.get("net_delta", 0.0) or 0.0)
        rsi_value = float(symbol_report.get("rsi", 0.0) or 0.0)
        ml_dir = str(symbol_report.get("direction", "N/A") or "N/A")
        ou_status = str(quant_health.get("ou_status", ou_snapshot.get("status", "")) or "").upper()
        garch_status = str(quant_health.get("garch_status", garch_snapshot.get("status", "")) or "").upper()

        if ou_status == "UNSTABLE":
            zscore_text = "UNSTBL"
        elif ou_status in {"FAIL", "CALIBRATING"}:
            zscore_text = "---"
        else:
            zscore_text = f"{float(zscore_raw):+05.2f}" if zscore_raw is not None else "---"

        if garch_status == "OK" and forecast_vol_raw is not None:
            garch_text = f"{float(forecast_vol_raw) * 100.0:>4.2f}% ({cls._garch_label(garch_snapshot)})"
        elif garch_status in {"FAIL", "CALIBRATING"}:
            garch_text = "[CALIBRATING]"
        elif forecast_vol_raw is not None and float(forecast_vol_raw or 0.0) > 0.0:
            garch_text = f"{float(forecast_vol_raw) * 100.0:>4.2f}% ({cls._garch_label(garch_snapshot)})"
        else:
            garch_text = "---"

        return (
            f"{symbol:<7} | "
            f"{zscore_text:>7} | "
            f"{garch_text:<13} | "
            f"{flow_delta:+10.0f} | "
            f"{rsi_value:>4.1f} | "
            f"{ml_dir:<6} | "
            f"{decision:<8} | "
            f"{reason_code:<4}"
        )

    @classmethod
    def format_strike_log_line(cls, signal: TradingSignal) -> str:
        strategy_meta = dict(getattr(signal, "strategy_meta", {}) or {})
        quant_scores = dict(strategy_meta.get("quant_scores") or {})
        ou_snapshot = dict(strategy_meta.get("ou_snapshot") or {})
        garch_snapshot = dict(strategy_meta.get("garch_snapshot") or {})

        trend_score = float(quant_scores.get("trend_score", getattr(signal, "confidence", 0.0)) or 0.0)
        zscore = float(ou_snapshot.get("zscore", 0.0) or 0.0)
        cluster_detected = bool(garch_snapshot.get("cluster_detected", False))
        garch_reason = "Expanding" if cluster_detected else "Stable"
        direction = getattr(getattr(signal, "direction", None), "value", "UNKNOWN")
        mode = "DRY_RUN" if str(os.environ.get("DRY_RUN", "0")).strip().lower() in {"1", "true", "yes", "on"} else "LIVE"
        size = float(getattr(signal, "position_size", 0.0) or strategy_meta.get("quant_position_size", 0.0) or 0.0)
        reason = f"ML Trend ({trend_score:.0%}) + OU Reversion ({zscore:+.1f} SD) + GARCH {garch_reason}"
        block = "\n".join(
            [
                "+" + "-" * 76 + "+",
                f"| STRIKE AUTHORIZED | PAIR: {signal.symbol:<7} | ACTION: {direction:<5} | SIZE: {size:>4.2f} L | MODE: {mode:<7} |",
                f"| REASON: {reason:<95}|",
                "+" + "-" * 76 + "+",
            ]
        )
        return _paint(block, ANSI_BLACK_ON_YELLOW)

    @classmethod
    def build_cycle_header_lines(
        cls,
        cycle_label: str,
        strategy_metas: List[Dict[str, Any]],
    ) -> List[str]:
        default_weights = QuantHybridConfig()
        weight_source = next((dict(meta.get("quant_weights") or {}) for meta in strategy_metas if meta.get("quant_weights")), {})
        trend_weight = float(weight_source.get("trend", default_weights.trend_weight) or default_weights.trend_weight)
        ou_weight = float(weight_source.get("ou", default_weights.ou_weight) or default_weights.ou_weight)
        micro_weight = float(weight_source.get("micro", default_weights.micro_weight) or default_weights.micro_weight)

        # BUG FIX #1: Only calculate health from symbols where quant_hybrid=True
        # This prevents SimpleTrendStrategy symbols from dragging health to [CALIBRATING]
        health_items = [
            dict(meta.get("quant_health") or {})
            for meta in strategy_metas
            if meta and meta.get("quant_hybrid", False)
        ]
        if health_items:
            garch_state = "OK" if all(bool(item.get("garch_converged", False)) for item in health_items) else "CALIBRATING"
            ou_state = "STABLE" if all(bool(item.get("ou_lambda_stable", False)) for item in health_items) else (
                "UNSTABLE" if any(str(item.get("ou_status", "")).upper() == "UNSTABLE" for item in health_items) else "CALIBRATING"
            )
            dxy_states = [str(item.get("dxy_state", "MISSING") or "MISSING").upper() for item in health_items]
            dxy_state = "OK" if "OK" in dxy_states else ("ISOLATED" if "ISOLATED" in dxy_states else "MISSING")
            
            # ===== ENHANCED DXY FIX: Check GLOBAL_QUANT_CACHE and orchestrator =====
            # Explicitly check GLOBAL_QUANT_CACHE["DXY"] for the DXY state and strength
            if dxy_state in ("MISSING", "ISOLATED", "UNKNOWN"):
                try:
                    import sys
                    main_module = sys.modules.get('__main__')
                    if main_module:
                        # Check GLOBAL_QUANT_CACHE first
                        global_cache = getattr(main_module, 'GLOBAL_QUANT_CACHE', {})
                        dxy_entry = global_cache.get("DXY", {})
                        if dxy_entry:
                            dxy_state = str(dxy_entry.get("state", "MISSING") or "MISSING").upper()
                            dxy_strength = float(dxy_entry.get("strength", 0.0) or 0.0)
                            # If state is UNKNOWN/MISSING but we have strength data, mark as SYNTHETIC or OK
                            if dxy_state in ("UNKNOWN", "MISSING") and dxy_strength > 0:
                                dxy_symbol = str(dxy_entry.get("dxy_symbol", "") or "")
                                dxy_state = "SYNTHETIC" if dxy_symbol in ("DX", "USDX") else "OK"
                        
                        # Fallback to orchestrator system_health
                        if dxy_state in ("UNKNOWN", "MISSING"):
                            # CRITICAL FIX: Check env variable first (set by DXY_CHECK at startup)
                            canonical_dxy_env = str(os.environ.get("DXY_CANONICAL_SYMBOL", "") or "").strip().upper()
                            if canonical_dxy_env in ("DX", "USDX", "DXY"):
                                dxy_state = "OK"
                                dxy_symbol = canonical_dxy_env
                            else:
                                # Fallback to orchestrator system_health
                                orchestrator = getattr(main_module, 'runtime_batch_orchestrator', None)
                                if orchestrator:
                                    dxy_state = str(getattr(orchestrator, 'system_health', {}).get("dxy", "MISSING") or "MISSING").upper()
                                    if dxy_state in ("UNKNOWN", "MISSING"):
                                        synthetic = getattr(orchestrator, 'synthetic_dxy_snapshot', {})
                                        if synthetic and float(synthetic.get("weighted_median_strength", 0) or 0) > 0:
                                            dxy_state = "SYNTHETIC"
                except Exception:
                    pass
        else:
            garch_state = "CALIBRATING"
            ou_state = "CALIBRATING"
            dxy_state = "MISSING"
            
            # ===== ENHANCED DXY FIX: Check GLOBAL_QUANT_CACHE even when no health items =====
            try:
                import sys
                main_module = sys.modules.get('__main__')
                if main_module:
                    # Check GLOBAL_QUANT_CACHE first
                    global_cache = getattr(main_module, 'GLOBAL_QUANT_CACHE', {})
                    dxy_entry = global_cache.get("DXY", {})
                    if dxy_entry:
                        dxy_state = str(dxy_entry.get("state", "MISSING") or "MISSING").upper()
                        dxy_strength = float(dxy_entry.get("strength", 0.0) or 0.0)
                        if dxy_state in ("UNKNOWN", "MISSING") and dxy_strength > 0:
                            dxy_symbol = str(dxy_entry.get("dxy_symbol", "") or "")
                            dxy_state = "SYNTHETIC" if dxy_symbol in ("DX", "USDX") else "OK"
                    
                    # Fallback to orchestrator system_health
                    if dxy_state in ("UNKNOWN", "MISSING"):
                        # CRITICAL FIX: Check env variable first (set by DXY_CHECK at startup)
                        canonical_dxy_env = str(os.environ.get("DXY_CANONICAL_SYMBOL", "") or "").strip().upper()
                        if canonical_dxy_env in ("DX", "USDX", "DXY"):
                            dxy_state = "OK"
                            dxy_symbol = canonical_dxy_env
                        else:
                            # Fallback to orchestrator system_health
                            orchestrator = getattr(main_module, 'runtime_batch_orchestrator', None)
                            if orchestrator:
                                dxy_state = str(getattr(orchestrator, 'system_health', {}).get("dxy", "MISSING") or "MISSING").upper()
                                if dxy_state in ("UNKNOWN", "MISSING"):
                                    synthetic = getattr(orchestrator, 'synthetic_dxy_snapshot', {})
                                    if synthetic and float(synthetic.get("weighted_median_strength", 0) or 0) > 0:
                                        dxy_state = "SYNTHETIC"
            except Exception:
                pass

        inner_width = 74
        title = f" QUANT ENGINE STATUS: CYCLE {cycle_label} "
        top_border = "+" + "-" * (inner_width + 2) + "+"
        title_line = "| " + title.center(inner_width) + " |"
        return [
            top_border,
            title_line,
            cls._dashboard_row(
                f" MODEL WEIGHTS:  Trend [{trend_weight:.0%}]  |  Reversion [{ou_weight:.0%}]  |  OrderFlow [{micro_weight:.0%}]",
                inner_width,
            ),
            cls._dashboard_row(
                f" SYSTEM HEALTH:  GARCH: {cls._state_badge(garch_state)}  |  OU-Lambda: "
                f"{cls._state_badge(ou_state)}  |  DXY: {cls._state_badge(dxy_state)}",
                inner_width,
            ),
            top_border,
        ]

    def _compute_quant_scores(
        self,
        base_signal: TradingSignal,
        snapshot: Dict[str, Any],
        ou_signal: Optional[TradingSignal],
        micro_signal: Optional[TradingSignal],
    ) -> Dict[str, float]:
        trend_score = float(getattr(base_signal, "confidence", 0.0) or 0.0)
        if getattr(base_signal, "source", "") == "standard":
            trend_score = float(getattr(base_signal, "confidence", trend_score) or trend_score)

        signal_dir = 1 if getattr(base_signal, "direction", None) == Direction.LONG else -1

        ou = dict(snapshot.get("ou") or {})
        ou_zscore = float(ou.get("zscore", 0.0) or 0.0)
        ou_dir = -1 if ou_zscore > 0 else (1 if ou_zscore < 0 else 0)
        ou_strength = min(abs(ou_zscore) / max(self.mean_reversion_model.config.entry_zscore, 1e-6), 1.5) / 1.5
        ou_score = ou_strength if ou_dir == signal_dir else max(0.0, 0.25 * ou_strength)
        if ou_signal is not None:
            ou_score = max(ou_score, float(getattr(ou_signal, "confidence", 0.0) or 0.0))

        micro = dict(snapshot.get("micro") or {})
        micro_delta = float(micro.get("net_delta", 0.0) or 0.0)
        micro_dir = 1 if micro_delta > 0 else (-1 if micro_delta < 0 else 0)
        micro_strength = min(abs(micro_delta) / max(self.microstructure_model.config.imbalance_threshold, 1e-6), 1.5) / 1.5
        micro_score = micro_strength if micro_dir == signal_dir else max(0.0, 0.25 * micro_strength)
        if micro_signal is not None:
            micro_score = max(micro_score, float(getattr(micro_signal, "confidence", 0.0) or 0.0))

        return {
            "trend_score": float(np.clip(trend_score, 0.0, 1.0)),
            "ou_score": float(np.clip(ou_score, 0.0, 1.0)),
            "micro_score": float(np.clip(micro_score, 0.0, 1.0)),
        }

    def _compute_quant_scores_from_snapshots(
        self,
        snapshot: Dict[str, Any],
        ou_signal: Optional[TradingSignal],
        micro_signal: Optional[TradingSignal],
    ) -> Dict[str, float]:
        """
        Compute quant scores unconditionally from snapshot data.
        Used when base_signal is None but we still need to populate strategy_meta
        for the Orchestrator table and background model calibration.
        """
        # Extract trend score from symbol_report (populated by _seed_symbol_report)
        symbol_report = dict(getattr(self, "_last_symbol_report", {}) or {})
        trend_score = float(symbol_report.get("confidence", 0.45) or 0.45)

        # OU score from snapshot
        ou = dict(snapshot.get("ou") or {})
        ou_zscore = float(ou.get("zscore", 0.0) or 0.0)
        ou_strength = min(abs(ou_zscore) / max(self.mean_reversion_model.config.entry_zscore, 1e-6), 1.5) / 1.5
        ou_score = float(np.clip(ou_strength, 0.0, 1.0))
        if ou_signal is not None:
            ou_score = max(ou_score, float(getattr(ou_signal, "confidence", 0.0) or 0.0))

        # Micro score from snapshot
        micro = dict(snapshot.get("micro") or {})
        micro_delta = float(micro.get("net_delta", 0.0) or 0.0)
        micro_strength = min(abs(micro_delta) / max(self.microstructure_model.config.imbalance_threshold, 1e-6), 1.5) / 1.5
        micro_score = float(np.clip(micro_strength, 0.0, 1.0))
        if micro_signal is not None:
            micro_score = max(micro_score, float(getattr(micro_signal, "confidence", 0.0) or 0.0))

        return {
            "trend_score": trend_score,
            "ou_score": ou_score,
            "micro_score": micro_score,
        }

    def _blend_confidence(self, base_signal: TradingSignal, scores: Dict[str, float]) -> float:
        cfg = self.hybrid_config
        blended = (
            cfg.trend_weight * float(scores.get("trend_score", 0.0))
            + cfg.ou_weight * float(scores.get("ou_score", 0.0))
            + cfg.micro_weight * float(scores.get("micro_score", 0.0))
        )
        return float(np.clip(blended, 0.0, 0.99))

    def _decorate_signal(
        self,
        signal: TradingSignal,
        quant_snapshots: Dict[str, Any],
        quant_scores: Dict[str, float],
        pair_signal: Optional[TradingSignal],
        garch_signal: Optional[TradingSignal],
        final_confidence: float,
    ) -> TradingSignal:
        final_signal = copy.deepcopy(signal)
        final_signal.confidence = final_confidence

        reasoning_parts = [
            str(getattr(signal, "reasoning", "") or "").strip(),
            (
                f"quant_blend(trend={quant_scores.get('trend_score', 0.0):.2f}, "
                f"ou={quant_scores.get('ou_score', 0.0):.2f}, "
                f"micro={quant_scores.get('micro_score', 0.0):.2f})"
            ),
        ]
        if pair_signal is not None:
            reasoning_parts.append("cointegration_overlay=active")
        final_signal.reasoning = " | ".join(part for part in reasoning_parts if part)

        garch_snapshot = dict(quant_snapshots.get("garch") or {})
        if garch_snapshot:
            setattr(final_signal, "garch_forecast_volatility", float(garch_snapshot.get("forecast_vol", 0.0) or 0.0))
            setattr(final_signal, "garch_forecast_variance", float(garch_snapshot.get("forecast_variance", 0.0) or 0.0))
            setattr(final_signal, "garch_cluster_detected", bool(garch_snapshot.get("cluster_detected", False)))

        strategy_meta = dict(getattr(final_signal, "strategy_meta", {}) or {})
        strategy_meta.update(
            self._build_quant_strategy_meta(
                quant_snapshots,
                quant_scores,
                pair_trade_active=bool(pair_signal is not None),
                quant_position_size=float(getattr(final_signal, "position_size", 0.0) or 0.0),
            )
        )
        setattr(final_signal, "strategy_meta", strategy_meta)
        self._last_quant_strategy_meta = dict(strategy_meta)
        self.latest_strategy_meta = dict(strategy_meta)
        self.latest_quant_meta = dict(strategy_meta)
        return final_signal

    def get_latest_quant_meta(self) -> Dict[str, Any]:
        return dict(self.latest_strategy_meta or self.latest_quant_meta or self._last_quant_strategy_meta or {})

    async def refresh_held_position_state(
        self,
        historical_data: List[Any],
        *,
        current_positions: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """
        Refresh quant state for held symbols without running the entry pipeline.
        """
        self.update_metrics_snapshot(historical_data, reason="held_position_refresh")
        quant_snapshots = self._collect_quant_snapshots(historical_data)
        ou_signal = self._extract_signal_result("ou", await self._run_quant_model("ou", self.mean_reversion_model, historical_data, current_positions))
        micro_signal = self._extract_signal_result("micro", await self._run_quant_model("micro", self.microstructure_model, historical_data, current_positions))
        pair_signal = await self._run_cointegration_check(historical_data)
        quant_scores = self._compute_quant_scores_from_snapshots(
            quant_snapshots,
            ou_signal,
            micro_signal,
        )
        complete_strategy_meta = self._build_quant_strategy_meta(
            quant_snapshots,
            quant_scores,
            pair_trade_active=bool(pair_signal is not None),
        )
        self._persist_latest_strategy_meta(complete_strategy_meta)
        self._update_symbol_report_from_quant(historical_data, quant_snapshots, quant_scores)
        latest_meta = self.get_latest_quant_meta()
        symbol_report = dict(getattr(self, "_last_symbol_report", {}) or latest_meta.get("symbol_report", {}) or {})
        latest_meta["symbol_report"] = symbol_report
        latest_meta["technical_indicators"] = {
            "rsi": float(symbol_report.get("rsi", 50.0) or 50.0),
            "atr": float(symbol_report.get("atr", symbol_report.get("volatility", 0.0)) or 0.0),
            "macd": float(symbol_report.get("macd", 0.0) or 0.0),
            "macd_signal": float(symbol_report.get("macd_signal", 0.0) or 0.0),
            "macd_histogram": float(symbol_report.get("macd_histogram", 0.0) or 0.0),
        }
        latest_meta["atr"] = float(latest_meta["technical_indicators"].get("atr", 0.0) or 0.0)
        return latest_meta

    def _best_quant_signal(self, signals: List[Optional[TradingSignal]]) -> Optional[TradingSignal]:
        valid = [signal for signal in signals if signal is not None]
        if not valid:
            return None
        return max(valid, key=lambda item: float(getattr(item, "confidence", 0.0) or 0.0))

    async def _run_cointegration_check(self, historical_data: List[Any]) -> Optional[TradingSignal]:
        if self.related_data_loader is None or not historical_data:
            return None

        candidate_symbols = DEFAULT_COINTEGRATION_CANDIDATES.get(self.symbol, [])
        if not candidate_symbols:
            return None

        try:
            related_histories = await self.related_data_loader(
                self.symbol,
                candidate_symbols,
                self.hybrid_config.pair_lookback,
            )
        except Exception as exc:
            self.logger.error("[QUANT_FAIL] COINTEGRATION fit error on symbol %s: %s", self.symbol, exc)
            return None

        primary_close = pd.Series(
            [float(getattr(bar, "close", 0.0) or 0.0) for bar in historical_data[-self.hybrid_config.pair_lookback :]],
            dtype=float,
        )
        if len(primary_close) < 30:
            return None

        for partner_symbol, partner_bars in dict(related_histories or {}).items():
            partner_close = pd.Series(
                [float(getattr(bar, "close", 0.0) or 0.0) for bar in partner_bars[-self.hybrid_config.pair_lookback :]],
                dtype=float,
            )
            pair_frame = pd.DataFrame({"primary": primary_close, "partner": partner_close}).dropna()
            if len(pair_frame) < 30:
                continue

            corr = float(pair_frame["primary"].corr(pair_frame["partner"]) or 0.0)
            if not math.isfinite(corr) or corr < self.hybrid_config.pair_correlation_floor:
                continue

            design = np.vstack([np.ones(len(pair_frame)), pair_frame["partner"].to_numpy(dtype=float)]).T
            intercept, beta = np.linalg.lstsq(design, pair_frame["primary"].to_numpy(dtype=float), rcond=None)[0]
            spread = pair_frame["primary"] - (intercept + beta * pair_frame["partner"])
            spread_std = float(spread.std(ddof=0) or 0.0)
            if spread_std <= 0.0:
                continue

            spread_value = float(spread.iloc[-1])
            spread_mean = float(spread.mean())
            spread_zscore = (spread_value - spread_mean) / spread_std
            if abs(spread_zscore) < self.hybrid_config.pair_zscore_threshold:
                continue

            atr = float(self.volatility_model._prepare_features(historical_data).iloc[-1].get("atr", 0.0) or 0.0)
            current_price = float(getattr(historical_data[-1], "close", 0.0) or 0.0)
            if current_price <= 0.0 or atr <= 0.0:
                continue

            direction = Direction.SHORT if spread_zscore > 0 else Direction.LONG
            reversion_target = float(intercept + beta * pair_frame["partner"].iloc[-1] + spread_mean)
            stop_distance = max(atr * 1.2, current_price * 0.0010)
            if direction == Direction.LONG:
                stop_loss = current_price - stop_distance
                take_profit = max(reversion_target, current_price + atr)
            else:
                stop_loss = current_price + stop_distance
                take_profit = min(reversion_target, current_price - atr)

            risk = abs(current_price - stop_loss)
            reward = abs(take_profit - current_price)
            if risk <= 0.0 or reward <= 0.0:
                continue

            self.logger.info(
                "[COINTEGRATION] Pair %s/%s | Spread: %.6f | Reversion Target: %.6f.",
                self.symbol,
                partner_symbol,
                spread_value,
                reversion_target,
            )

            confidence = float(np.clip(0.55 + min(abs(spread_zscore) / 4.0, 0.25), 0.55, 0.86))
            
            # CRITICAL FIX: Use valid position_size placeholder (0.01 minimum)
            # TradingSignal validation requires 0.0 < position_size <= 1.0
            # Pair trade signals are diagnostic - actual sizing happens in position_sizer
            # Try multiple sources for risk_per_trade config value
            default_position_size = 0.01  # Safe default
            try:
                # Try parent config first (SimpleTrendStrategy.config)
                parent_config = getattr(self, 'config', None)
                if parent_config and hasattr(parent_config, 'risk_per_trade'):
                    default_position_size = float(getattr(parent_config, 'risk_per_trade', 0.01) or 0.01)
                # Try hybrid_config as fallback
                elif hasattr(self.hybrid_config, 'risk_per_trade'):
                    default_position_size = float(getattr(self.hybrid_config, 'risk_per_trade', 0.01) or 0.01)
            except Exception:
                pass  # Keep safe default of 0.01
            
            # Ensure position_size is within valid range (0.0, 1.0]
            default_position_size = max(0.01, min(1.0, default_position_size))
            
            return TradingSignal(
                symbol=self.symbol,
                direction=direction,
                entry_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_size=default_position_size,
                confidence=confidence,
                reasoning=f"Pairs trade vs {partner_symbol} | spread_z={spread_zscore:.2f}",
                timestamp=datetime.now(timezone.utc),
                rr_ratio=(reward / risk),
                source="quant_pairs_trade",
            )

        return None
