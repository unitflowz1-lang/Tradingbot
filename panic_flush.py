"""One-shot panic flush trigger for stagnant live positions."""

import json
import os
import sys
from datetime import datetime, timezone


def main() -> int:
    min_bars_open = 40
    if len(sys.argv) > 1:
        try:
            min_bars_open = max(1, int(sys.argv[1]))
        except ValueError:
            print("Usage: python panic_flush.py [min_bars_open]")
            return 1

    payload = {
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "min_bars_open": min_bars_open,
    }
    trigger_path = os.path.join(os.getcwd(), "panic_flush_command.json")
    with open(trigger_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    print(f"Panic flush armed in {trigger_path} for positions older than {min_bars_open} bars.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
