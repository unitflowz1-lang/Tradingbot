from src.models import ExecutionResult
from src.trading.execution_engine import ExecutionEngine
from src.runtime.contracts.commands import ExecutionPlan
from src.runtime.execution.execution_gateway import ExecutionGateway


class LegacyExecutionAdapter(ExecutionGateway):
    """
    Adapter for existing ExecutionEngine.
    Phase 1 behavior: convert ExecutionPlan to legacy Order and execute.
    """

    def __init__(self, execution_engine: ExecutionEngine):
        self.execution_engine = execution_engine

    async def submit(self, plan: ExecutionPlan) -> ExecutionResult:
        order = plan.to_order()
        return await self.execution_engine.execute_trade(order)

