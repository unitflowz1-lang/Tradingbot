"""
Unified execution regime resolver.
"""

from enum import Enum
import os
from typing import Iterable


class ExecutionRegime(str, Enum):
    PROTECT = "PROTECT"
    STRIKE = "STRIKE"


LEGACY_STRIKE_FLAGS: Iterable[str] = (
    "TOTAL_ECLIPSE",
    "FORCE_MAJEURE",
    "ULTIMATE_OVERRIDE",
    "STRIKING_MODE",
    "SYSTEM_UNCAGED",
    "SYSTEM_UNCAGED_V6",
    "WAR_ROOM",
)


def macro_ignore_news_enabled(env: dict | None = None) -> bool:
    """
    Manual override for bypassing the macro news hard stop.
    Set MACRO_IGNORE_NEWS=1/true/yes/on to enable.
    """
    env = env or os.environ
    raw = str(env.get("MACRO_IGNORE_NEWS", "") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def resolve_execution_regime(env: dict | None = None) -> ExecutionRegime:
    """
    Resolve the unified execution regime from env vars.

    Priority:
    1) EXECUTION_REGIME explicitly set
    2) Any legacy strike flag enabled -> STRIKE
    3) Default -> PROTECT
    """
    env = env or os.environ
    raw = str(env.get("EXECUTION_REGIME", "") or "").strip().upper()
    if raw in {"PROTECT", "SAFE", "SAFETY"}:
        return ExecutionRegime.PROTECT
    if raw in {"STRIKE", "AGGRESSIVE", "ATTACK"}:
        return ExecutionRegime.STRIKE

    for key in LEGACY_STRIKE_FLAGS:
        val = str(env.get(key, "") or "").strip().lower()
        if val in {"1", "true", "yes", "on"}:
            return ExecutionRegime.STRIKE

    return ExecutionRegime.PROTECT
