"""
Shared emergency-stop state for runtime trading safety circuit breakers.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

_lock = threading.Lock()
_trading_enabled: bool = True
_active_reason: str = ""
_triggered_at: Optional[datetime] = None
_callbacks: Dict[str, Callable[[str], Any]] = {}


def trading_enabled() -> bool:
    with _lock:
        return bool(_trading_enabled)


def emergency_stop_active() -> bool:
    return not trading_enabled()


def get_emergency_stop_state() -> Dict[str, Any]:
    with _lock:
        return {
            "trading_enabled": bool(_trading_enabled),
            "active": not bool(_trading_enabled),
            "reason": _active_reason,
            "triggered_at": _triggered_at,
        }


def register_emergency_stop_callback(name: str, callback: Callable[[str], Any]) -> None:
    with _lock:
        _callbacks[str(name)] = callback


def clear_emergency_stop_for_tests() -> None:
    with _lock:
        global _trading_enabled, _active_reason, _triggered_at  # noqa: PLW0603
        _trading_enabled = True
        _active_reason = ""
        _triggered_at = None


def trigger_emergency_stop(reason: str) -> bool:
    with _lock:
        global _trading_enabled, _active_reason, _triggered_at  # noqa: PLW0603
        if not _trading_enabled:
            return False
        _trading_enabled = False
        _active_reason = str(reason or "EMERGENCY_STOP")
        _triggered_at = datetime.now(timezone.utc)
        callbacks = list(_callbacks.values())

    for callback in callbacks:
        try:
            result = callback(_active_reason)
            if inspect.isawaitable(result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    continue
                loop.create_task(result)
        except Exception:
            continue
    return True
