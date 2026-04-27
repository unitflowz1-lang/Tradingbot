# User Trade Learner Integration Guide

## Overview

The enhanced UserTradeLearner (v2.0) automatically learns from manual trader decisions across 4 pathways:

1. **Conviction Mapping** - Tracks bot rejections and compares to manual entry success
2. **Exit Analysis** - Classifies exits to understand risk perception (momentum vs news)
3. **Directional Bias** - Boosts signals matching user's proven edge
4. **Quality Floor** - Recommends adaptive thresholds based on striking frequency

---

## Integration Points

### 1. In Signal Validation (Enhanced Signal Validator)

**Where:** `src/analysis/enhanced_signal_validator.py`

```python
from src.analysis.user_trade_learner import UserTradeLearner

class EnhancedSignalValidator:
    def __init__(self, config=None, user_learner=None):
        self.config = config or EnhancedSignalConfig()
        self.user_learner = user_learner or UserTradeLearner()
        # ... rest of init
    
    def validate_signal(self, signal, historical_data, higher_tf_data=None, 
                       current_positions=None, conviction_data=None):
        """
        Apply learned weights and conviction boosts
        """
        # ... existing validation logic ...
        
        # NEW: Apply conviction boost from rejection memory
        if conviction_data and conviction_data.get('conviction_delta', 0) > 0:
            conviction_boost = min(15.0, conviction_data['conviction_delta'] * 0.5)
            total_score += conviction_boost
            
            self.logger.info(
                f"[CONVICTION_BOOST] {signal.symbol} +{conviction_boost:.1f} pts "
                f"(User delta: {conviction_data['conviction_delta']:.1f})"
            )
        
        # NEW: Use learned weights instead of hardcoded
        learned_weights = self.user_learner.get_weights()
        self.config.weights.update(learned_weights)
        
        return confluence_score
```

### 2. When Bot Rejects a Signal

**Where:** Core trading engine or signal generation

```python
from src.analysis.user_trade_learner import UserTradeLearner

user_learner = UserTradeLearner()

def handle_rejected_signal(signal, reason, confluence_score, market_context):
    """
    Record rejections so we can spot conviction deltas when user enters
    """
    user_learner.record_bot_rejection(
        symbol=signal.symbol,
        reason=reason,
        required_score=confluence_score.total_score,
        market_context=market_context
    )
    
    logger.info(f"[REJECTION_RECORDED] {signal.symbol} | Reason: {reason}")
```

### 3. When User Enters Manually

**Where:** Position manager / trade admission

```python
def on_manual_entry(position, market_context, source='manual'):
    """
    Capture manual entry and check conviction vs bot
    """
    # Record the entry
    user_learner.capture_trade_entry(position, market_context, source=source)
    
    # Analyze conviction delta
    conviction_analysis = user_learner.analyze_manual_entry_conviction(
        position, market_context
    )
    
    if conviction_analysis['bot_rejected_recently']:
        logger.critical(
            f"[CONVICTION_SIGNAL] {position.symbol} | "
            f"User entering after bot rejection | "
            f"Conviction delta: +{conviction_analysis['conviction_delta']:.1f} pts"
        )
```

### 4. When Position Exits

**Where:** Exit handler

```python
def on_trade_exit(position_id, exit_price, profit, market_context_at_exit):
    """
    Record exit and classify type (momentum, news, or profit-taking)
    """
    # Get entry context
    trade = user_learner.trades.get(position_id)
    if not trade:
        return
    
    # Analyze the exit
    exit_analysis = user_learner.analyze_manual_exit(
        position_id=position_id,
        exit_price=exit_price,
        market_context_at_entry=trade.market_context,
        market_context_at_exit=market_context_at_exit
    )
    
    # Record outcome with classification
    user_learner.capture_trade_exit(
        position_id=position_id,
        profit=profit,
        exit_time=datetime.now(timezone.utc),
        market_context_at_exit=market_context_at_exit
    )
    
    if exit_analysis['sensitivity_adjustment']:
        logger.warning(
            f"[EXIT_LEARNING] {trade.symbol} | "
            f"Type: {exit_analysis['exit_type']} | "
            f"Boost {exit_analysis['sensitivity_adjustment']['indicator']} "
            f"+{exit_analysis['sensitivity_adjustment']['boost']*100:.0f}%"
        )
```

### 5. Apply Learned Weights

**Where:** Signal scoring / Monte Carlo simulation

```python
def score_signal_with_learning(signal_inputs):
    """
    Use learner's optimized weights for scoring
    """
    learned_weights = user_learner.get_weights()
    
    # Use instead of hardcoded weights
    mtf_component_score = signal_inputs['mtf'] * learned_weights.get('mtf', 0.25)
    vol_component_score = signal_inputs['volatility'] * learned_weights.get('volatility', 0.15)
    momentum_score = signal_inputs['momentum'] * learned_weights.get('momentum', 0.20)
    # ... etc
    
    total = mtf_component_score + vol_component_score + momentum_score + ...
    
    return total
```

### 6. Directional Bias Application

**Where:** Position sizing / trade approval

```python
def apply_directional_bias_boost(signal):
    """
    Boost signals matching user's proven edge
    """
    perf = user_learner.calculate_performance_metrics(signal.symbol)
    
    if perf['directional_bias'] == 'LONG_BIAS':
        if signal.direction == Direction.LONG:
            # User proven better at LONGs
            signal.confidence *= 1.15  # +15% boost
            logger.info(
                f"[BIAS_BOOST] {signal.symbol} LONG | "
                f"User {perf['long_wr']:.1%} vs Short {perf['short_wr']:.1%}"
            )
    
    elif perf['directional_bias'] == 'SHORT_BIAS':
        if signal.direction == Direction.SHORT:
            signal.confidence *= 1.15  # +15% boost
            logger.info(
                f"[BIAS_BOOST] {signal.symbol} SHORT | "
                f"User {perf['short_wr']:.1%} vs Long {perf['long_wr']:.1%}"
            )
```

### 7. Quality Floor Recommendations

**Where:** Signal validation / admission controller

```python
def check_quality_floor_recommendation(bot_trades, current_floor=65.0):
    """
    Analyze if we should temporarily lower quality floor
    to match user's striking frequency
    """
    freq_analysis = user_learner.analyze_striking_frequency(bot_trades)
    
    if freq_analysis['recommendation'] == 'LOWER_FLOOR':
        suggested = freq_analysis['suggest_floor']
        duration = freq_analysis['suggest_duration_hours']
        
        logger.critical(
            f"[QUALITY_FLOOR_RECOMMENDATION] "
            f"{current_floor} → {suggested:.1f} for {duration}h | "
            f"{freq_analysis['reason']}"
        )
        
        # Could auto-apply with timer, or require manual approval
        return {
            'suggested_floor': suggested,
            'duration_hours': duration,
            'auto_revert': True
        }
    
    return None
```

---

## Data Flow Diagram

```
MANUAL ENTRY
    │
    ├─→ capture_trade_entry()
    │       ├─→ analyze_manual_entry_conviction()
    │       │   └─→ query_rejection_history() [60-min window]
    │       │       └─→ conviction_delta calculated
    │       └─→ trades.json + verdict logged
    │
    └─→ [TRADING PROCEEDS]
            │
            ├─→ Price moves
            │
    MANUAL EXIT
            │
            ├─→ capture_trade_exit()
            │   ├─→ analyze_manual_exit()
            │   │   ├─→ _detect_momentum_reversal()
            │   │   └─→ _detect_price_spike()
            │   └─→ exit_type classified
            │
            └─→ optimize_weights()
                ├─→ Boost momentum if momentum_shifts >= 3
                ├─→ Boost liquidity if news_spikes >= 2
                ├─→ Apply directional bias
                └─→ learned_weights.json saved
                    │
                    └─→ Next signal uses boosted weights
```

---

## Sample Usage in Main Trading Loop

```python
from src.analysis.user_trade_learner import UserTradeLearner
from src.analysis.enhanced_signal_validator import EnhancedSignalValidator

# Initialize learner
user_learner = UserTradeLearner()

# Initialize validator with learner
validator = EnhancedSignalValidator(user_learner=user_learner)

# Main loop
while trading_active:
    
    # 1. Generate signal
    signal = generate_trading_signal(market_data)
    
    # 2. Validate signal
    if is_manual_entry(signal):
        # User entering: check conviction
        conviction_data = user_learner.analyze_manual_entry_conviction(
            position=signal_position,
            market_context=market_context
        )
    else:
        conviction_data = None
    
    confluence = validator.validate_signal(
        signal, 
        historical_data,
        higher_tf_data=higher_tfs,
        conviction_data=conviction_data
    )
    
    # 3. Handle rejection
    if not confluence.signal_approved:
        handle_rejected_signal(signal, confluence.rejection_reasons, 
                              confluence.total_score, market_context)
        continue
    
    # 4. Execute trade
    position = execute_trade(signal, confluence)
    user_learner.capture_trade_entry(position, market_context)
    
    # 5. Monitor position
    while position_open:
        # ... manage position ...
        
        if manual_exit_triggered:
            exit_analysis = user_learner.analyze_manual_exit(
                position.position_id,
                current_price,
                trade.market_context,
                current_market_context
            )
            close_position(position)
            user_learner.capture_trade_exit(
                position.position_id,
                profit,
                datetime.now(),
                current_market_context
            )
    
    # 6. Every 3 trades, re-optimize
    completed = sum(1 for t in user_learner.trades.values() if t.outcome)
    if completed % 3 == 0:
        user_learner.optimize_weights()
        
        # Check quality floor recommendation
        floor_rec = check_quality_floor_recommendation(bot_trades)
        if floor_rec:
            logger.critical(f"Quality floor adjustment suggested: {floor_rec}")
```

---

## Key Methods Reference

### Pathway 1: Conviction Mapping
```python
user_learner.record_bot_rejection(symbol, reason, required_score, market_context)
conviction = user_learner.analyze_manual_entry_conviction(position, market_context)
# Returns: {conviction_delta, bot_rejected_recently, striking_zone_params, recommendation}
```

### Pathway 2: Exit Analysis
```python
exit_analysis = user_learner.analyze_manual_exit(
    position_id, exit_price, entry_context, exit_context
)
# Returns: {exit_type, sensitivity_adjustment, symbol, profit}
# exit_type: MOMENTUM_SHIFT | NEWS_SPIKE | PROFIT_TAKING
```

### Pathway 3: Directional Bias
```python
perf = user_learner.calculate_performance_metrics(symbol)
# Returns: {win_rate, profit_factor, long_wr, short_wr, directional_bias}
```

### Pathway 4: Quality Floor
```python
freq = user_learner.analyze_striking_frequency(bot_trades)
# Returns: {recommendation, suggest_floor, suggest_duration_hours, reason}
```

### Monitoring
```python
summary = user_learner.get_learning_summary()
# Returns: {total_trades, win_rate, exit_patterns, learned_weights, rejection_history_depth}

weights = user_learner.get_weights()
# Returns current optimized weights
```

---

## Testing Checklist

- [ ] Bot rejection recorded when signal rejected
- [ ] Manual entry detected, conviction_delta calculated
- [ ] Exit classified as MOMENTUM_SHIFT / NEWS_SPIKE / PROFIT_TAKING
- [ ] Momentum weight boosted after 3+ momentum exits
- [ ] Liquidity weight boosted after 2+ news spike exits
- [ ] Directional bias applied (+15%) when user has 15%+ better WR
- [ ] Quality floor recommendation triggered when frequency_ratio >= 2.5x
- [ ] Rejection history auto-limited to 100 entries per symbol
- [ ] Weights saved to disk and loaded on startup
- [ ] Learning summary shows all four pathways active

---

## Safety Constraints Maintained

✓ Hard Spread Limit (3.0 pips) - Cannot override  
✓ 0.25% risk model - Learning doesn't affect sizing  
✓ Meta-Gate safety floors - Always enforced  
✓ Macro Shield operational - Always monitoring  
✓ Weight normalization - Sums to 1.0 always  

---

## Monitoring Output

Watch for these log entries to confirm learning is active:

```
[CONVICTION_DELTA] EURUSD | User conviction +8.5 pts over bot rejection
[EXIT_MOMENTUM] GBPUSD | User exited on RSI reversal | BOOST momentum +10%
[EXIT_NEWS] AUDUSD | Spike detected | BOOST liquidity gate +8%
[BIAS_BOOST] EURUSD SHORT | User 72% vs Bot 55%
[QUALITY_FLOOR_ALERT] User striking 3.2x more often. Suggest temp floor 58 for 4h
[LEARNER] Applied new weights: {'mtf': 0.25, 'momentum': 0.30, 'liquidity': 0.17, ...}
```

---

## Next Steps

1. Import UserTradeLearner in main.py
2. Hook rejection recording into signal validation
3. Hook manual entry capture into position manager
4. Hook manual exit analysis into close positions handler
5. Apply learned weights in signal scoring
6. Monitor summary dashboard for learning progress
