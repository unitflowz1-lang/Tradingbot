from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional


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

        for pkg in queued_strikes:
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
