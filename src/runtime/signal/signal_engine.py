from typing import List, Protocol

from src.runtime.contracts.commands import SignalIntent
from src.runtime.contracts.snapshots import MarketSnapshot


class SignalEngine(Protocol):
    async def generate(self, snapshot: MarketSnapshot) -> List[SignalIntent]:
        """Generate signal intents from a point-in-time market snapshot."""
        ...

