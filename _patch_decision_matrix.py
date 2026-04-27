"""
One-shot patch: restores the broken spread-aware sizing + vol-multiplier block
in main.py and adds the forced_execution bypass to the Decision Matrix cutoff.
Run once then delete.
"""
import sys

TARGET = "main.py"

# Use \n only — the file uses LF line endings (confirmed via debug output)
OLD_BLOCK = (
    "                            if current_spread_pips > 2.0:\n"
    "                            )\n"
    "                            \n"
    "                            # If trading is cutoff, skip new positions\n"
    "                            if not decision_matrix.should_trade(latest_decision):\n"
    "                                logger.critical(\n"
    "                                    \"[DECISION_MATRIX] Trading cutoff active - New positions blocked. \"\n"
    "                                    \"Emergency conditions detected.\"\n"
    "                                )\n"
    "                                return\n"
    "                            \n"
    "                            final_lots = final_lots * final_vol_multiplier"
)

NEW_BLOCK = (
    "                            if current_spread_pips > 2.0:\n"
    "                                logger.info(f\"[SPREAD_AWARE_SIZING] Spread {format_float(current_spread_pips, '.1f')} > 2.0. Reducing final lots by 10%.\")\n"
    "                                final_lots *= 0.90\n"
    "                                final_lots = max(0.01, round(final_lots, 2))\n"
    "\n"
    "                            # Cap at 0.1 lots per trade\n"
    "                            final_lots = min(final_lots, 0.1)\n"
    "\n"
    "                            # **IMPROVED:** Apply volatility-adjusted position sizing\n"
    "                            # In high volatility, reduce position size to control risk\n"
    "                            vol_multiplier = 1.0  # Default (1% normal volatility)\n"
    "                            if current_volatility > 0:\n"
    "                                vol_ratio = current_volatility / 1.0  # Normalize to 1% normal\n"
    "                                if vol_ratio > 2.0:  # Extreme volatility (>2%)\n"
    "                                    vol_multiplier = 0.5  # 50% of base size\n"
    "                                elif vol_ratio > 1.5:  # High volatility (1.5%-2%)\n"
    "                                    vol_multiplier = 0.667  # 66.7% of base size\n"
    "                                elif vol_ratio > 1.0:  # Elevated volatility (1%-1.5%)\n"
    "                                    vol_multiplier = 0.85  # 85% of base size\n"
    "\n"
    "                            # **NEW:** Apply decision matrix governance to position sizing\n"
    "                            final_vol_multiplier = decision_matrix.get_position_multiplier(\n"
    "                                vol_multiplier, latest_decision\n"
    "                            )\n"
    "\n"
    "                            # [PATCH] Decision Matrix cutoff: forced_execution signals bypass\n"
    "                            # the emergency cutoff so high-conviction trades are never deadlocked.\n"
    "                            # EMERGENCY_CUTOFF still blocks all standard (non-forced) signals.\n"
    "                            _signal_is_forced = getattr(signal, 'forced_execution', False)\n"
    "                            if not decision_matrix.should_trade(latest_decision) and not _signal_is_forced:\n"
    "                                logger.critical(\n"
    "                                    \"[DECISION_MATRIX] Trading cutoff active - New positions blocked. \"\n"
    "                                    \"Emergency conditions detected. (forced_execution signals still admitted)\"\n"
    "                                )\n"
    "                                return\n"
    "                            elif not decision_matrix.should_trade(latest_decision) and _signal_is_forced:\n"
    "                                logger.warning(\n"
    "                                    \"[DECISION_MATRIX] Trading cutoff BYPASSED for forced_execution signal: %s\",\n"
    "                                    symbol,\n"
    "                                )\n"
    "\n"
    "                            final_lots = final_lots * final_vol_multiplier"
)

with open(TARGET, "r", encoding="utf-8") as f:
    content = f.read()

if OLD_BLOCK not in content:
    print("ERROR: Target block not found.")
    idx = content.find("if current_spread_pips > 2.0:")
    print(f"Anchor offset: {idx}")
    if idx != -1:
        print(repr(content[idx : idx + 500]))
    sys.exit(1)

patched = content.replace(OLD_BLOCK, NEW_BLOCK, 1)

with open(TARGET, "w", encoding="utf-8") as f:
    f.write(patched)

print("SUCCESS: Decision matrix / spread-aware sizing block patched correctly.")
