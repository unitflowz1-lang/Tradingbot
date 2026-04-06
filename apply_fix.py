#!/usr/bin/env python3
"""Apply fix to main.py - remove redundant position sizer overrides"""

import re

# The replacement text (clean, without unicode issues)
new_code = '''                            logger.debug(f"[FINAL_SIZE] {symbol} | PositionSizer output: {format_float(final_lots, '.4f')} lots (all multipliers applied internally)")
                            
                            # ===== FIX #2: REMOVE REDUNDANT POSITION SIZER OVERRIDES =====
                            # The PositionSizer already applies all multipliers internally:
                            # 1. Confidence multiplier | 2. Tier multiplier (0.75/0.60x) | 
                            # 3. Volatility multiplier | 4. ML Accuracy Risk multiplier
                            # Taking the LOWEST to prevent cascade decay
                            #
                            # DO NOT apply additional multipliers. Trust the PositionSizer output.
                            # Previous code destroying position sizing accuracy by applying:
                            #   - confluence_score multiplier (redundant)
                            #   - MACRO_SHIELD 0.5x override (hardcoded)
                            #   - ConfMult gate forcing 0.5x if confidence < 0.70 (duplicate)
                            # Result: 0.21 lots became 0.03 lots
                            
                            # Only check: (1) Symbol-level exposure cap (2) Broker minimum floor
                            symbol_exposure_lots = sum(
                                float(getattr(p, "volume", getattr(p, "quantity", 0.0)) or 0.0)
                                for p in same_direction_symbol_positions
                            )
                            max_symbol_lots = max(0.01, equity_based_size * 1.0)
                            remaining_capacity = max(0.0, max_symbol_lots - symbol_exposure_lots)
                            
                            if final_lots > remaining_capacity and remaining_capacity > 0:
                                logger.info("[POSITION_CAP] %s | Capping %.4f to remaining capacity %.4f", symbol, final_lots, remaining_capacity)
                                final_lots = remaining_capacity
                            
                            broker_min = 0.05
                            if final_lots < broker_min and final_lots > 0:
                                logger.info("[POSITION_FLOOR] %s | Flooring %.4f to broker minimum %.4f", symbol, final_lots, broker_min)
                                final_lots = broker_min
                            elif final_lots <= 0:
                                logger.info("[POSITION_REJECTED] %s | PositionSizer output %.4f <= 0. Trade rejected.", symbol, final_lots)
                                final_lots = 0.0
                            
                            logger.info(
                                "[ACTION] Risk OK | Score: %s | TIER: %s | PositionSizer: %.4f | SymbolCap: %.4f | Final: %.4f lots",
                                format_float(assessment.risk_score, '.2f'),
                                getattr(signal, 'trade_tier', 'UNKNOWN'),
                                float(getattr(signal, 'position_size', 0.0) or 0.0),
                                remaining_capacity,
                                format_float(final_lots, '.4f'))'''

# Read the file
with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Pattern to match the entire block we want to replace
# This is more flexible to handle special characters
pattern = r"logger\.debug\(f\"\[FINAL_SIZE\].*?PositionSizer output:.*?lots \(all multipliers applied internally\)\"\)\s*\n\s*# ENHANCED: Apply confluence score position multiplier.*?logger\.info\(\s*\"\[ACTION\] Risk OK \| Score: %s \| TIER: %s \| \"\s*\"RawSize: %s%% \| EquitySize: %s \| ConfMult: %sx \| Final: %s lots\",.*?format_float\(final_lots, '\.2f'\)\)"

matches = list(re.finditer(pattern, content, re.DOTALL))
print(f"Found {len(matches)} matches with flexible pattern")

if matches:
    match = matches[0]
    old_section = content[match.start():match.end()]
    print(f"Match length: {len(old_section)} chars")
    print(f"Replacement length: {len(new_code)} chars")
    
    # Replace
    new_content = content[:match.start()] + new_code + content[match.end():]
    
    # Write back
    with open('main.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print("SUCCESS: File updated")
    print(f"Total file size: {len(new_content)} chars (was {len(content)})")
else:
    print("ERROR: Pattern not found")
    print("\nTrying to find key string...")
    if "# ENHANCED: Apply confluence score position multiplier" in content:
        idx = content.find("# ENHANCED: Apply confluence score position multiplier")
        print(f"Found at char {idx}")
        context = content[max(0, idx-300):min(len(content), idx+500)]
        print("Context:")
        print(context)
