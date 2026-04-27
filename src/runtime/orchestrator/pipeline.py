import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from src.models import ExecutionResult, OrderType
from src.runtime.contracts.commands import ExecutionPlan, SignalIntent
from src.runtime.contracts.decisions import RiskDecision
from src.runtime.contracts.snapshots import MarketSnapshot, PortfolioSnapshot
from src.runtime.execution.execution_gateway import ExecutionGateway
from src.runtime.risk.policy_engine import RiskPolicyEngine
from src.runtime.signal.signal_engine import SignalEngine
from src.strategies.quant_hybrid_strategy import QuantHybridStrategy


@dataclass
class PipelineOutcome:
    intents_total: int = 0
    intents_approved: int = 0
    executed: int = 0
    execution_results: List[ExecutionResult] = None

    def __post_init__(self) -> None:
        if self.execution_results is None:
            self.execution_results = []


class TradingPipeline:
    """Phase 1 pipeline shell: signal -> risk -> execution."""

    def __init__(
        self,
        signal_engine: SignalEngine,
        risk_engine: RiskPolicyEngine,
        execution_gateway: ExecutionGateway,
    ):
        self.signal_engine = signal_engine
        self.risk_engine = risk_engine
        self.execution_gateway = execution_gateway
        self.logger = logging.getLogger(__name__)

    async def run_once(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioSnapshot,
    ) -> PipelineOutcome:
        outcome = PipelineOutcome()
        intents = await self.signal_engine.generate(market)
        outcome.intents_total = len(intents)

        for intent in intents:
            risk: RiskDecision = self.risk_engine.evaluate(intent, portfolio, market)
            if not risk.approved:
                continue

            outcome.intents_approved += 1
            plan = self._build_plan(intent, risk)
            result = await self.execution_gateway.submit(plan)
            outcome.execution_results.append(result)
            if result.success:
                outcome.executed += 1

        return outcome

    def _build_plan(self, intent: SignalIntent, risk: RiskDecision) -> ExecutionPlan:
        return ExecutionPlan(
            symbol=intent.symbol,
            side=intent.side,
            qty_lots=max(risk.capped_qty_lots, 0.01),
            entry_type=OrderType.MARKET,
            sl=None,
            tp=None,
            client_order_id=f"rt_{intent.symbol}_{intent.side.value}",
            entry_price=intent.entry_ref,
            metadata={"risk_reason": risk.reason_code, "priority": intent.priority},
        )


class LegacySymbolBatchOrchestrator:
    """
    Phase 4 extraction: symbol batch orchestration wrapper around legacy analyzer.

    This keeps the existing per-symbol analyzer logic in main.py, but moves
    concurrent fan-out/fan-in and queue assembly into runtime/orchestrator.
    """

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        strategy_state_provider: Optional[Callable[[str], Dict[str, Any]]] = None,
        quant_cache: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        self.logger = logger or logging.getLogger(__name__)
        self.strategy_state_provider = strategy_state_provider
        self.quant_cache = quant_cache  # GLOBAL_QUANT_CACHE reference
        self.use_synthetic_dxy = True
        
        # ===== FIX #3: PERMANENT DXY/MACRO SUPPRESSION =====
        # One-time startup check: if DXY doesn't exist on broker, silence all macro logs
        self.dxy_checked = False
        self.dxy_exists = False
        self.dxy_symbol: Optional[str] = None
        self.synthetic_dxy_snapshot: Dict[str, Any] = {}
        self.macro_suppressed = False  # If True, skip all macro-related logging
        self.system_health: Dict[str, Any] = {"dxy": "UNKNOWN"}

    def set_strategy_state_provider(self, provider: Optional[Callable[[str], Dict[str, Any]]]) -> None:
        self.strategy_state_provider = provider
    
    def set_quant_cache(self, cache: Optional[Dict[str, Dict[str, Any]]]) -> None:
        """Set the GLOBAL_QUANT_CACHE reference for persistent table display."""
        self.quant_cache = cache
    
    def check_and_suppress_macro(self, mt5_symbols: list) -> None:
        """
        One-time startup check: verify if DXY/USDX exists on broker.
        If found, lock the symbol and disable all macro fallback searches.
        If not found, permanently suppress all macro-related logging.
        
        FIX #2: Enhanced with expanded alias list and synthetic DXY fallback.
        
        Call this once during bot initialization.
        """
        if self.dxy_checked:
            return  # Already checked
        if self.use_synthetic_dxy:
            self.dxy_exists = True
            self.dxy_symbol = "SYNTHETIC_DXY"
            self.system_health["dxy"] = "STABLE"
            self.macro_suppressed = False
            self.dxy_checked = True
            self.logger.info("[DXY_BASELINE] Synthetic DXY forced. Direct broker DXY symbol probing disabled.")
            return
        
        try:
            import MetaTrader5 as mt5
            # FIX #2: Expanded DXY symbol aliases with FUZZY SEARCH
            # ===== FIX #3: USDX PRIORITIZED + FUZZY MATCHING =====
            # On MetaQuotes-Demo, USDX is the primary Dollar Index symbol
            # Added fuzzy search for common DXY names: 'USDX', 'DXY', 'DOLLAR'
            dxy_candidates = [
                "USDX", "DXY", "DX-", "USDIndex", "DollarIndex", 
                "DXY.m", "DX-Y.NYB", "DX=F", "USD_INDEX", 
                "DOLLAR", "UUP", "UDN", "DX"
            ]
            self.dxy_exists = False
            
            normalized_mt5_symbols = {
                str(getattr(item, "name", item) or "").strip().upper()
                for item in (mt5_symbols or [])
                if str(getattr(item, "name", item) or "").strip()
            }

            for candidate in dxy_candidates:
                try:
                    symbol_info = mt5.symbol_info(candidate)
                    matched_symbol = candidate
                    if symbol_info is None:
                        # FUZZY SEARCH: Check if candidate is contained in any visible symbol
                        matched_symbol = next(
                            (name for name in normalized_mt5_symbols if name == candidate.upper() or candidate.upper() in name),
                            candidate,
                        )
                        symbol_info = mt5.symbol_info(matched_symbol)
                    if symbol_info is not None and symbol_info.visible:
                        self.dxy_exists = True
                        self.dxy_symbol = matched_symbol  # Lock the symbol
                        os.environ["DXY_CANONICAL_SYMBOL"] = str(matched_symbol)
                        self.system_health["dxy"] = "OK"
                        self.logger.info(
                            "[DXY_CHECK] Found Dollar Index via fuzzy search: %s | Locked as canonical symbol. "
                            "All macro evaluation will use this symbol. No more DXY_MISSING warnings.",
                            matched_symbol
                        )
                        break
                except Exception:
                    continue
            
            if not self.dxy_exists:
                # FIX #2: Attempt to calculate synthetic DXY from EURUSD, USDJPY, GBPUSD
                self.dxy_symbol = self._calculate_synthetic_dxy(mt5)
                if self.dxy_symbol:
                    self.dxy_exists = True
                    self.system_health["dxy"] = "STABLE"
                    self.logger.info(
                        "[DXY_CHECK] Using Synthetic DXY Baseline. "
                        "No direct Dollar Index symbol found, so macro evaluation will use EURUSD/USDJPY/GBPUSD median strength."
                    )
                else:
                    self.macro_suppressed = True
                    self.system_health["dxy"] = "UNAVAILABLE"
                    self.logger.info(
                        "[DXY_CHECK] No Dollar Index symbol available on broker and synthetic calculation failed. "
                        "Macro evaluation disabled. Bot will operate in technical-only mode."
                    )
            else:
                self.system_health["dxy"] = "OK"
                self.logger.debug("[DXY_CHECK] DXY/USDX available. Macro evaluation enabled.")
        except Exception as e:
            self.logger.warning(
                "[DXY_CHECK] Failed to check DXY availability: %s. Assuming unavailable.", e
            )
            self.macro_suppressed = True  # Safe default: suppress if we can't check
            self.system_health["dxy"] = "UNAVAILABLE"
        
        self.dxy_checked = True
    
    def _calculate_synthetic_dxy(self, mt5) -> str:
        """
        Calculate synthetic DXY using weighted USD-strength contributions from
        EURUSD, USDJPY, and GBPUSD and a weighted median reducer.
        Returns 'SYNTHETIC_DXY' if calculation succeeds, None otherwise.
        """
        try:
            dxy_components = {
                "EURUSD": {"weight": 0.576, "anchor": 1.08, "invert": True},
                "USDJPY": {"weight": 0.136, "anchor": 150.0, "invert": False},
                "GBPUSD": {"weight": 0.119, "anchor": 1.27, "invert": True},
            }
            available_components = []
            
            for symbol, component_cfg in dxy_components.items():
                tick = mt5.symbol_info_tick(symbol)
                if tick is not None and tick.bid > 0:
                    raw_price = float(tick.bid)
                    anchor = float(component_cfg["anchor"])
                    normalized_strength = (anchor / raw_price) if component_cfg["invert"] else (raw_price / anchor)
                    available_components.append({
                        "symbol": symbol,
                        "bid": raw_price,
                        "ask": float(tick.ask or raw_price),
                        "weight": float(component_cfg["weight"]),
                        "normalized_strength": float(normalized_strength),
                    })
            
            if len(available_components) == len(dxy_components):
                weighted_median = self._weighted_median(
                    [item["normalized_strength"] for item in available_components],
                    [item["weight"] for item in available_components],
                )
                self.synthetic_dxy_snapshot = {
                    "components": available_components,
                    "weighted_median_strength": float(weighted_median),
                }
                self.logger.info(
                    "[SYNTHETIC_DXY] Components=%s | Weighted median strength=%.5f | Synthetic DXY enabled",
                    [c["symbol"] for c in available_components],
                    float(weighted_median),
                )
                return "SYNTHETIC_DXY"
            else:
                self.logger.warning(
                    "[SYNTHETIC_DXY] Insufficient components (%d/3) for weighted synthetic calculation",
                    len(available_components)
                )
                return None
        except Exception as e:
            self.logger.warning("[SYNTHETIC_DXY] Calculation failed: %s", e)
            return None

    @staticmethod
    def _weighted_median(values: List[float], weights: List[float]) -> float:
        ordered = sorted(zip(values, weights), key=lambda item: item[0])
        total_weight = sum(max(float(weight), 0.0) for _, weight in ordered)
        if total_weight <= 0:
            return float(ordered[len(ordered) // 2][0])
        cumulative = 0.0
        threshold = total_weight / 2.0
        for value, weight in ordered:
            cumulative += max(float(weight), 0.0)
            if cumulative >= threshold:
                return float(value)
        return float(ordered[-1][0])

    def _cycle_label(self, cycle_snapshot: Any) -> str:
        for attr in ("cycle_id", "cycle", "cycle_count"):
            value = getattr(cycle_snapshot, attr, None)
            if value is not None:
                return str(value)
        return "LIVE"

    def _extract_quant_meta(self, result: Any) -> Optional[Dict[str, Any]]:
        """
        Extract strategy metadata from analyzer result.
        
        CRITICAL: Do NOT filter out non-quant strategies. Return metadata for ALL strategy types.
        SimpleTrendStrategy pairs should have their symbol_report (RSI, ML Dir) included.
        """
        signal = None
        strategy_meta = {}
        if isinstance(result, dict):
            signal = result.get("signal")
            strategy_meta.update(dict(result.get("strategy_meta") or {}))
        elif self._looks_like_signal(result):
            signal = result
        if signal is not None:
            strategy_meta.update(dict(getattr(signal, "strategy_meta", {}) or {}))
        
        # CRITICAL FIX: Do NOT return None just because quant_hybrid=False
        # Return whatever metadata we have, even if it's just symbol_report
        return strategy_meta if strategy_meta else None

    @staticmethod
    def _dry_run_enabled() -> bool:
        return str(os.environ.get("DRY_RUN", "0")).strip().lower() in {"1", "true", "yes", "on"}

    def _log_cycle_header_banner(self, cycle_snapshot: Any, ordered_symbols: List[str], results: List[Any]) -> None:
        strategy_metas = [meta for meta in (self._extract_quant_meta(result) for result in results) if meta]
        if callable(self.strategy_state_provider):
            for symbol in ordered_symbols:
                try:
                    cached_meta = dict(self.strategy_state_provider(symbol) or {})
                except Exception:
                    cached_meta = {}
                if cached_meta and not any(meta is cached_meta for meta in strategy_metas):
                    strategy_metas.append(cached_meta)
        
        # CRITICAL FIX: Also include metas for symbols that might have been filtered out
        # but still have cached strategy state (e.g., symbols with active positions)
        # This ensures the table shows ALL symbols, not just the ones analyzed this cycle
        if callable(self.strategy_state_provider):
            try:
                # Get all known symbols from the strategy state provider's context
                # We'll try common symbol list and add any that have cached meta
                all_known_symbols = set(ordered_symbols)
                # Try to add symbols that might have cached state
                for test_symbol in ["AUD/USD", "USD/CAD", "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "NZD/USD"]:
                    if test_symbol not in all_known_symbols:
                        try:
                            cached_meta = dict(self.strategy_state_provider(test_symbol) or {})
                            if cached_meta:
                                strategy_metas.append(cached_meta)
                                all_known_symbols.add(test_symbol)
                        except Exception:
                            pass
            except Exception:
                pass
        
        for line in QuantHybridStrategy.build_cycle_header_lines(self._cycle_label(cycle_snapshot), strategy_metas):
            self.logger.info(line)

    def _log_symbol_table_header(self) -> None:
        self.logger.info("Symbol  │ Z-Score │ GARCH Vol     │ Flow Delta │ RSI  │ ML Dir │ Decision │ Reason")
        self.logger.info("────────┼─────────┼───────────────┼────────────┼──────┼────────┼──────────┼──────")

    def _log_forced_execution_banner(self, signal: Any) -> None:
        self.logger.critical(QuantHybridStrategy.format_strike_log_line(signal))

    def _log_symbol_table_header(self) -> None:
        self.logger.info("Symbol  | Z-Score | GARCH Vol     | Flow Delta | RSI  | ML Dir | Decision | Reason")
        self.logger.info("--------+---------+---------------+------------+------+--------+----------+-------")

    @staticmethod
    def _looks_like_signal(candidate: Any) -> bool:
        return bool(
            candidate is not None
            and getattr(candidate, "symbol", None)
            and getattr(candidate, "direction", None) is not None
            and getattr(candidate, "entry_price", None) is not None
        )

    async def _invoke_analyzer(
        self,
        symbol: str,
        analyzer: Callable[[str, Dict[str, Any], Any], Awaitable[Any]],
        market_data_dict: Dict[str, Any],
        cycle_snapshot: Any,
    ) -> Any:
        try:
            result = await analyzer(symbol, market_data_dict, cycle_snapshot)
        except ValueError as exc:
            if "too many values to unpack" in str(exc):
                self.logger.error(
                    "[RUNTIME_ORCH] %s analysis failed with unpacking error. "
                    "Analyzer likely returned more than 2 values. The offending unpack is in the legacy "
                    "analysis/strategy path, not this runtime wrapper. Normalize that call site to absorb "
                    "extra return values before execution handoff.",
                    symbol,
                )
            raise

        if isinstance(result, (list, tuple)):
            items = list(result)
            strike_pkg = next((item for item in items if isinstance(item, dict) and "order" in item and "signal" in item), None)
            signal = next((item for item in items if self._looks_like_signal(item)), None)
            self.logger.info(
                "[RUNTIME_ORCH] %s analyzer returned %d values | strike_pkg=%s | signal=%s",
                symbol,
                len(items),
                bool(strike_pkg is not None),
                bool(signal is not None),
            )
            if strike_pkg is not None:
                return strike_pkg

        return result

    async def analyze_symbols(
        self,
        ordered_symbols: List[str],
        analyzer: Callable[[str, Dict[str, Any], Any], Awaitable[Any]],
        market_data_dict: Dict[str, Any],
        cycle_snapshot: Any = None,
    ) -> List[Dict[str, Any]]:
        results = await self._run_batch(
            ordered_symbols=ordered_symbols,
            analyzer=analyzer,
            market_data_dict=market_data_dict,
            cycle_snapshot=cycle_snapshot,
        )
        self._log_cycle_header_banner(cycle_snapshot, ordered_symbols, results)
        self._log_symbol_table_header()
        
        # CRITICAL FIX: Loop through ALL symbols in quant_cache, not just analyzed ones
        # This ensures symbols with active positions still appear in the table
        if self.quant_cache:
            # Use the cache keys as the master symbol list
            all_symbols = list(self.quant_cache.keys())
        else:
            # Fallback to analyzed symbols only
            all_symbols = list(ordered_symbols)
        
        # Build a result map for analyzed symbols
        result_map = dict(zip(ordered_symbols, results))
        
        for symbol in all_symbols:
            # Try to get result from current cycle first
            result = result_map.get(symbol)
            
            if result is not None:
                # Symbol was analyzed this cycle, extract fresh meta
                signal = result.get("signal") if isinstance(result, dict) else result
                strategy_meta = self._extract_quant_meta(result) or {}
                symbol_display = str(
                    (result.get("symbol") if isinstance(result, dict) else None)
                    or getattr(signal, "symbol", None)
                    or strategy_meta.get("symbol")
                    or symbol
                    or "UNKNOWN"
                )
                if not strategy_meta and callable(self.strategy_state_provider):
                    try:
                        strategy_meta = dict(self.strategy_state_provider(symbol) or {})
                    except Exception:
                        strategy_meta = {}
                is_rejected = isinstance(result, dict) and bool(result.get("rejected", False))
                reason_code = (result.get("rejection_code") if isinstance(result, dict) else None) or "[OK]"
                if isinstance(result, Exception):
                    decision_label = "BLOCKED"
                    reason_code = "[Q]"
                elif is_rejected:
                    decision_label = "BLOCKED"
                elif isinstance(result, dict) and "order" in result and "signal" in result:
                    decision_label = "DRY_RUN" if self._dry_run_enabled() else "READY"
                elif self._looks_like_signal(signal):
                    decision_label = "DRY_RUN" if self._dry_run_enabled() else "READY"
                else:
                    decision_label = "BLOCKED"
                    reason_code = reason_code if reason_code != "[OK]" else "[Q]"
            else:
                # Symbol was NOT analyzed (e.g., has active position), use cached data
                strategy_meta = dict(self.quant_cache.get(symbol, {}) or {})
                symbol_display = symbol
                decision_label = "HELD"  # Indicate symbol has active position
                reason_code = "[POS]"
            
            self.logger.info(
                QuantHybridStrategy.format_quant_state_line(
                    symbol_display,
                    strategy_meta,
                    decision=decision_label,
                    reason_code=reason_code,
                )
            )
        
        # CRITICAL FIX: Also log table rows for symbols that were filtered out
        # (e.g., symbols with active positions) but still have cached strategy state
        if callable(self.strategy_state_provider):
            all_known_symbols = ["AUD/USD", "USD/CAD", "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "NZD/USD"]
            analyzed_symbols = set(ordered_symbols)
            for symbol in all_known_symbols:
                if symbol not in analyzed_symbols:
                    # This symbol was filtered out, but show it with cached state
                    try:
                        strategy_meta = dict(self.strategy_state_provider(symbol) or {})
                        if strategy_meta:  # Only show if we have cached data
                            self.logger.info(
                                QuantHybridStrategy.format_quant_state_line(
                                    symbol,
                                    strategy_meta,
                                    decision="HELD",  # Indicate symbol has active position
                                    reason_code="[POS]",
                                )
                            )
                    except Exception:
                        pass

        queued_strikes: List[Dict[str, Any]] = []
        for res in results:
            if (
                isinstance(res, dict)
                and "order" in res
                and "signal" in res
                and self._looks_like_signal(res.get("signal"))
            ):
                strategy_meta = dict(getattr(res.get("signal"), "strategy_meta", {}) or {})
                if bool(strategy_meta.get("quant_hybrid", False)):
                    if bool(getattr(res.get("signal"), "forced_execution", False)):
                        self._log_forced_execution_banner(res.get("signal"))
                    else:
                        self.logger.info(QuantHybridStrategy.format_strike_log_line(res.get("signal")))
                self.logger.info(
                    "[RUNTIME_ORCH_HANDOFF] %s accepted for execution queue.",
                    getattr(res.get("signal"), "symbol", res.get("symbol", "UNKNOWN")),
                )
                if bool(strategy_meta.get("quant_hybrid", False)):
                    quant_scores = dict(strategy_meta.get("quant_scores") or {})
                    self.logger.info(
                        "[RUNTIME_ORCH] %s quant hybrid active | trend=%.2f | ou=%.2f | micro=%.2f",
                        getattr(res.get("signal"), "symbol", res.get("symbol", "UNKNOWN")),
                        float(quant_scores.get("trend_score", 0.0) or 0.0),
                        float(quant_scores.get("ou_score", 0.0) or 0.0),
                        float(quant_scores.get("micro_score", 0.0) or 0.0),
                    )
                queued_strikes.append(res)
            elif isinstance(res, dict) and bool(res.get("rejected", False)):
                continue
            elif isinstance(res, dict) and ("order" in res or "signal" in res):
                self.logger.error(
                    "[RUNTIME_ORCH] Dropping malformed strike package for %s | has_order=%s | has_signal=%s | signal_valid=%s",
                    res.get("symbol", "UNKNOWN"),
                    "order" in res,
                    "signal" in res,
                    self._looks_like_signal(res.get("signal")),
                )
            elif isinstance(res, Exception):
                self.logger.error("[RUNTIME_ORCH] Symbol analysis failed: %s", res)
        return queued_strikes

    async def _run_batch(
        self,
        ordered_symbols: List[str],
        analyzer: Callable[[str, Dict[str, Any], Any], Awaitable[Any]],
        market_data_dict: Dict[str, Any],
        cycle_snapshot: Any,
    ) -> List[Any]:
        import asyncio

        return await asyncio.gather(
            *[
                self._invoke_analyzer(sym, analyzer, market_data_dict, cycle_snapshot)
                for sym in ordered_symbols
            ],
            return_exceptions=True,
        )
