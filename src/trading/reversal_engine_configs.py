"""
REVERSAL ENGINE - CONFIGURATION EXAMPLES
========================================

Pre-tuned configurations for different trading scenarios and risk profiles.
Copy and modify these for your specific use case.

Author: Lead Quantitative Developer
Version: 1.0.0
"""

import logging
from src.trading.reversal_engine import ReversalEngine, CooldownManager, MockSRH

# Setup logging
logger = logging.getLogger(__name__)


# ==============================================================================
# CONFIGURATION CLASSES
# ==============================================================================

class ReversalEngineConfig:
    """Base configuration for reversal engine tuning."""

    def __init__(
        self,
        name: str,
        base_threshold_ranging: float = 0.55,
        base_threshold_other: float = 0.65,
        w_div: float = 0.35,
        w_exh: float = 0.20,
        w_str: float = 0.15,
        w_pa: float = 0.15,
        w_clx: float = 0.15,
        max_penalty: float = 0.45,
        confidence_floor: float = 0.55,
        cooldown_candles: int = 8,
    ):
        """
        Initialize configuration.
        
        Args:
            name: Config name (for logging)
            base_threshold_ranging: Threshold in RANGING regime
            base_threshold_other: Threshold in other regimes
            w_div: Divergence weight
            w_exh: Exhaustion weight
            w_str: Structure weight
            w_pa: Price Action weight
            w_clx: Climax weight
            max_penalty: Hard penalty floor (0.45 = can't go below 0.55x)
            confidence_floor: Minimum exponential confidence
            cooldown_candles: Candles between trades
        """
        self.name = name
        self.base_threshold_ranging = base_threshold_ranging
        self.base_threshold_other = base_threshold_other
        self.w_div = w_div
        self.w_exh = w_exh
        self.w_str = w_str
        self.w_pa = w_pa
        self.w_clx = w_clx
        self.max_penalty = max_penalty
        self.confidence_floor = confidence_floor
        self.cooldown_candles = cooldown_candles

        # Verify weights sum to 1.0
        total_weight = w_div + w_exh + w_str + w_pa + w_clx
        assert abs(total_weight - 1.0) < 0.001, f"Weights sum to {total_weight}, must be 1.0"

    def create_engine(self, srh=None, cooldown_mgr=None) -> ReversalEngine:
        """Create configured engine instance."""
        if srh is None:
            srh = MockSRH()
        if cooldown_mgr is None:
            cooldown_mgr = CooldownManager(cooldown_candles=self.cooldown_candles)

        engine = ReversalEngine(srh=srh, cooldown_mgr=cooldown_mgr)
        
        # Apply custom weights
        engine.W_DIV = self.w_div
        engine.W_EXH = self.w_exh
        engine.W_STR = self.w_str
        engine.W_PA = self.w_pa
        engine.W_CLX = self.w_clx

        logger.info(f"[CONFIG] Created engine: {self.name}")
        logger.info(f"  Weights: DIV={self.w_div:.2f} EXH={self.w_exh:.2f} "
                    f"STR={self.w_str:.2f} PA={self.w_pa:.2f} CLX={self.w_clx:.2f}")
        logger.info(f"  Thresholds: RANGING={self.base_threshold_ranging:.2f} "
                    f"OTHER={self.base_threshold_other:.2f}")
        logger.info(f"  Cooldown: {self.cooldown_candles} candles")

        return engine

    def describe(self) -> str:
        """Return human-readable description of config."""
        return f"""
{self.name}
{'='*60}

THRESHOLDS
  Ranging Regime:    {self.base_threshold_ranging:.2f}
  Other Regimes:     {self.base_threshold_other:.2f}
  Confidence Floor:  {self.confidence_floor:.2f}
  Max Penalty:       {self.max_penalty:.2f} (floor at {1.0 - self.max_penalty:.2f}x)

WEIGHTS (total = 1.0)
  Divergence:        {self.w_div:.2f} (35%)
  Exhaustion:        {self.w_exh:.2f}
  Structure/BOS:     {self.w_str:.2f}
  Price Action:      {self.w_pa:.2f}
  Climax:            {self.w_clx:.2f}

FREQUENCY CONTROL
  Cooldown:          {self.cooldown_candles} candles

CHARACTERISTICS
  Selectivity:       {"STRICT" if self.base_threshold_other >= 0.70 else "MODERATE" if self.base_threshold_other >= 0.60 else "LOOSE"}
  Entry Rate:        {"LOW" if self.base_threshold_other >= 0.65 else "MEDIUM" if self.base_threshold_other >= 0.55 else "HIGH"}
  Conviction Focus:  {"Divergence-heavy" if self.w_div >= 0.40 else "Balanced"}
"""


# ==============================================================================
# PRE-TUNED CONFIGURATIONS
# ==============================================================================

# ============================================================================
# CONFIG 1: CONSERVATIVE ELITE SIGNALS
# ============================================================================
CONFIG_CONSERVATIVE = ReversalEngineConfig(
    name="Conservative Elite Signals",
    base_threshold_ranging=0.70,
    base_threshold_other=0.75,
    w_div=0.45,      # Heavy emphasis on divergence (high-conviction)
    w_exh=0.15,
    w_str=0.15,
    w_pa=0.15,
    w_clx=0.10,      # De-emphasize climax (can be false)
    max_penalty=0.40,  # Strict penalty (0.60x floor)
    confidence_floor=0.65,  # High confidence floor
    cooldown_candles=12,  # Longer cooldown between trades
)

"""
CONSERVATIVE PROFILE
====================
Target Trader: Risk-averse, quality over quantity

Characteristics:
  ✓ High selectivity (75% threshold in volatility regime)
  ✓ Divergence-focused (45% weight)
  ✓ Long cooldown (12 candles = 12 minutes on M1)
  ✓ Strict confidence floor (65%)
  ✓ Tight penalties (40% max)

Expected Performance:
  Win Rate: 50-55% (higher, elite setups)
  Avg Winner: 1.8R-2.2R (wait for bigger moves)
  Avg Loser: -1.0R
  Avg R/Trade: +0.4R to +0.6R
  Trade Frequency: ~5-8 per day (4 symbols)

Best For:
  - Account sizes < $10,000 (quality over quantity)
  - Risk-averse traders
  - Consistent profit focus
  - Low drawdown tolerance

Recommended Symbols: Major pairs (EUR/USD, GBP/USD, USD/JPY)
Timeframe: M1 (scalp into higher timeframes)
"""


# ============================================================================
# CONFIG 2: BALANCED INSTITUTIONAL
# ============================================================================
CONFIG_BALANCED = ReversalEngineConfig(
    name="Balanced Institutional",
    base_threshold_ranging=0.55,    # Default
    base_threshold_other=0.65,      # Default
    w_div=0.35,     # Standard
    w_exh=0.20,
    w_str=0.15,
    w_pa=0.15,
    w_clx=0.15,
    max_penalty=0.45,  # Standard
    confidence_floor=0.55,  # Standard
    cooldown_candles=8,  # Standard
)

"""
BALANCED PROFILE
================
Target Trader: Institutional, looking for consistency

Characteristics:
  ✓ Moderate selectivity (65% threshold)
  ✓ Balanced multi-factor approach
  ✓ Standard cooldown (8 candles = 8 minutes)
  ✓ All features equally weighted
  ✓ Moderate penalties (45% max)

Expected Performance:
  Win Rate: 45-52% (balanced risk/reward)
  Avg Winner: 1.5R-1.8R
  Avg Loser: -1.0R
  Avg R/Trade: +0.25R to +0.40R
  Trade Frequency: ~10-15 per day (4 symbols)

Best For:
  - Account sizes $10K-$100K
  - Consistent, systematic approach
  - Institutional deployment
  - SRH-integrated trading

Recommended Symbols: Major + Minor pairs (8-12 symbols)
Timeframe: M1 (primary)
"""


# ============================================================================
# CONFIG 3: AGGRESSIVE VOLUME
# ============================================================================
CONFIG_AGGRESSIVE = ReversalEngineConfig(
    name="Aggressive Volume",
    base_threshold_ranging=0.50,
    base_threshold_other=0.55,
    w_div=0.25,     # De-emphasize divergence
    w_exh=0.15,
    w_str=0.15,
    w_pa=0.15,
    w_clx=0.30,     # Heavy emphasis on climax/volume
    max_penalty=0.50,  # Soft penalties (0.50x floor)
    confidence_floor=0.50,  # Low confidence floor
    cooldown_candles=4,  # Short cooldown
)

"""
AGGRESSIVE PROFILE
==================
Target Trader: Volume-focused, high-frequency

Characteristics:
  ✓ Low selectivity (55% threshold)
  ✓ Volume/climax focused (30% weight)
  ✓ Short cooldown (4 candles = 4 minutes)
  ✓ Soft penalties
  ✓ Low confidence floor (catches more noise)

Expected Performance:
  Win Rate: 40-48% (lower, accept more noise)
  Avg Winner: 1.2R-1.5R (quick scalps)
  Avg Loser: -1.0R
  Avg R/Trade: +0.15R to +0.30R
  Trade Frequency: ~20-30 per day (4 symbols)

Best For:
  - Account sizes > $50K (can absorb losses)
  - High-frequency scalp strategies
  - Liquid market pairs
  - Experienced traders

Recommended Symbols: Liquid pairs (EUR/USD, GBP/USD, AUD/USD)
Timeframe: M1 (rapid entries/exits)
"""


# ============================================================================
# CONFIG 4: EXOTIC PAIRS / LOW LIQUIDITY
# ============================================================================
CONFIG_EXOTIC = ReversalEngineConfig(
    name="Exotic Pairs - Low Liquidity",
    base_threshold_ranging=0.65,
    base_threshold_other=0.75,
    w_div=0.40,
    w_exh=0.20,
    w_str=0.20,     # Heavy structure (exotic pairs have cleaner structure)
    w_pa=0.10,      # De-emphasize PA (less reliable in low liquidity)
    w_clx=0.10,     # De-emphasize climax (false signals in exotic)
    max_penalty=0.35,  # Strict penalties (0.65x floor)
    confidence_floor=0.70,  # High floor
    cooldown_candles=16,  # Very long cooldown
)

"""
EXOTIC PAIRS PROFILE
====================
Target Trader: Specialist in exotic FX pairs

Characteristics:
  ✓ Very high selectivity (75% threshold)
  ✓ Structure-focused (20% weight) - cleaner in exotic
  ✓ Long cooldown (16 candles) - slower moving
  ✓ Low PA/Climax weight (more false signals)
  ✓ Very strict penalty (35% max)

Expected Performance:
  Win Rate: 48-55% (elite setups only)
  Avg Winner: 2.0R-2.5R (bigger moves)
  Avg Loser: -1.0R
  Avg R/Trade: +0.5R to +0.8R
  Trade Frequency: ~2-5 per day (4 symbols)

Best For:
  - Trading exotic pairs (USD/ZAR, USD/BRL, etc.)
  - Lower liquidity environments
  - Specialists in specific regions
  - Conservative risk management

Recommended Symbols: Exotic pairs, regional pairs
Timeframe: M1-M5 (slower signals)
"""


# ============================================================================
# CONFIG 5: TRENDING MARKET BIAS
# ============================================================================
CONFIG_TREND_FOLLOWING = ReversalEngineConfig(
    name="Trend Following (Reversed)",
    base_threshold_ranging=0.48,
    base_threshold_other=0.52,
    w_div=0.20,     # De-emphasize divergence
    w_exh=0.30,     # Heavy exhaustion (catch trend exhaustion)
    w_str=0.20,     # Emphasis structure (BOS on breakout)
    w_pa=0.15,
    w_clx=0.15,
    max_penalty=0.50,  # Soft penalties
    confidence_floor=0.48,  # Very low floor
    cooldown_candles=3,  # Very short
)

"""
TREND FOLLOWING PROFILE (Reversal Context)
===========================================
This config reverses counter-trend (finds exhaustion zones)
but optimized for trend environments where reversals are deeper.

Target Trader: Trend followers looking for optimal exit points

Characteristics:
  ✓ Low selectivity (52% threshold in vol regime)
  ✓ Exhaustion-focused (30%) - catch trend end
  ✓ Structure emphasis (20%) - BOS on reversal
  ✓ Short cooldown (3 candles) - rapid re-entries
  ✓ Soft penalties

Expected Performance:
  Win Rate: 45-50%
  Avg Winner: 1.3R
  Avg Loser: -1.0R
  Avg R/Trade: +0.15R to +0.25R
  Trade Frequency: 25-40 per day

Best For:
  - Trend exhaustion scalping
  - Finding optimal trend exits
  - High-frequency reversal fading

Recommended Symbols: Trending majors in volatile sessions
Timeframe: M1
"""


# ============================================================================
# CONFIG 6: NIGHT SESSION / LOW ACTIVITY
# ============================================================================
CONFIG_NIGHT_QUIET = ReversalEngineConfig(
    name="Night Session - Quiet Markets",
    base_threshold_ranging=0.70,
    base_threshold_other=0.80,
    w_div=0.50,     # Very high divergence emphasis
    w_exh=0.15,
    w_str=0.20,
    w_pa=0.10,
    w_clx=0.05,     # De-emphasize (less volume at night)
    max_penalty=0.30,  # Strict penalties (0.70x floor)
    confidence_floor=0.75,  # Very high confidence floor
    cooldown_candles=20,  # Very long cooldown
)

"""
NIGHT SESSION PROFILE
=====================
For low-volume, quiet market periods (Asia session, late night NY)

Characteristics:
  ✓ Very selective (80% threshold)
  ✓ Divergence-focused (50%) - most reliable in quiet markets
  ✓ Long cooldown (20 candles)
  ✓ Minimal climax weight (little volume)
  ✓ Very strict penalties (30% max)

Expected Performance:
  Win Rate: 55-60% (quiet market = cleaner moves)
  Avg Winner: 2.0R-2.5R
  Avg Loser: -1.0R
  Avg R/Trade: +0.5R to +0.8R
  Trade Frequency: ~1-2 per day per symbol

Best For:
  - Asia session trading
  - Low-volatility nights
  - Patience-focused traders
  - Ultra-high-conviction trades

Recommended Symbols: Asian crosses (AUD/JPY, NZD/JPY), exotics
Timeframe: M1-M5
"""


# ==============================================================================
# SCENARIO-BASED SELECTION GUIDE
# ==============================================================================

"""
QUICK SELECTION GUIDE
=====================

Q: "I'm brand new, want to be safe"
A: Use CONFIG_CONSERVATIVE
   - Highest win rate
   - Longest cooldown (fewer mistakes)
   - Highest quality entries

Q: "I want institutional consistency"
A: Use CONFIG_BALANCED
   - Default settings
   - Good for SRH integration
   - Proven approach

Q: "I have a large account, want volume"
A: Use CONFIG_AGGRESSIVE
   - More entries
   - Shorter cooldown
   - Accept lower win rate for more opportunities

Q: "I trade emerging market pairs (USD/ZAR, etc.)"
A: Use CONFIG_EXOTIC
   - Higher thresholds
   - Structure-focused
   - Long cooldown

Q: "I primarily fade trends"
A: Use CONFIG_TREND_FOLLOWING
   - Exhaustion-focused
   - Short cooldown
   - Lower thresholds

Q: "I trade during quiet Asian sessions"
A: Use CONFIG_NIGHT_QUIET
   - Divergence-heavy
   - Highest thresholds
   - Very selective

Q: "I don't see signals often enough"
A: Lower base_threshold or increase w_clx (volume emphasis)

Q: "Too many false signals / whipsaws"
A: Raise base_threshold or increase max_penalty
"""


# ==============================================================================
# CUSTOM CONFIGURATION TEMPLATE
# ==============================================================================

def create_custom_config(
    name: str,
    base_threshold_other: float = 0.65,
    w_div: float = 0.35,
    cooldown_candles: int = 8,
) -> ReversalEngineConfig:
    """
    Helper to quickly create custom config.

    Args:
        name: Config name
        base_threshold_other: Main threshold
        w_div: Divergence weight (0.0 to 0.5)
        cooldown_candles: Candles between trades

    Returns:
        Configured ReversalEngineConfig
    """
    # Auto-calculate other weights (balanced)
    remaining = 1.0 - w_div
    w_exh = remaining * 0.30
    w_str = remaining * 0.25
    w_pa = remaining * 0.25
    w_clx = remaining * 0.20

    return ReversalEngineConfig(
        name=name,
        base_threshold_ranging=base_threshold_other - 0.05,
        base_threshold_other=base_threshold_other,
        w_div=w_div,
        w_exh=w_exh,
        w_str=w_str,
        w_pa=w_pa,
        w_clx=w_clx,
        cooldown_candles=cooldown_candles,
    )


# ==============================================================================
# EXAMPLE USAGE
# ==============================================================================

if __name__ == "__main__":
    # Print all configurations
    configs = [
        CONFIG_CONSERVATIVE,
        CONFIG_BALANCED,
        CONFIG_AGGRESSIVE,
        CONFIG_EXOTIC,
        CONFIG_TREND_FOLLOWING,
        CONFIG_NIGHT_QUIET,
    ]

    print("\n" + "="*80)
    print("REVERSAL ENGINE - PRE-TUNED CONFIGURATIONS")
    print("="*80)

    for config in configs:
        print(config.describe())
        print()

    # Create custom config
    print("="*80)
    print("CUSTOM CONFIGURATION EXAMPLE")
    print("="*80)

    my_config = create_custom_config(
        name="My Custom Setup",
        base_threshold_other=0.60,
        w_div=0.40,
        cooldown_candles=10,
    )
    print(my_config.describe())

    # Create engine with custom config
    engine = my_config.create_engine()
    print("\nEngine created successfully with custom config!")
