import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))


def verify_protection_settings():
    print("--- [PROFIT PROTECTION VERIFICATION] ---")

    env_vars = {
        "BREAKEVEN_TRIGGER_R": os.getenv("BREAKEVEN_TRIGGER_R"),
        "TRAILING_ACTIVATION_R": os.getenv("TRAILING_ACTIVATION_R"),
    }

    for var, value in env_vars.items():
        if value is not None:
            print(
                f"CRITICAL: Environment variable '{var}' is set to {value} "
                "(OVERRIDING DEFAULTS)"
            )
        else:
            print(f"INFO: No environment override for {var}")

    try:
        from src.trading.profit_protection_module import TradeManagementSettings

        settings = TradeManagementSettings()

        print("\n--- [MODULE CONFIG AUDIT] ---")
        print(f"Target Trail Activation: {settings.trailing_stop_activation_r:.2f}")
        print(f"Target Break-Even Trigger: {settings.breakeven_trigger_r:.2f}")
        print(f"Dynamic Profit Locking Enabled: {settings.use_dynamic_profit_locking}")
        print(
            "Dynamic Profit Lock Levels: "
            + ", ".join(
                f"{level['trigger_profit_pct']:.1f}%->{level['lock_profit_pct']:.1f}%"
                if not bool(float(level.get("use_entry_plus_spread", 0.0) or 0.0))
                else f"{level['trigger_profit_pct']:.1f}%->Entry+Spread"
                for level in settings.dynamic_profit_lock_levels
            )
        )
    except Exception as exc:
        print(f"\nERROR: Could not import or read TradeManagementSettings: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(verify_protection_settings())
