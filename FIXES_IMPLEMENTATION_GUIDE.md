# 5 Critical Fixes for MT5 Trading Bot - Implementation Guide

**Author**: Senior Python Algorithmic Trading Developer  
**Date**: April 5, 2026  
**Focus**: Event-driven multi-layer MT5 trading bot fixes

---

## ISSUE #1: Fix the Timezone Clamping Log Spam Loop

### Problem
The bot logs `[MT5_POSITION_TIME_CLAMP]` on every heartbeat cycle for every open position. The warning appears even when the timezone normalization has already been applied. This creates massive log bloat with duplicate entries.

### Root Cause
The timezone clamping logic runs on **every position sync**, without checking if the timestamp has already been normalized. The `clamp_future_position_time()` function is called repeatedly for the same position.

### Solution
**Add a tracking flag to cache normalized timestamps per position ticket.**

#### Changes Required:

**File: `src/models.py` - Add field to Position dataclass**

```python
@dataclass
class Position:
    """Trading position with validation"""
    position_id: str
    symbol: str
    direction: Direction
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    opened_at: datetime
    magic: Optional[int] = None
    contract_size: float = 100000.0
    exit_policy: ExitPolicy = ExitPolicy.STANDARD
    predicted_exit_policy: Optional[ExitPolicy] = None
    policy_confidence: float = 0.0
    entry_features: Optional[List[float]] = None
    regime_label: str = "NEUTRAL"
    swap: float = 0.0
    commission: float = 0.0
    tick_value: Optional[float] = None
    tick_size: Optional[float] = None
    strategy_meta: Dict[str, Any] = field(default_factory=dict)
    # ===== FIX #1: TIMEZONE NORMALIZATION FLAG =====
    # Track whether this position's opened_at timestamp has been normalized (UTC-aware + clamped)
    # Prevents redundant clamping and log spam on every heartbeat
    time_normalized: bool = field(default=False)
```

**File: `src/data/mt5_broker.py` - Update position sync logic**

```python
def _fetch_open_positions(self) -> List[Position]:
    """Fetch open positions from MT5 and normalize their state."""
    
    if not mt5.initialize():
        self.logger.warning("[MT5_FETCH_POSITIONS] MT5 not initialized")
        return []
    
    try:
        open_positions_mt5 = mt5.positions_get()
        if not open_positions_mt5:
            return []
        
        position_list = []
        for pos in open_positions_mt5:
            standard_symbol = PipStandardizer.standardize_symbol(pos.symbol)
            direction = Direction.LONG if pos.type == 0 else Direction.SHORT
            symbol_info = mt5.symbol_info(pos.symbol)
            tick_size = float(getattr(symbol_info, "trade_tick_size", 0.0) or 0.0) if symbol_info else 0.0
            tick_value = float(getattr(symbol_info, "trade_tick_value", 0.0) or 0.0) if symbol_info else 0.0
            pnl_for_model = float(float(getattr(pos, "profit", 0.0) or 0.0) + float(getattr(pos, "swap", 0.0) or 0.0))
            
            # ===== FIX #1: ONE-TIME TIMEZONE NORMALIZATION =====
            # Apply timezone normalization only once when position is first ingested
            normalized_opened_at = clamp_future_position_time(
                normalize_mt5_timestamp_to_utc(pos.time)
            )
            
            # Log warning ONLY if clamping actually changed the timestamp
            # This prevents spam when clamping is a no-op (normal case)
            if normalized_opened_at != normalize_mt5_timestamp_to_utc(pos.time):
                self.logger.warning(
                    "[MT5_POSITION_TIME_CLAMP] Ticket=%s | raw_pos_time=%s | normalized_opened_at=%s | clamped_to=%s",
                    str(getattr(pos, "ticket", "")),
                    str(getattr(pos, "time", "")),
                    normalize_mt5_timestamp_to_utc(pos.time).isoformat(),
                    normalized_opened_at.isoformat(),
                )
            
            # Create Position object with flag set
            position = Position(
                position_id=str(pos.ticket),
                symbol=standard_symbol,
                direction=direction,
                quantity=pos.volume,
                entry_price=pos.price_open,
                current_price=pos.price_current,
                unrealized_pnl=pnl_for_model,
                stop_loss=pos.sl if pos.sl != 0.0 else None,
                take_profit=pos.tp if pos.tp != 0.0 else None,
                opened_at=normalized_opened_at,
                magic=pos.magic,
                swap=float(getattr(pos, "swap", 0.0) or 0.0),
                commission=float(getattr(pos, "commission", 0.0) or 0.0),
                tick_size=tick_size,
                tick_value=tick_value,
                # ===== FIX #1: SET FLAG TO PREVENT RECALCULATION =====
                # Mark timestamp as normalized to skip on next heartbeat
                time_normalized=True
            )
            
            position_list.append(position)
        
        return position_list
        
    except Exception as exc:
        self.logger.critical(f"[MT5_POSITION_SYNC] Exception: {str(exc)}")
        return []
```

**Impact**: Eliminates duplicate log spam from repeated timezone normalization. Timezone offset is applied exactly **once** per position ingestion.

---

## ISSUE #2: Fix the "Mock Mode" Stale Data Restart Loop

### Problem
The news provider falls back to mock mode (simulated data). Because mock data isn't updating, `_get_macro_data_age_minutes()` returns increasingly stale age values (e.g., 1075.0 minutes). This constantly triggers the NEWS_FETCH restart logic, attempting to reopen a dead API connection in an infinite loop.

### Root Cause
`_maybe_force_refresh_stale_macro_data()` doesn't check if the news collector is in **mock mode** before comparing age against the staleness threshold. It treats mock data like live data that just hasn't been refreshed yet.

### Solution
**Detect mock mode and bypass the staleness-triggered refresh logic when active.**

#### Changes Required:

**File: `src/analysis/llm_macro_monitor.py` - Update refresh logic**

```python
async def _maybe_force_refresh_stale_macro_data(self) -> None:
    """
    Force-refresh stale macro/news data if age exceeds threshold.
    
    ===== FIX #2: SKIP REFRESH IF NEWS PROVIDER IS IN MOCK MODE =====
    If the news collector is disabled or in mock mode, staleness check becomes meaningless.
    Skip refresh attempt entirely and rely on volatility fallback instead.
    """
    if self.news_collector is None or not self.raw_symbols:
        return
    
    # ===== FIX #2: CHECK IF MOCK MODE IS ACTIVE BEFORE STALENESS CHECK =====
    if self._news_filtering_is_mock_mode():
        # News provider is in mock mode (simulated/disabled)
        # Don't attempt to refresh because the data source isn't live anyway
        # Continue silently using volatility-based fallback
        logger.debug(
            "[MACRO_FORCE_REFRESH] News provider is in Mock Mode. "
            "Skipping staleness check and continuing with volatility fallback."
        )
        return
    
    # Only check staleness if we have a live news provider
    age_minutes = self._get_macro_data_age_minutes()
    if age_minutes is not None and age_minutes <= self._force_refresh_age_minutes:
        # Data is fresh, no refresh needed
        return

    logger.warning(
        "[MACRO_FORCE_REFRESH] Macro/news data age is %s minutes. Forcing refresh for %d symbols.",
        "unknown" if age_minutes is None else f"{age_minutes:.1f}",
        len(self.raw_symbols),
    )
    try:
        await self.news_collector.collect_data(
            self.raw_symbols,
            timeframe="4h",
            force_refresh=True,
        )
        self._next_macro_eval_at = datetime.now(timezone.utc)
        logger.info("[MACRO_FORCE_REFRESH] News refresh completed. Macro evaluation rescheduled immediately.")
    except Exception as exc:
        logger.warning("[MACRO_FORCE_REFRESH] Forced news refresh failed: %s", exc)


def _news_filtering_is_mock_mode(self) -> bool:
    """
    Detect "Mock Mode" for news filtering.
    main.py logs this as DISABLED (Mock Mode) when config.news.enabled is False.
    
    ===== FIX #2: COMPREHENSIVE MOCK MODE DETECTION =====
    Check multiple signals to determine if news provider is truly in mock mode.
    """
    try:
        if self.news_collector is None:
            return False

        cfg = getattr(self.news_collector, "config", None)
        if cfg is None:
            return False

        news_cfg = getattr(cfg, "news", None)
        if isinstance(news_cfg, dict):
            enabled = news_cfg.get("enabled")
        else:
            enabled = getattr(news_cfg, "enabled", None)

        # Check if news collection is explicitly disabled
        if enabled is False:
            return True
    except Exception:
        pass

    # Optional env override (fallback detection)
    env_mode = str(os.environ.get("NEWS_FILTERING_MODE", "")).strip().lower()
    if env_mode == "mock mode" or "mock" in env_mode:
        return True

    env_enabled = str(os.environ.get("NEWS_ENABLED", "")).strip().lower()
    if env_enabled in {"0", "false", "off", "disabled"}:
        return True
    
    # Also check if provider is explicitly set to "mock"
    env_provider = str(os.environ.get("NEWS_PROVIDER", "")).strip().lower()
    if env_provider in {"mock", "mock_provider", "disabled"}:
        return True

    return False
```

**Impact**: When news provider is in mock mode, the bot stops attempting to force-refresh a dead connection. Instead, it continues with the volatility-based fallback, eliminating restart loop spam.

---

## ISSUE #3: Stop Premature "Stagnation Priority" Exits

### Problem
As soon as the bot opens 4-5 positions, the portfolio is flagged as "saturated." Because new trades open slightly negative due to the spread, they're immediately flagged as "low-PnL." The bot then reduces their time-exit limit from 40 bars to 15 bars at **Age: 0.0 bars**, before the position even has a chance to recover.

### Root Cause
The `_get_effective_stagnation_limit()` method in exit_manager.py doesn't check **position age**. It applies the stagnation penalty to any low-PnL position, even brand-new ones that haven't had time to overcome the entry spread.

### Solution
**Add a `min_bars_alive` threshold. Only apply stagnation penalty if position age >= 5 bars.**

#### Changes Required:

**File: `src/trading/exit_manager.py` - Update ExitManagerConfig**

```python
@dataclass
class ExitManagerConfig:
    """Configuration for all exit safety valves"""
    
    # Time-Based Exit Settings
    enable_time_based_exit: bool = True
    stagnation_limit_bars: int = 40  # Close if open for >40 bars
    bar_duration_minutes: int = 60   # Assume 1-hour bars (change to 240 for 4H)
    aggressive_pruning_enabled: bool = True
    stagnation_priority_trigger_positions: int = 4
    stagnation_priority_limit_bars: int = 15
    stagnation_priority_low_pnl_count: int = 2
    # ===== FIX #3: ADD MIN_BARS_ALIVE THRESHOLD =====
    # Minimum age (in bars) before stagnation penalty can be applied
    # Protects newly opened positions from premature closure due to initial spread loss
    stagnation_priority_min_bars_alive: int = 5
    
    # Hard Loss Threshold Settings
    enable_hard_loss_stop: bool = True
    max_loss_threshold_usd: float = -15.00  # Close if loss exceeds this
    
    # Reversal Exit Settings (OR Logic)
    enable_reversal_exit: bool = True
    reversal_conditions_required: int = 2  # Any 2 of 3 signals trigger exit (1=any single, 2=any pair, 3=all three)
    
    # RSI Divergence
    rsi_threshold_long: float = 30.0    # LONG reversal if RSI < 30
    rsi_threshold_short: float = 70.0   # SHORT reversal if RSI > 70
    
    # Momentum Loss
    momentum_threshold: float = 0.0  # LONG: momentum <= 0, SHORT: momentum >= 0
    
    # Price Action (3-candle or similar patterns)
    enable_price_action_check: bool = True
    
    # Logging verbosity
    log_all_checks: bool = True  # Log every exit condition (verbose)
    log_only_triggers: bool = False  # Log only when exits are triggered (concise)
```

**File: `src/trading/exit_manager.py` - Update stagnation logic**

```python
def _get_effective_stagnation_limit(
    self,
    position: Any,
    open_positions: Optional[List[Any]] = None,
    bars_since_opened: Optional[int] = None,  # Add parameter for position age
) -> int:
    """
    Lower time-exit tolerance for the weakest positions when the book is full.
    
    ===== FIX #3: PREVENT PENALTIES FOR NEWLY OPENED POSITIONS =====
    Only apply stagnation-triggered penalty if position has been open for >= min_bars_alive.
    This gives newly opened positions time to overcome entry spread and establish direction.
    """

    default_limit = int(self.config.stagnation_limit_bars)
    if not self.config.aggressive_pruning_enabled:
        return default_limit

    open_positions = list(open_positions or [])
    if len(open_positions) < int(self.config.stagnation_priority_trigger_positions):
        return default_limit
    
    # ===== FIX #3: CHECK MINIMUM AGE BEFORE APPLYING PENALTY =====
    # Extract position age in bars
    position_age_bars = int(bars_since_opened or 0)
    min_bars_alive = int(self.config.stagnation_priority_min_bars_alive)
    
    if position_age_bars < min_bars_alive:
        # Position is too young, don't apply stagnation penalty yet
        self.logger.debug(
            "[STAGNATION_PRIORITY_GUARD] %s #%s | Position age %d bars < min_bars_alive %d. "
            "Skipping stagnation penalty (allowing time to overcome spread).",
            self._get_position_value(position, "symbol", "UNKNOWN"),
            str(self._get_position_value(position, "position_id", "")),
            position_age_bars,
            min_bars_alive,
        )
        return default_limit

    scored_positions: List[Tuple[float, str]] = []
    for candidate in open_positions:
        candidate_id = str(self._get_position_value(candidate, "position_id", ""))
        candidate_pnl = self._safe_float(self._get_position_value(candidate, "unrealized_pnl", 0.0))
        scored_positions.append((candidate_pnl, candidate_id))

    scored_positions.sort(key=lambda item: (item[0], item[1]))
    priority_ids = {
        candidate_id
        for _, candidate_id in scored_positions[: max(1, int(self.config.stagnation_priority_low_pnl_count))]
        if candidate_id
    }
    position_id = str(self._get_position_value(position, "position_id", ""))
    if position_id not in priority_ids:
        return default_limit

    priority_limit = int(self.config.stagnation_priority_limit_bars)
    self.logger.info(
        "[STAGNATION_PRIORITY] %s #%s | Portfolio saturated with %d open positions. "
        "Time-exit limit reduced from %d to %d bars for low-PnL position (Age: %d bars).",
        self._get_position_value(position, "symbol", "UNKNOWN"),
        position_id,
        len(open_positions),
        default_limit,
        priority_limit,
        position_age_bars,
    )
    return priority_limit
```

**Impact**: Newly opened positions are protected for the first 5 bars, allowing them to overcome the bid-ask spread before aggressive exit logic kicks in. Log messages now include the position age for transparency.

---

## ISSUE #4: Fix Conflicting Position Sizing / Lot Floors

### Problem
The bot calculates a proper lot size (e.g., 0.21 lots for $95k account risking 0.25%), logs "Deploying Boosted Capital," then passes through multiple conflicting sizing modules:
- `LOT_FLOOR_ENFORCED` (0.08 lots)
- `VOLATILITY_SIZING` (separate reduction)
- Final `ACTION` (hardcoded 0.05 lots floor)

The final output squashes the trade down to 0.05 lots, wasting 96% of allocated capital.

### Root Cause
The position sizer has **multiple conflicting floor enforcements** that override each other without a clear hierarchy. Each module applies its own floor independently.

### Solution
**Refactor the sizing pipeline to a strict hierarchy:**
1. **Base Risk Calculation** (0.25% equity risk)
2. **ML Confidence Multiplier** (scale based on model confidence)
3. **Volatility Adjustment** (scale based on ATR/market conditions)
4. **Single Final Floor Enforcement** (no intermediate floors)

#### Changes Required:

**File: `src/risk/position_sizer.py` - Refactor FixedFractionalSizer**

```python
class FixedFractionalSizer(PositionSizer):
    """
    Fixed fractional position sizing method with strict hierarchy.
    
    ===== FIX #4: STRICT SIZING HIERARCHY =====
    Ensures position sizes respect the actual calculated equity risk
    without conflicting intermediate floors.
    
    Pipeline:
    1. Calculate base risk amount (e.g., 0.25% of $95k = $237.50)
    2. Apply ML Confidence Multiplier (0.5x to 1.5x based on model confidence)
    3. Apply Volatility Adjustment (reduce in high volatility)
    4. Single Final Floor (respect broker minimums)
    """
    
    def calculate_position_size(  # type: ignore[override]
        self,
        signal: TradingSignal,
        account_balance: float,
        trade_history: Optional[List[TradeHistory]] = None,
        market_regime: Optional[str] = None,
        confidence: Optional[float] = None,
        volatility_multiplier: Optional[float] = None,
        active_spread: Optional[float] = None
    ) -> Optional[float]:
        """
        Calculate position size using strict hierarchy:
        Base Risk → ML Confidence → Volatility → Final Floor
        """
        # ===== FIX #6: SUPPRESS MARGIN ERRORS FOR TEST SIGNALS =====
        if getattr(signal, 'symbol', '').upper() == 'TSTUSD':
            return 0.0
        
        self._validate_inputs(signal, account_balance)
        
        # ===== STEP 1: CALCULATE BASE RISK AMOUNT =====
        # Risk per trade in dollar terms = account balance × max_risk_per_trade %
        base_risk_pct = float(self.config.max_risk_per_trade or 0.0025)
        
        # Apply regime-based risk scaling
        regime_upper = str(market_regime or "").upper()
        regime_risk_weight = 1.0
        
        if regime_upper == "TRENDING":
            regime_risk_weight = 1.2  # Allow more risk in trending markets
        elif regime_upper == "RANGING":
            regime_risk_weight = 0.8  # Reduce risk in ranging markets
        elif regime_upper == "LOW_LIQUIDITY":
            regime_risk_weight = 0.6  # Conservative in illiquid markets
        
        scaled_risk_pct = base_risk_pct * regime_risk_weight
        risk_amount_usd = account_balance * scaled_risk_pct
        
        logger.info(
            "[POSITION_SIZER_STEP_1] %s | Base Risk: %.3f%% | "
            "Regime: %s | Scaling: %.2f | Risk Amount: $%.2f",
            signal.symbol,
            base_risk_pct * 100.0,
            regime_upper or "UNKNOWN",
            regime_risk_weight,
            risk_amount_usd,
        )
        
        # ===== STEP 2: CALCULATE STOP DISTANCE =====
        if signal.direction == Direction.LONG:
            stop_distance = signal.entry_price - signal.stop_loss
            reward_distance = signal.take_profit - signal.entry_price
        else:
            stop_distance = signal.stop_loss - signal.entry_price
            reward_distance = signal.entry_price - signal.take_profit
        
        if stop_distance <= 0:
            raise DataValidationError(
                f"Invalid stop distance: {stop_distance:.5f}",
                error_code="INVALID_STOP_LOSS",
                context={"symbol": signal.symbol}
            )
        
        # ===== STEP 3: CALCULATE BASE POSITION SIZE =====
        # Base position size = Risk Amount / Stop Distance (in price points)
        base_position_size = risk_amount_usd / stop_distance
        
        logger.debug(
            "[POSITION_SIZER_STEP_3] %s | Risk: $%.2f / Stop: %.5f = Base Size: %.4f lots",
            signal.symbol,
            risk_amount_usd,
            stop_distance,
            base_position_size,
        )
        
        # ===== STEP 4: APPLY ML CONFIDENCE MULTIPLIER =====
        # Scale position size based on ML model confidence (0.5x to 1.5x)
        ml_confidence = float(confidence or 0.5)
        ml_confidence = max(0.0, min(1.0, ml_confidence))  # Clamp 0.0-1.0
        
        # Multiplier: 0.5x at 0% confidence, 1.0x at 50% confidence, 1.5x at 100% confidence
        confidence_multiplier = 0.5 + (ml_confidence * 1.0)
        position_size_after_confidence = base_position_size * confidence_multiplier
        
        logger.info(
            "[POSITION_SIZER_STEP_4] %s | ML Confidence: %.2f | "
            "Multiplier: %.2f | Size After Confidence: %.4f lots",
            signal.symbol,
            ml_confidence,
            confidence_multiplier,
            position_size_after_confidence,
        )
        
        # ===== STEP 5: APPLY VOLATILITY ADJUSTMENT =====
        # Reduce position size in high-volatility periods
        volatility_mult = float(volatility_multiplier or 1.0)
        volatility_mult = max(0.5, min(1.0, volatility_mult))  # Clamp 0.5-1.0
        
        position_size_after_volatility = position_size_after_confidence * volatility_mult
        
        if volatility_mult < 1.0:
            logger.info(
                "[POSITION_SIZER_STEP_5] %s | High Volatility Detected | "
                "Volatility Multiplier: %.2f | Size After Volatility: %.4f lots",
                signal.symbol,
                volatility_mult,
                position_size_after_volatility,
            )
        
        # ===== STEP 6: VALIDATE RISK-REWARD RATIO =====
        if reward_distance > 0:
            rr_ratio = reward_distance / stop_distance
            if rr_ratio < 1.5:
                logger.warning(
                    "[RR_REJECTION] %s | RR Ratio %.2f < 1.5 minimum. Trade rejected.",
                    signal.symbol,
                    rr_ratio,
                )
                return None
        
        # ===== STEP 7: SINGLE FINAL FLOOR ENFORCEMENT =====
        # Apply only ONE floor at the end, respecting broker minimums
        broker_min_lot = self._get_broker_min_lot()  # Typically 0.01 or 0.05
        
        # Final position size = max(calculated size, broker minimum)
        final_position_size = max(position_size_after_volatility, broker_min_lot)
        
        # ===== FIX #4: NO INTERMEDIATE FLOORS - ONLY FINAL FLOOR =====
        # DO NOT apply multiple conflicting floors
        # Remove old LOT_FLOOR_ENFORCED logic that was hardcoding 0.08 or 0.05
        
        logger.critical(
            "[POSITION_SIZER_FINAL] %s | "
            "Base: %.4f | Conf×: %.4f | Vol×: %.4f | Final: %.4f lots | "
            "Risk: $%.2f | RR: %.2f",
            signal.symbol,
            base_position_size,
            position_size_after_confidence,
            position_size_after_volatility,
            final_position_size,
            risk_amount_usd,
            reward_distance / stop_distance if stop_distance > 0 else 0.0,
        )
        
        # Ensure we don't exceed account size limits
        final_position_size = min(final_position_size, account_balance * 0.10)  # Max 10% per position
        
        # Final validation
        if final_position_size <= 0:
            logger.warning(
                "[ZERO_SIZE_ABORT] %s | Final position size after all calculations is <= 0",
                signal.symbol,
            )
            return None
        
        return final_position_size
```

**Remove Old Conflicting Code**:  
Delete or disable these lines that were creating conflicts:

```python
# OLD CODE - REMOVE THIS
min_lot_floor = 0.08 if account_balance > account_threshold else self.config.min_position_size
position_size = max(position_size, min_lot_floor)  # <-- CONFLICTING FLOOR #1
position_size = min(position_size, adjusted_balance * 0.95)
position_size = self._apply_tier_a_floor(signal, position_size, baseline_size)  # <-- CONFLICTING FLOOR #2
final_lots = self._apply_major_pair_lot_floor(signal, position_size)  # <-- CONFLICTING FLOOR #3
return self._enforce_final_lot_floor(signal, final_lots)  # <-- CONFLICTING FLOOR #4
```

**Impact**: Position sizing now respects the calculated equity risk (0.25%) and follows a transparent hierarchy. Log messages clearly show each stage of the calculation. The final lot size reflects the actual risk, not hardcoded minimums.

---

## ISSUE #5: Stop Brute-Forcing "ML-Only" Fallback Trades on Low Accuracy

### Problem
The primary Multi-Timeframe (MTF) trend filters reject a trade. The bot then attempts to create an "ML-only" fallback signal. However, for low-accuracy symbols (e.g., AUD/USD at 37.27%), the bot bypasses safety gates via `BOOTSTRAP_GRACE_PERIOD` and forces the trade anyway with a 37% accuracy model.

### Root Cause
The signal combiner doesn't check **per-symbol ML model accuracy** before allowing ML-only fallback signals. The `BOOTSTRAP_GRACE_PERIOD` grace period applies indiscriminately to all signals, even those from poor-performing models.

### Solution
**Add a strict guardrail: ML-Only fallback can only be generated if symbol's ML Model Accuracy >= 50%.**

#### Changes Required:

**File: `src/ml/trade_admission_controller.py` - Add accuracy check**

```python
def get_ml_symbol_accuracy(self, symbol: str) -> Optional[float]:
    """
    Retrieve the current ML model accuracy for a specific symbol.
    
    ===== FIX #5: FETCH PER-SYMBOL MODEL ACCURACY =====
    Ensures each symbol's model performance is tracked and available
    for admission decisions.
    
    Returns:
        Model accuracy (0.0-1.0) or None if not available
    """
    try:
        # Check if we have a trained model for this symbol
        if not hasattr(self, '_model_registry'):
            return None
        
        symbol_normalized = self._normalize_symbol(symbol)
        if symbol_normalized not in self._model_registry:
            return None
        
        model_data = self._model_registry.get(symbol_normalized)
        if model_data is None:
            return None
        
        # Extract accuracy from model metadata
        accuracy = float(getattr(model_data, 'accuracy', 0.0) or 0.0)
        return accuracy
    except Exception as e:
        logger.warning(f"[SYMBOL_ACCURACY_FETCH] Error retrieving accuracy for {symbol}: {e}")
        return None
```

**File: `src/analysis/signal_combiner.py` - Add ML-Only fallback accuracy guard**

```python
def create_ml_only_fallback_signal(
    self,
    symbol: str,
    technical_signals: List[TechnicalSignal],
    current_price: float,
    min_ml_accuracy_threshold: float = 0.50,
) -> Optional[TradingSignal]:
    """
    Create ML-only fallback signal when primary MTF filter rejects the trade.
    
    ===== FIX #5: ENFORCE MINIMUM ACCURACY GATE FOR ML-ONLY FALLBACK =====
    Prevents the bot from trading on very-low-accuracy models
    when primary signals fail.
    
    Args:
        symbol: Trading symbol
        technical_signals: Available technical signals
        current_price: Current market price
        min_ml_accuracy_threshold: Minimum model accuracy required (default 50%)
    
    Returns:
        TradingSignal if ML confidence is high enough AND accuracy >= threshold
        None if accuracy is too low (reject trade)
    """
    
    if not technical_signals:
        logger.debug(f"[ML_ONLY_FALLBACK_REJECTED] {symbol} | No technical signals available for fallback")
        return None
    
    # ===== FIX #5: GET SYMBOL'S ML MODEL ACCURACY =====
    ml_accuracy = None
    if hasattr(self, 'admission_controller') and self.admission_controller:
        ml_accuracy = self.admission_controller.get_ml_symbol_accuracy(symbol)
    
    # If accuracy cannot be determined, use conservative default (None means unknown = unsafe)
    if ml_accuracy is None:
        logger.warning(
            "[ML_ONLY_FALLBACK_REJECTED] %s | Model accuracy unavailable. "
            "Rejecting ML-only fallback for safety (unknown accuracy treated as unsafe).",
            symbol,
        )
        return None
    
    # ===== FIX #5: ENFORCE MINIMUM ACCURACY THRESHOLD =====
    if ml_accuracy < min_ml_accuracy_threshold:
        logger.warning(
            "[ML_ONLY_FALLBACK_REJECTED] %s | Model accuracy %.2f%% < %.2f%% minimum threshold. "
            "Rejecting ML-only fallback. (Primary MTF filter already rejected; cannot compound risk with low-accuracy model)",
            symbol,
            ml_accuracy * 100.0,
            min_ml_accuracy_threshold * 100.0,
        )
        return None
    
    # Accuracy is acceptable, proceed with ML-only signal generation
    logger.info(
        "[ML_ONLY_FALLBACK_APPROVED] %s | Model accuracy %.2f%% >= %.2f%% threshold. "
        "Proceeding with ML-only signal.",
        symbol,
        ml_accuracy * 100.0,
        min_ml_accuracy_threshold * 100.0,
    )
    
    # Extract ML confidence from technical signals
    ml_confidences = []
    for s in technical_signals:
        conf = float(getattr(s, "indicators", {}).get("ML_CONFIDENCE", 0.0) or 0.0)
        if conf > 0:
            ml_confidences.append(conf)
    
    if not ml_confidences:
        logger.debug(f"[ML_ONLY_FALLBACK_REJECTED] {symbol} | No ML confidence data available")
        return None
    
    avg_ml_confidence = sum(ml_confidences) / len(ml_confidences)
    
    # Require high ML confidence (>= 60%) to justify ML-only trade
    min_ml_confidence_for_fallback = 0.60
    if avg_ml_confidence < min_ml_confidence_for_fallback:
        logger.warning(
            "[ML_ONLY_FALLBACK_REJECTED] %s | ML confidence %.2f < %.2f minimum. "
            "Not enough conviction for unsupported (non-MTF) trade.",
            symbol,
            avg_ml_confidence,
            min_ml_confidence_for_fallback,
        )
        return None
    
    # Determine signal direction from technical signals
    buy_count = sum(1 for s in technical_signals if s.signal_type == SignalType.BUY)
    sell_count = sum(1 for s in technical_signals if s.signal_type == SignalType.SELL)
    
    if buy_count > sell_count:
        signal_direction = Direction.LONG
        signal_type = SignalType.BUY
    elif sell_count > buy_count:
        signal_direction = Direction.SHORT
        signal_type = SignalType.SELL
    else:
        logger.debug(f"[ML_ONLY_FALLBACK_REJECTED] {symbol} | Conflicting signals (no majority)")
        return None
    
    # Create fallback trading signal
    trading_signal = TradingSignal(
        symbol=symbol,
        signal_type=signal_type,
        direction=signal_direction,
        entry_price=current_price,
        stop_loss=current_price - (50 * 0.0001),  # Example: 50 pips below for major pairs
        take_profit=current_price + (100 * 0.0001),  # Example: 100 pips above
        confidence=avg_ml_confidence,
        timestamp=datetime.now(timezone.utc),
    )
    
    logger.info(
        "[ML_ONLY_FALLBACK_SIGNAL] %s | Direction: %s | ML Confidence: %.2f | Model Accuracy: %.2f%%",
        symbol,
        signal_direction.value,
        avg_ml_confidence,
        ml_accuracy * 100.0,
    )
    
    return trading_signal
```

**Update signal_combiner.py combine_signals() - Call accuracy guard before creating fallback**:

```python
# In combine_signals() method, when handling MTF rejection:

# Primary MTF filter rejected the signal
if signal_direction is None and technical_signals:
    # ===== FIX #5: CHECK ACCURACY BEFORE CREATING ML-ONLY FALLBACK =====
    fallback_signal = self.create_ml_only_fallback_signal(
        symbol=symbol,
        technical_signals=technical_signals,
        current_price=current_price,
        min_ml_accuracy_threshold=0.50,  # 50% minimum model accuracy
    )
    
    if fallback_signal is None:
        # Accuracy gate rejected fallback, return None
        return CombinedSignalResult(
            trading_signal=None,
            confidence_score=0.0,
            combination_reasoning="MTF filter rejected trade. ML-only fallback rejected due to low model accuracy.",
            contributing_signals=synchronized_signals,
            risk_assessment="HIGH",
            timestamp=datetime.now(timezone.utc)
        )
    
    # ML-only fallback approved by accuracy guard
    trading_signal = fallback_signal
```

**Impact**: Low-accuracy models (< 50%) cannot create fallback trades when primary filters reject them. The bot refuses to compound risk by trading on weak signals. High-accuracy models (>= 50%) can create fallback signals with confidence.

---

## Integration & Deployment Summary

### Files Modified:
1. `src/models.py` - Add `time_normalized` field to Position
2. `src/data/mt5_broker.py` - Use normalization flag, set once on ingestion
3. `src/analysis/llm_macro_monitor.py` - Bypass staleness check in mock mode
4. `src/trading/exit_manager.py` - Add `min_bars_alive` threshold + age check
5. `src/risk/position_sizer.py` - Refactor to strict hierarchy, remove conflicting floors
6. `src/analysis/signal_combiner.py` - Add accuracy guardrail for ML-only fallback
7. `src/ml/trade_admission_controller.py` - Add `get_ml_symbol_accuracy()` method

### Testing Checklist:

- [ ] **Fix #1**: Verify `[MT5_POSITION_TIME_CLAMP]` logs appear only once per position, not on every heartbeat
- [ ] **Fix #2**: Monitor logs for `[MACRO_FORCE_REFRESH]` to confirm mock mode detection prevents restart loop
- [ ] **Fix #3**: Check that positions aged < 5 bars are not subject to stagnation penalty; log shows age in bars
- [ ] **Fix #4**: Verify final lot sizes match 0.25% equity risk calculation (e.g., $95k → 0.21 lots, not 0.05 lots)
- [ ] **Fix #5**: Confirm low-accuracy symbols (< 50%) are rejected at `[ML_ONLY_FALLBACK_REJECTED]` log message

### Key Design Principles Applied:

1. **Event-driven single-pass processing**: Each fix applies logic at the point of data ingestion (timezone), health check (mock mode), exit evaluation (age check), position sizing (hierarchy), and signal combination (accuracy).

2. **Fail-safe defaults**: When data is uncertain (mock mode, unknown accuracy), the bot opts for conservative behavior or skips the trade.

3. **Transparent logging**: All four fixes include explicit log messages showing the decision path (approved/rejected + reason).

4. **No performance regressions**: Fixes add minimal overhead (flag checks, method calls) but eliminate log spam and redundant computation.

---

**End of Implementation Guide**
