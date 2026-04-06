import json
import os
from datetime import datetime


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHADOW_FILE = os.path.join(ROOT_DIR, "shadow_state.json")
LOG_FILE = os.path.join(ROOT_DIR, "logs", "forex_bot.log")


def check_bot_health() -> None:
    print(f"--- Bot Health Report ({datetime.now().strftime('%H:%M:%S')}) ---")

    # 1. Check freeze-zone deferrals from shadow state
    if os.path.exists(SHADOW_FILE):
        try:
            with open(SHADOW_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)

            shadow_positions = payload.get("shadow_positions", {}) if isinstance(payload, dict) else {}

            for tid, data in shadow_positions.items():
                if not isinstance(data, dict):
                    continue
                meta = data.get("strategy_meta", {}) or {}
                if "freeze_retry_bar_time" in meta:
                    print(f"[!] ALERT: Ticket {tid} ({data.get('symbol', 'UNKNOWN')}) is in FREEZE RETRY mode.")
                    print(f"    Pending until after: {meta['freeze_retry_bar_time']}")
        except Exception as exc:
            print(f"[!] Failed reading shadow state: {exc}")
    else:
        print("[i] No shadow_state.json found.")

    # 2. Check recent ML retrain triggers from logs
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-500:]

            triggers = [line.strip() for line in lines if "[ML_RETRAIN_TRIGGER]" in line]
            if triggers:
                print("[!] Recent ML retrain triggers detected:")
                for line in triggers[-5:]:
                    print(f"    {line}")
        except Exception as exc:
            print(f"[!] Failed reading log file: {exc}")
    else:
        print("[i] No forex_bot.log found.")

    print("--- End of Report ---")


if __name__ == "__main__":
    check_bot_health()
