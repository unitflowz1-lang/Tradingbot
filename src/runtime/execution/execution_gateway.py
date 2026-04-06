from typing import Protocol

from src.models import ExecutionResult
from src.runtime.contracts.commands import ExecutionPlan


class ExecutionGateway(Protocol):
    async def submit(self, plan: ExecutionPlan) -> ExecutionResult:
        """Submit a compliant execution plan to the broker/execution backend."""
        ...

