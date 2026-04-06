# MOMENTUM SYSTEM - COPY-PASTE CODE SNIPPETS FOR MAIN.PY

This file contains exact code snippets you can copy directly into main.py with minimal changes.

## SNIPPET 1: Imports (at top of main.py)

```python
# Add these imports to your existing imports section
from src.trading.momentum_exit_manager import MomentumExitManager, MomentumExitSignal
from src.models import Direction, Position
from datetime import datetime, timezone
```

---

## SNIPPET 2: Initialization (in startup section)

```python
# Add this in your startup/initialization code (after logger setup)

# ===== INITIALIZE MOMENTUM PROFIT SYSTEM =====
momentum_manager = MomentumExitManager(
    logger=logger,
    broker=mt5
)
logger.info(
    "[STARTUP_MOMENTUM] Initialized with breakeven=%.1fR, trail=%.1fR, scale_out=%.1fR",
    momentum_manager.breakeven_trigger_r,
    momentum_manager.trail_activation_r,
    momentum_manager.scale_out_trigger_r,
)
```

---

## SNIPPET 3: Register Position on Entry

```python
# Add this AFTER you successfully open a position

# Register with momentum manager
try:
    position_obj = Position(
        position_id=position_ticket,
        symbol=symbol,
        direction=direction,  # Direction.LONG or Direction.SHORT
        entry_price=entry_price,
        size=size,
        stop_loss=stop_loss,
        opened_at=datetime.now(timezone.utc),
        current_price=entry_price,
    )
    momentum_manager.register_position(position_obj)
    logger.info("[MOMENTUM_REGISTER] %s #%s entry=%.5f", symbol, position_ticket, entry_price)
except Exception as e:
    logger.error("[MOMENTUM_REGISTER_ERROR] %s", e)
```

---

## SNIPPET 4: Process All Active Positions (in main loop)

```python
# Add this in your main loop where you process active positions

# ===== MOMENTUM POSITION MANAGEMENT =====
for position in active_positions:
    try:
        symbol = position.symbol
        ticket = position.position_id
        
        # Get current market data
        tick = mt5.symbol_info_tick(symbol)
        current_price = tick.ask if position.direction == Direction.LONG else tick.bid
        
        # Calculate R-multiple
        pip_value = 0.01 if 'JPY' in symbol else 0.0001
        risk_pips = abs(position.entry_price - position.stop_loss) / pip_value
        if position.direction == Direction.LONG:
            profit_pips = (current_price - position.entry_price) / pip_value
        else:
            profit_pips = (position.entry_price - current_price) / pip_value
        current_r = profit_pips / risk_pips if risk_pips > 0 else 0.0
        
        # Prepare market data for momentum manager
        momentum_data = {
            'price_history': get_symbol_price_history(symbol, last_n=20),  # Get last 20 bars
            'current_price': current_price,
            'current_r': current_r,
            'momentum': calculate_momentum(symbol),  # Your momentum calculation
            'rsi': calculate_rsi(symbol),  # Your RSI calculation
            'volume_decay': calculate_volume_decay(symbol),  # Your volume decay calc
            'adx': calculate_adx(symbol),  # Your ADX calculation
            'unrealized_pnl': position.profit,  # From MT5
            'ml_confidence': get_ml_confidence(symbol),  # Your ML score
            'stop_loss': position.stop_loss,
        }
        
        # Process through momentum manager
        result = momentum_manager.process_position(position, momentum_data)
        
        # Handle result based on action type
        if result['action'] == 'update_sl':
            new_sl = result['new_sl']
            reason = result['reason']
            logger.info(
                "[MOMENTUM_SL] %s #%s | %.5f → %.5f | R: %.2fR",
                symbol, ticket, position.stop_loss, new_sl, current_r
            )
            
            # Update broker
            request = {
                "action": mt5.TRADE_ACTION_MODIFY,
                "order": ticket,
                "sl": new_sl,
                "type_time": mt5.ORDER_TIME_GTC,
            }
            response = mt5.order_send(request)
            if response and response.retcode == mt5.TRADE_RETCODE_DONE:
                position.stop_loss = new_sl
            else:
                logger.warning("[MOMENTUM_SL_FAILED] %s | %s", symbol, 
                             response.comment if response else "No response")
        
        elif result['action'] == 'scale_out':
            close_pct = result['close_percent']
            new_sl = result.get('new_sl_for_remainder')
            volume_to_close = position.size * (close_pct / 100)
            
            logger.critical(
                "[MOMENTUM_SCALEOUT] %s #%s | Close %.0f%% (%.2f) | New SL: %.5f | R: %.2fR",
                symbol, ticket, close_pct, volume_to_close, new_sl, current_r
            )
            
            # Close partial
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume_to_close,
                "type": mt5.ORDER_TYPE_BUY if position.type == 1 else mt5.ORDER_TYPE_SELL,
                "position": ticket,
                "type_time": mt5.ORDER_TIME_RETURN,
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }
            response = mt5.order_send(request)
            if response and response.retcode == mt5.TRADE_RETCODE_DONE:
                # Update SL for remaining
                request2 = {
                    "action": mt5.TRADE_ACTION_MODIFY,
                    "order": ticket,
                    "sl": new_sl,
                    "type_time": mt5.ORDER_TIME_GTC,
                }
                response2 = mt5.order_send(request2)
                if response2 and response2.retcode == mt5.TRADE_RETCODE_DONE:
                    position.stop_loss = new_sl
                    position.size -= volume_to_close
        
        elif result['action'] == 'force_close':
            reason = result['reason']
            signal = result['signal_type'].value
            
            logger.critical(
                "[MOMENTUM_FORCE_CLOSE] %s #%s | Reason: %s | R: %.2fR",
                symbol, ticket, reason, current_r
            )
            
            # Close entire position
            tick = mt5.symbol_info_tick(symbol)
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": position.size,
                "type": mt5.ORDER_TYPE_BUY if position.type == 1 else mt5.ORDER_TYPE_SELL,
                "position": ticket,
                "price": tick.ask if position.type == 0 else tick.bid,
                "type_time": mt5.ORDER_TIME_RETURN,
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }
            response = mt5.order_send(request)
            if response and response.retcode == mt5.TRADE_RETCODE_DONE:
                logger.critical(
                    "[MOMENTUM_CLOSED] %s #%s | Final R: %.2fR | PnL: $%.2f",
                    symbol, ticket, current_r, position.profit
                )
                active_positions.remove(position)  # Remove from tracking
            else:
                logger.warning("[MOMENTUM_CLOSE_FAILED] %s", response.comment if response else "No response")
    
    except Exception as e:
        logger.error("[MOMENTUM_LOOP_ERROR] %s #%s | %s", position.symbol, position.position_id, e)
        continue
```

---

## SNIPPET 5: Cleanup on Position Close

```python
# Add this function to your position cleanup code

def cleanup_closed_position(ticket):
    """Remove momentum state when position closes"""
    try:
        if str(ticket) in momentum_manager.momentum_states:
            del momentum_manager.momentum_states[str(ticket)]
            logger.debug("[MOMENTUM_CLEANUP] Cleared state for ticket %d", ticket)
    except Exception as e:
        logger.error("[MOMENTUM_CLEANUP_ERROR] %s", e)
```

---

## SNIPPET 6: Key Functions You Need

These are helper functions you might not have - add them:

```python
def get_symbol_price_history(symbol, last_n=20):
    """Get OHLC price history for a symbol"""
    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, last_n)
        if rates is None:
            return []
        
        price_history = []
        for rate in rates:
            price_history.append({
                'open': rate['open'],
                'high': rate['high'],
                'low': rate['low'],
                'close': rate['close'],
                'volume': rate['tick_volume'],
                'time': datetime.fromtimestamp(rate['time']),
            })
        return price_history
    except Exception as e:
        logger.error("[PRICE_HISTORY_ERROR] %s | %s", symbol, e)
        return []


def calculate_momentum(symbol):
    """Calculate momentum indicator (ROC, MACD, or your custom)"""
    # This is a placeholder - implement your own momentum calculation
    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 14)
        if len(rates) < 2:
            return 0.0
        
        # Simple momentum: (close[0] - close[13]) / close[13]
        momentum = (rates[0]['close'] - rates[-1]['close']) / rates[-1]['close']
        return momentum
    except:
        return 0.0


def calculate_rsi(symbol, period=14):
    """Calculate RSI indicator"""
    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, period + 10)
        if len(rates) < period:
            return 50.0
        
        # Your RSI calculation here - this is placeholder
        # Real implementation needed
        closes = [r['close'] for r in rates]
        
        gains = []
        losses = []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    except:
        return 50.0


def calculate_volume_decay(symbol):
    """Calculate volume decay (0-1, where 1 = complete decay)"""
    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 5)
        if len(rates) < 2:
            return 0.0
        
        volumes = [r['tick_volume'] for r in rates]
        if max(volumes) == 0:
            return 0.0
        
        decay = (volumes[0] - volumes[-1]) / max(volumes)
        return max(0, min(1, decay))
    except:
        return 0.0


def calculate_adx(symbol, period=14):
    """Calculate ADX indicator"""
    # This is complex - use a TA library or pre-calculated values
    # Placeholder returning default
    try:
        # If you have TA-Lib or similar: return proper ADX
        # For now: placeholder
        return 20.0
    except:
        return 20.0


def get_ml_confidence(symbol):
    """Get ML model confidence for this symbol"""
    # This should return your ML model's confidence (0.0 to 1.0)
    # Placeholder implementation
    try:
        # Your ML model prediction here
        confidence = 0.6  # Placeholder
        return confidence
    except:
        return 0.5
```

---

## SNIPPET 7: Integration Test (Quick Sanity Check)

```python
# Run this after integration to verify everything connects

async def test_momentum_integration():
    """Quick integration test"""
    
    logger.info("[TEST] Starting momentum integration test...")
    
    # 1. Check manager initialized
    assert momentum_manager is not None
    logger.info("[TEST] ✓ Manager initialized")
    
    # 2. Create test position
    test_pos = Position(
        position_id=12345,
        symbol="EUR/USD",
        direction=Direction.LONG,
        entry_price=1.0900,
        size=1.0,
        stop_loss=1.0850,
        opened_at=datetime.now(timezone.utc),
        current_price=1.0950,
    )
    
    # 3. Register it
    momentum_manager.register_position(test_pos)
    assert str(12345) in momentum_manager.momentum_states
    logger.info("[TEST] ✓ Position registered")
    
    # 4. Process it
    test_data = {
        'price_history': [],
        'current_price': 1.0950,
        'current_r': 2.0,
        'momentum': 0.05,
        'rsi': 55.0,
        'volume_decay': 0.1,
        'adx': 25.0,
        'unrealized_pnl': 50.0,
        'ml_confidence': 0.75,
        'stop_loss': 1.0850,
    }
    
    result = momentum_manager.process_position(test_pos, test_data)
    assert result is not None
    assert 'action' in result
    logger.info("[TEST] ✓ Position processed | Action: %s", result['action'])
    
    logger.info("[TEST] ✅ All integration tests passed!")

# Run the test
# await test_momentum_integration()
```

---

## Quick Checklist

Copy this into your main.py TODO list:

```python
# ===== MOMENTUM INTEGRATION CHECKLIST =====
# [ ] Add imports (SNIPPET 1)
# [ ] Add initialization (SNIPPET 2)
# [ ] Call register on entry (SNIPPET 3)
# [ ] Add main loop processing (SNIPPET 4)
# [ ] Add cleanup function (SNIPPET 5)
# [ ] Add helper functions if needed (SNIPPET 6)
# [ ] Run integration test (SNIPPET 7)
# [ ] Backtest with momentum enabled
# [ ] Monitor logs for first 24 hours live
# ===== END CHECKLIST =====
```

---

## That's It!

You now have all the code snippets to integrate the Momentum System. Just:

1. Copy each snippet into appropriate location in main.py
2. Fill in your custom calculations (momentum, RSI, ADX, ML confidence)
3. Test with backtesting first
4. Deploy to live trading with logging

The system will automatically handle:
- ✅ Breakeven locking at 0.3R
- ✅ Chandelier trailing at 0.8R+
- ✅ Scale-outs at 1.2R
- ✅ Reversal defense
- ✅ Tokyo session adaptation
- ✅ ML confidence exits

All you need to do is provide market data and execute the returned actions!

---

**Questions?** See:
- MOMENTUM_PROFIT_SYSTEM_GUIDE.md (complete reference)
- MOMENTUM_INTEGRATION_MAIN_PY.md (detailed integration guide)
- momentum_exit_manager.py (source code with docstrings)
