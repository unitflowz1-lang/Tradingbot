"""
Shared cooldown state for temporarily forcing local-LLM consumers into
technical-only / reduced-load behavior after repeated fail-open events.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

_state_lock = threading.Lock()
_forced_until: Optional[datetime] = None
_reason: str = ""
_source: str = ""


def activate_local_llm_fast_path(
    *,
    duration_minutes: float = 30.0,
    reason: str = "",
    source: str = "unknown",
) -> datetime:
    until = datetime.now(timezone.utc) + timedelta(minutes=max(0.0, float(duration_minutes)))
    with _state_lock:
        global _forced_until, _reason, _source  # noqa: PLW0603
        _forced_until = until
        _reason = str(reason or "")
        _source = str(source or "unknown")
    return until


def clear_local_llm_fast_path() -> None:
    with _state_lock:
        global _forced_until, _reason, _source  # noqa: PLW0603
        _forced_until = None
        _reason = ""
        _source = ""


def get_local_llm_fast_path_state(now: Optional[datetime] = None) -> Dict[str, Any]:
    now_utc = now or datetime.now(timezone.utc)
    with _state_lock:
        active = bool(_forced_until is not None and now_utc < _forced_until)
        return {
            "active": active,
            "until": _forced_until,
            "reason": _reason,
            "source": _source,
            "remaining_seconds": max(0.0, (_forced_until - now_utc).total_seconds()) if _forced_until else 0.0,
        }
