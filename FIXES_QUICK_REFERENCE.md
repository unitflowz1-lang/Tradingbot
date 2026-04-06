# Quick Reference: Line-by-Line Code Changes

## ISSUE #1: src/models.py - Add time_normalized field

**Location**: Line ~738 (Position dataclass)

**ADD:** After `strategy_meta: Dict[str, Any] = field(default_factory=dict)` line:

```python
    # ===== FIX #1: TIMEZONE NORMALIZATION FLAG =====
    # Track whether this position's opened_at timestamp has been normalized
    time_normalized: bool = field(default=False)
```

---

## ISSUE #2: src/analysis/llm_macro_monitor.py - Mock mode detection

**Location 1**: Lines 1149-1175 (\_maybe_force_refresh_stale_macro_data method)

**REPLACE** the existing method body with:

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
            logger.debug(
                "[MACRO_FORCE_REFRESH] News provider is in Mock Mode. "
                "Skipping staleness check and continuing with volatility fallback."
            )
            return
        
        age_minutes = self._get_macro_data_age_minutes()
        if age_minutes is not None and age_minutes <= self._force_refresh_age_minutes:
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
```

**Location 2**: Lines 867-903 (\_news_filtering_is_mock_mode method)

**REPLACE** the existing method with:

```python
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

            if enabled is False:
                return True
        except Exception:
            pass

        env_mode = str(os.environ.get("NEWS_FILTERING_MODE", "")).strip().lower()
        if env_mode == "mock mode" or "mock" in env_mode:
            return True

        env_enabled = str(os.environ.get("NEWS_ENABLED", "")).strip().lower()
        if env_enabled in {"0", "false", "off", "disabled"}:
            return True
        
        # ===== FIX #2: ALSO CHECK ENV PROVIDER SETTING =====
        env_provider = str(os.environ.get("NEWS_PROVIDER", "")).strip().lower()
        if env_provider in {"mock", "mock_provider", "disabled"}:
            return True

        return False
```

---

## ISSUE #3: src/trading/exit_manager.py - Min bars alive threshold

**Location 1**: Lines 45-47 (ExitManagerConfig dataclass)

**ADD** new config parameter after `stagnation_priority_low_pnl_count: int = 2`:

```python
    # ===== FIX #3: ADD MIN_BARS_ALIVE THRESHOLD =====
    # Minimum age (in bars) before stagnation penalty can be applied
    # Protects newly opened positions from premature closure due to initial spread loss
    stagnation_priority_min_bars_alive: int = 5
```

**Location 2**: Lines 372-404 (\_get_effective_stagnation_limit method)

**REPLACE** the method signature and add age check:

```python
    def _get_effective_stagnation_limit(
        self,
        position: Any,
        open_positions: Optional[List[Any]] = None,
        bars_since_opened: Optional[int] = None,  # ===== FIX #3: Add age parameter =====
    ) -> int:
        """Lower time-exit tolerance for the weakest positions when the book is full."""

        default_limit = int(self.config.stagnation_limit_bars)
        if not self.config.aggressive_pruning_enabled:
            return default_limit

        open_positions = list(open_positions or [])
        if len(open_positions) < int(self.config.stagnation_priority_trigger_positions):
            return default_limit
        
        # ===== FIX #3: CHECK MINIMUM AGE BEFORE APPLYING PENALTY =====
        position_age_bars = int(bars_since_opened or 0)
        min_bars_alive = int(self.config.stagnation_priority_min_bars_alive)
        
        if position_age_bars < min_bars_alive:
            self.logger.debug(
                "[STAGNATION_PRIORITY_GUARD] %s #%s | Position age %d bars < min_bars_alive %d. "
                "Skipping stagnation penalty (allowing time to overcome spread).",
                self._get_position_value(position, "symbol", "UNKNOWN"),
                str(self._get_position_value(position, "position_id", "")),
                position_age_bars,
                min_bars_alive,
            )
            return default_limit

        # ... rest of method continues as before, but update the final log message:
        self.logger.info(
            "[STAGNATION_PRIORITY] %s #%s | Portfolio saturated with %d open positions. "
            "Time-exit limit reduced from %d to %d bars for low-PnL position (Age: %d bars).",  # ===== FIX #3: Include age in log =====
            self._get_position_value(position, "symbol", "UNKNOWN"),
            position_id,
            len(open_positions),
            default_limit,
            priority_limit,
            position_age_bars,  # ===== FIX #3: Log position age =====
        )
        return priority_limit
```

---

## ISSUE #4: src/risk/position_sizer.py - Strict sizing hierarchy

**Location**: Lines 370-388 (FixedFractionalSizer.calculate_position_size method)

**REMOVE** these conflicting lines:

```python
# DELETE THIS SECTION:
        min_lot_floor = 0.08 if account_balance > account_threshold else self.config.min_position_size
        position_size = max(position_size, min_lot_floor)
        position_size = min(position_size, adjusted_balance * 0.95)
        position_size = self._apply_tier_a_floor(signal, position_size, baseline_size)
        final_lots = self._apply_major_pair_lot_floor(signal, position_size)
        return self._enforce_final_lot_floor(signal, final_lots)
```

**REPLACE** with new hierarchy (see full implementation in FIXES_IMPLEMENTATION_GUIDE.md for complete refactored method)

**Key changes:**
- Step 1: Calculate base risk = account × risk_pct
- Step 2: Calculate stop distance
- Step 3: Base position = Risk / Stop Distance
- Step 4: Apply ML Confidence Multiplier (0.5x to 1.5x)
- Step 5: Apply Volatility Adjustment (0.5x to 1.0x)
- Step 6: Validate RR ratio >= 1.5
- Step 7: Single final floor (broker minimum only)

---

## ISSUE #5: src/ml/trade_admission_controller.py - ML accuracy check

**Location**: Add new method (after line 521 approximately)

**ADD** this new method to TradeAdmissionController class:

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
            if not hasattr(self, '_model_registry'):
                return None
            
            symbol_normalized = self._normalize_symbol(symbol)
            if symbol_normalized not in self._model_registry:
                return None
            
            model_data = self._model_registry.get(symbol_normalized)
            if model_data is None:
                return None
            
            accuracy = float(getattr(model_data, 'accuracy', 0.0) or 0.0)
            return accuracy
        except Exception as e:
            logger.warning(f"[SYMBOL_ACCURACY_FETCH] Error retrieving accuracy for {symbol}: {e}")
            return None
```

---

## ISSUE #5: src/analysis/signal_combiner.py - ML-only fallback accuracy guard

**Location 1**: Add new method to SignalCombiner class (around line 300):

**ADD** this new method:

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
        """
        
        if not technical_signals:
            logger.debug(f"[ML_ONLY_FALLBACK_REJECTED] {symbol} | No technical signals available for fallback")
            return None
        
        # ===== FIX #5: GET SYMBOL'S ML MODEL ACCURACY =====
        ml_accuracy = None
        if hasattr(self, 'admission_controller') and self.admission_controller:
            ml_accuracy = self.admission_controller.get_ml_symbol_accuracy(symbol)
        
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
                "Rejecting ML-only fallback.",
                symbol,
                ml_accuracy * 100.0,
                min_ml_accuracy_threshold * 100.0,
            )
            return None
        
        logger.info(
            "[ML_ONLY_FALLBACK_APPROVED] %s | Model accuracy %.2f%% >= %.2f%% threshold. "
            "Proceeding with ML-only signal.",
            symbol,
            ml_accuracy * 100.0,
            min_ml_accuracy_threshold * 100.0,
        )
        
        # Extract ML confidence
        ml_confidences = []
        for s in technical_signals:
            conf = float(getattr(s, "indicators", {}).get("ML_CONFIDENCE", 0.0) or 0.0)
            if conf > 0:
                ml_confidences.append(conf)
        
        if not ml_confidences:
            logger.debug(f"[ML_ONLY_FALLBACK_REJECTED] {symbol} | No ML confidence data available")
            return None
        
        avg_ml_confidence = sum(ml_confidences) / len(ml_confidences)
        
        # Require high confidence for fallback
        if avg_ml_confidence < 0.60:
            logger.warning(
                "[ML_ONLY_FALLBACK_REJECTED] %s | ML confidence %.2f < 0.60 minimum.",
                symbol,
                avg_ml_confidence,
            )
            return None
        
        # Determine direction
        buy_count = sum(1 for s in technical_signals if s.signal_type == SignalType.BUY)
        sell_count = sum(1 for s in technical_signals if s.signal_type == SignalType.SELL)
        
        if buy_count > sell_count:
            signal_direction = Direction.LONG
            signal_type = SignalType.BUY
        elif sell_count > buy_count:
            signal_direction = Direction.SHORT
            signal_type = SignalType.SELL
        else:
            logger.debug(f"[ML_ONLY_FALLBACK_REJECTED] {symbol} | Conflicting signals")
            return None
        
        # Create fallback signal
        trading_signal = TradingSignal(
            symbol=symbol,
            signal_type=signal_type,
            direction=signal_direction,
            entry_price=current_price,
            stop_loss=current_price - (50 * 0.0001),
            take_profit=current_price + (100 * 0.0001),
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

**Location 2**: In combine_signals() method around line 410-420

**FIND** this section where MTF filter rejects the signal:

```python
        elif signal_direction is not None and technical_signals:
            # === ISSUE #3 FIX: Check exploration override before force-rejecting ===
            # ... existing code ...
```

**MODIFY** to add accuracy guard:

```python
        elif signal_direction is not None and technical_signals:
            # === ISSUE #3 FIX: ... existing comment ...
            technical_only_mode = bool(getattr(self, '_technical_only_mode_for_cycle', False))
            striking_mode_active = str(os.environ.get("SYSTEM_UNCAGED", "0")).lower() in {"1", "true", "yes", "on"} or \
                                  str(os.environ.get("SYSTEM_UNCAGED_V6", "0")).lower() in {"1", "true", "yes", "on"}
            is_exploration_mode = bool(technical_only_mode or striking_mode_active)
            signal_override_authorized = bool(getattr(self, '_override_authorized', False))
            
            if not (is_exploration_mode or signal_override_authorized) and confidence_score < min_conf_for_cycle:
                # ===== FIX #5: TRY ML-ONLY FALLBACK WITH ACCURACY CHECK =====
                fallback_signal = self.create_ml_only_fallback_signal(
                    symbol=symbol,
                    technical_signals=technical_signals,
                    current_price=current_price,
                    min_ml_accuracy_threshold=0.50,
                )
                
                if fallback_signal is not None:
                    trading_signal = fallback_signal
                    confidence_score = fallback_signal.confidence
                else:
                    # Accuracy guard rejected fallback
                    logger.warning(
                        f"[COMBINER_FORCE_PASS_REMOVED] {symbol} blocked | "
                        f"Confidence {confidence_score:.2f} < min {min_conf_for_cycle:.2f}."
                    )
                    logger.info(
                        "[FILTER_REJECT] %s | Reason: CONFIDENCE (%.2f < %.2f)",
                        symbol,
                        confidence_score,
                        min_conf_for_cycle,
                    )
                    trading_signal = None
            elif is_exploration_mode or signal_override_authorized:
                # Override path: exploration or authorization active
                logger.critical(
                    f"[COMBINER_CONFIDENCE_OVERRIDE] {symbol} | "
                    f"Confidence {confidence_score:.2f} < min {min_conf_for_cycle:.2f}, but ALLOWED due to "
                    f"exploration_mode={is_exploration_mode} | override_authorized={signal_override_authorized}"
                )
```

---

## Call Site Updates

### For Issue #3, when calling _get_effective_stagnation_limit():

**Find** any code that calls `_get_effective_stagnation_limit()`:

```python
# Current (old):
limit = self._get_effective_stagnation_limit(position, open_positions)

# Update to (new):
bars_since_opened = calculate_bars_age(position.opened_at)  # Your existing function
limit = self._get_effective_stagnation_limit(
    position, 
    open_positions,
    bars_since_opened=bars_since_opened,
)
```

---

## Testing Log Messages to Verify Each Fix

### Fix #1 Success Indicators:
```
✓ [MT5_POSITION_TIME_CLAMP] appears once per position, not repeated every heartbeat
✓ No repeated "Ticket=..." entries for same position
```

### Fix #2 Success Indicators:
```
✓ If news is in mock mode: "[MACRO_FORCE_REFRESH] News provider is in Mock Mode. Skipping..."
✓ No repeated "[MACRO_FORCE_REFRESH]" attempts with age_minutes > 10.0
```

### Fix #3 Success Indicators:
```
✓ "[STAGNATION_PRIORITY] ... (Age: 0 bars)" should NOT trigger penalty
✓ "[STAGNATION_PRIORITY_GUARD] ... Age 3 bars < min_bars_alive 5 ... Skipping" logs appear
✓ Only positions with Age >= 5 bars see penalties applied
```

### Fix #4 Success Indicators:
```
✓ "[POSITION_SIZER_STEP_1]" through "[POSITION_SIZER_STEP_7]" logs show clear progression
✓ Final lot size matches equation: Base = Risk/Stop; then × Confidence × Volatility
✓ NO "[LOT_FLOOR_ENFORCED]" logs with intermediate hedging/conflicts
```

### Fix #5 Success Indicators:
```
✓ For low-accuracy symbols: "[ML_ONLY_FALLBACK_REJECTED] ... Model accuracy 37.27% < 50.00%"
✓ For high-accuracy symbols: "[ML_ONLY_FALLBACK_APPROVED] ... Model accuracy 65.00% >= 50.00%"
✓ Positions don't execute when MTF rejects AND model accuracy < 50%
```

---

**End of Quick Reference**
