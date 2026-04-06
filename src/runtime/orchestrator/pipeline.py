import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from src.models import ExecutionResult, OrderType
from src.runtime.contracts.commands import ExecutionPlan, SignalIntent
from src.runtime.contracts.decisions import RiskDecision
from src.runtime.contracts.snapshots import MarketSnapshot, PortfolioSnapshot
from src.runtime.execution.execution_gateway import ExecutionGateway
from src.runtime.risk.policy_engine import RiskPolicyEngine
from src.runtime.signal.signal_engine import SignalEngine


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

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)

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

        queued_strikes: List[Dict[str, Any]] = []
        for res in results:
            if (
                isinstance(res, dict)
                and "order" in res
                and "signal" in res
                and self._looks_like_signal(res.get("signal"))
            ):
                self.logger.info(
                    "[RUNTIME_ORCH_HANDOFF] %s accepted for execution queue.",
                    getattr(res.get("signal"), "symbol", res.get("symbol", "UNKNOWN")),
                )
                queued_strikes.append(res)
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
