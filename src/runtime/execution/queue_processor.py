from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional
from src.runtime.emergency_stop import emergency_stop_active


@dataclass
class QueueExecutionAttempt:
    pkg: Dict[str, Any]
    result: Optional[Any] = None
    skipped_reason: Optional[str] = None
    load_before: int = 0
    load_after: int = 0


@dataclass
class QueueExecutionOutcome:
    attempts: List[QueueExecutionAttempt] = field(default_factory=list)
    final_load: int = 0


class RuntimeExecutionQueueProcessor:
    """
    Phase 5 extraction: capacity-gated queue execution orchestration.
    """

    async def process_queue(
        self,
        queued_strikes: List[Dict[str, Any]],
        current_load: int,
        max_cap: int,
        execute_order: Callable[[Any], Awaitable[Any]],
        prepare_pkg: Optional[Callable[[Dict[str, Any], int, int], None]] = None,
        should_skip: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
    ) -> QueueExecutionOutcome:
        outcome = QueueExecutionOutcome(final_load=current_load)

        if emergency_stop_active():
            pending_count = len(queued_strikes)
            queued_strikes.clear()
            if pending_count:
                outcome.attempts.append(
                    QueueExecutionAttempt(
                        pkg={"symbol": "ALL"},
                        skipped_reason="EMERGENCY_STOP_ACTIVE",
                        load_before=current_load,
                        load_after=current_load,
                    )
                )
            outcome.final_load = current_load
            return outcome

        for idx, pkg in enumerate(list(queued_strikes)):
            if emergency_stop_active():
                del queued_strikes[idx:]
                outcome.attempts.append(
                    QueueExecutionAttempt(
                        pkg=pkg,
                        skipped_reason="EMERGENCY_STOP_ACTIVE",
                        load_before=current_load,
                        load_after=current_load,
                    )
                )
                outcome.final_load = current_load
                return outcome
            if current_load >= max_cap:
                outcome.attempts.append(
                    QueueExecutionAttempt(
                        pkg=pkg,
                        skipped_reason=f"MAX_CAPACITY_REACHED ({current_load}/{max_cap})",
                        load_before=current_load,
                        load_after=current_load,
                    )
                )
                break

            if should_skip is not None:
                skip_reason = should_skip(pkg)
                if skip_reason:
                    outcome.attempts.append(
                        QueueExecutionAttempt(
                            pkg=pkg,
                            skipped_reason=skip_reason,
                            load_before=current_load,
                            load_after=current_load,
                        )
                    )
                    continue

            if prepare_pkg is not None:
                prepare_pkg(pkg, current_load, max_cap)

            load_before = current_load
            result = await execute_order(pkg["order"])
            if getattr(result, "success", False):
                current_load += 1

            outcome.attempts.append(
                QueueExecutionAttempt(
                    pkg=pkg,
                    result=result,
                    load_before=load_before,
                    load_after=current_load,
                )
            )

        outcome.final_load = current_load
        return outcome

    async def clear_symbol_queue(self, symbol_key: str, queued_strikes: Optional[List[Dict[str, Any]]] = None) -> int:
        if queued_strikes is None:
            return 0
        before = len(queued_strikes)
        normalized = str(symbol_key or "").upper()
        queued_strikes[:] = [
            pkg for pkg in queued_strikes
            if str(getattr(pkg.get("signal"), "symbol", pkg.get("symbol", ""))).replace("/", "").upper() != normalized
        ]
        return before - len(queued_strikes)

    async def clear_all_queues(self, queued_strikes: Optional[List[Dict[str, Any]]] = None) -> int:
        if queued_strikes is None:
            return 0
        count = len(queued_strikes)
        queued_strikes.clear()
        return count
