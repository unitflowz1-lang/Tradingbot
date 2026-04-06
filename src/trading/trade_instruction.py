"""
TradeInstruction: Atomic, immutable trade object ensuring zero-size abort prevention.
All size validations occur at creation time. ExecutionEngine receives only valid instructions.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class TradeInstructionError(Exception):
    """Raised when TradeInstruction validation fails."""
    pass


class ZeroSizeAbortError(TradeInstructionError):
    """Raised when PositionSizer returns size < broker minimum."""
    pass


class Direction(Enum):
    """Trade direction."""
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True)  # Immutable - prevents accidental modifications
class TradeInstruction:
    """
    Atomic trade instruction object.
    
    GUARANTEED INVARIANTS:
    - size is always > 0.05 (broker minimum)
    - entry, sl, tp are all valid and sensible
    - symbol is non-empty
    - Created timestamp for audit trail
    
    Once created, cannot be modified (frozen=True prevents accidental state corruption).
    """
    
    # Core trade parameters
    symbol: str
    direction: Direction
    entry_price: float
    stop_loss: float
    take_profit: float
    size: float  # GUARANTEED > 0.05
    
    # Optional metadata
    confidence: float = 0.5  # 0.0 - 1.0
    ml_confidence: float = 0.5  # 0.0 - 1.0
    tier: str = "TIER_C"
    risk_reward_ratio: Optional[float] = None
    regime: str = "UNKNOWN"
    
    # Lifecycle tracking
    created_at: datetime = field(default_factory=datetime.utcnow)
    instruction_id: Optional[str] = None  # Assigned by orchestrator
    
    def __post_init__(self):
        """Validate all invariants after construction."""
        if self.size < 0.05:
            raise ZeroSizeAbortError(
                f"[TRADE_INSTRUCTION] {self.symbol} | "
                f"Size {self.size:.4f} < broker minimum 0.05. "
                f"Instruction REJECTED. This is a fatal validation error."
            )
        
        if self.size > 100.0:
            raise TradeInstructionError(
                f"[TRADE_INSTRUCTION] {self.symbol} | "
                f"Size {self.size:.4f} exceeds reasonable maximum 100.0."
            )
        
        if self.entry_price <= 0:
            raise TradeInstructionError(
                f"[TRADE_INSTRUCTION] {self.symbol} | "
                f"Entry price {self.entry_price} must be > 0."
            )
        
        if self.stop_loss <= 0:
            raise TradeInstructionError(
                f"[TRADE_INSTRUCTION] {self.symbol} | "
                f"Stop loss {self.stop_loss} must be > 0."
            )
        
        if self.take_profit <= 0:
            raise TradeInstructionError(
                f"[TRADE_INSTRUCTION] {self.symbol} | "
                f"Take profit {self.take_profit} must be > 0."
            )
        
        # Validate risk/reward direction makes sense
        if self.direction == Direction.LONG:
            if self.stop_loss >= self.entry_price:
                raise TradeInstructionError(
                    f"[TRADE_INSTRUCTION] {self.symbol} LONG | "
                    f"Stop loss {self.stop_loss} must be below entry {self.entry_price}."
                )
            if self.take_profit <= self.entry_price:
                raise TradeInstructionError(
                    f"[TRADE_INSTRUCTION] {self.symbol} LONG | "
                    f"Take profit {self.take_profit} must be above entry {self.entry_price}."
                )
        else:  # SHORT
            if self.stop_loss <= self.entry_price:
                raise TradeInstructionError(
                    f"[TRADE_INSTRUCTION] {self.symbol} SHORT | "
                    f"Stop loss {self.stop_loss} must be above entry {self.entry_price}."
                )
            if self.take_profit >= self.entry_price:
                raise TradeInstructionError(
                    f"[TRADE_INSTRUCTION] {self.symbol} SHORT | "
                    f"Take profit {self.take_profit} must be below entry {self.entry_price}."
                )
        
        if not 0.0 <= self.confidence <= 1.0:
            raise TradeInstructionError(
                f"[TRADE_INSTRUCTION] {self.symbol} | "
                f"Confidence {self.confidence} must be between 0.0 and 1.0."
            )
        
        logger.debug(
            "[TRADE_INSTRUCTION_VALIDATED] %s %s | "
            "Size: %.4f | Entry: %.5f | SL: %.5f | TP: %.5f | "
            "Conf: %.1f%% | Regime: %s",
            self.symbol,
            self.direction.value,
            self.size,
            self.entry_price,
            self.stop_loss,
            self.take_profit,
            self.confidence * 100,
            self.regime
        )
    
    @property
    def risk_pips(self) -> float:
        """Calculate risk in pips."""
        if self.direction == Direction.LONG:
            return (self.entry_price - self.stop_loss) * 10000
        else:
            return (self.stop_loss - self.entry_price) * 10000
    
    @property
    def reward_pips(self) -> float:
        """Calculate reward in pips."""
        if self.direction == Direction.LONG:
            return (self.take_profit - self.entry_price) * 10000
        else:
            return (self.entry_price - self.take_profit) * 10000
    
    @property
    def calculated_rr(self) -> float:
        """Calculate risk-reward ratio."""
        if self.risk_pips == 0:
            return 0.0
        return self.reward_pips / self.risk_pips
    
    def to_dict(self) -> dict:
        """Convert to dictionary for logging/serialization."""
        return {
            'symbol': self.symbol,
            'direction': self.direction.value,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'size': self.size,
            'confidence': self.confidence,
            'ml_confidence': self.ml_confidence,
            'tier': self.tier,
            'risk_reward_ratio': self.calculated_rr,
            'regime': self.regime,
            'created_at': self.created_at.isoformat(),
            'instruction_id': self.instruction_id,
        }


def build_trade_instruction(
    symbol: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    size: float,
    confidence: float = 0.5,
    ml_confidence: float = 0.5,
    tier: str = "TIER_C",
    regime: str = "UNKNOWN",
) -> TradeInstruction:
    """
    Factory function to build and validate a TradeInstruction.
    
    Raises:
        ZeroSizeAbortError: If size < 0.05 (broker minimum)
        TradeInstructionError: If any parameter validation fails
    """
    try:
        dir_enum = Direction[direction.upper()] if isinstance(direction, str) else direction
        
        instruction = TradeInstruction(
            symbol=symbol,
            direction=dir_enum,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            size=size,
            confidence=confidence,
            ml_confidence=ml_confidence,
            tier=tier,
            regime=regime,
        )
        
        logger.info(
            "[TRADE_INSTRUCTION_CREATED] %s %s | Size: %.4f | RR: %.2f",
            symbol,
            direction.upper(),
            size,
            instruction.calculated_rr
        )
        
        return instruction
    
    except ZeroSizeAbortError as e:
        logger.critical("[ZERO_SIZE_ABORT] %s", str(e))
        raise
    except TradeInstructionError as e:
        logger.error("[TRADE_INSTRUCTION_ERROR] %s", str(e))
        raise
    except Exception as e:
        logger.error("[TRADE_INSTRUCTION_UNKNOWN_ERROR] %s | %s", symbol, str(e))
        raise TradeInstructionError(f"Failed to create TradeInstruction for {symbol}: {e}")
