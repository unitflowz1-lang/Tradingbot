"""
Asynchronous LLM Macro Monitor.

Runs in the background and updates a fast local cache with per-symbol
macro risk penalties so trade admission can read instantly without blocking.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional
from src.analysis.ollama_runtime_gate import OLLAMA_REQUEST_LOCK
from src.utils.json_utils import safe_json_load
from src.analysis.local_llm_fast_path import (
    clear_local_llm_fast_path,
    get_local_llm_fast_path_state,
)
import contextlib
try:
    import aiohttp  # type: ignore
except Exception:  # pragma: no cover
    aiohttp = None
from src.data.news_data_collector import NewsDataCollector

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("MACRO_MONITOR_OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
# === FIX: Unified Nemotron-3-Nano model for all macro monitoring tasks ===
DEFAULT_MODEL = os.environ.get("MACRO_MONITOR_PRIMARY_MODEL", "qwen3.5:0.8b")
PRIMARY_MODEL = os.environ.get("MACRO_MONITOR_PRIMARY_MODEL", "qwen3.5:0.8b")
FALLBACK_MODEL = os.environ.get("MACRO_MONITOR_FALLBACK_MODEL", "qwen3.5:4b")
FAST_FALLBACK_MODEL = os.environ.get("MACRO_MONITOR_FAST_MODEL", "qwen3.5:0.8b")
# Increased timeouts from 25s/30s to 60s/45s to allow model warm-up on first load
PRIMARY_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("MACRO_MONITOR_PRIMARY_TIMEOUT_SECONDS", "60.0"))
FALLBACK_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("MACRO_MONITOR_FALLBACK_TIMEOUT_SECONDS", "45.0"))
RETRY_BACKOFF_SECONDS = float(os.environ.get("MACRO_MONITOR_RETRY_BACKOFF", "2.0"))  # Wait 2s between retries
DEFAULT_CACHE_PATH = os.path.join("data", "macro_risk_cache.json")


def _normalize_symbol(symbol: str) -> str:
    if not symbol:
        return symbol
    compact = symbol.replace("/", "").upper()
    return compact


class MacroRiskCache:
    """Thread-safe in-memory + JSON cache for macro penalties."""

    def __init__(self, cache_path: str = DEFAULT_CACHE_PATH):
        self.cache_path = cache_path
        self._lock = threading.Lock()
        self._penalties: Dict[str, float] = {}
        self._reasons: Dict[str, str] = {}
        # PRODUCTION FIX: Initialize to current time instead of None
        # This prevents 'age_minutes=unknown' during first cycle while background task runs
        self._updated_at: str = datetime.now(timezone.utc).isoformat()
        self._source: str = "init"
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Load macro risk cache from disk with robust error handling."""
        
        # FIX: Use safe_json_load instead of raw json.load()
        payload = safe_json_load(
            file_path=self.cache_path,
            default={"penalties": {}, "reasons": {}},
            auto_recover=True,
        )
        
        # Extract fields with fallback to empty dicts
        penalties = payload.get("penalties", {}) if isinstance(payload, dict) else {}
        reasons = payload.get("reasons", {}) if isinstance(payload, dict) else {}
        
        with self._lock:
            self._penalties = {
                _normalize_symbol(k): float(max(0.0, min(0.4, v)))
                for k, v in penalties.items()
                if isinstance(v, (int, float))
            }
            self._reasons = {
                _normalize_symbol(k): str(v)[:200]
                for k, v in reasons.items()
            }
            # PRODUCTION FIX: Only overwrite _updated_at if disk has a valid value
            # Otherwise keep the startup timestamp we initialized with
            disk_updated_at = payload.get("_updated_at")
            if disk_updated_at:
                self._updated_at = disk_updated_at
            # If disk doesn't have _updated_at, keep the startup timestamp
            self._source = "disk"
            
            if self._penalties:
                logger.info(
                    f"[MACRO_CACHE_LOADED] {len(self._penalties)} penalties loaded from {self.cache_path}"
                )

    def update(
        self,
        penalties: Dict[str, float],
        source: str = "llm",
        reasons: Optional[Dict[str, str]] = None,
        *,
        replace: bool = True,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        normalized = {
            _normalize_symbol(k): float(max(0.0, min(0.4, v)))
            for k, v in penalties.items()
            if isinstance(v, (int, float))
        }
        normalized_reasons = {
            _normalize_symbol(k): str(v)
            for k, v in (reasons or {}).items()
            if isinstance(v, str) and str(v).strip()
        }
        with self._lock:
            if replace:
                self._penalties = dict(normalized)
                self._reasons = {}
                for key in normalized:
                    self._reasons[key] = normalized_reasons.get(key, "No_Macro_Risk")
            else:
                self._penalties.update(normalized)
                self._reasons.update(normalized_reasons)
            self._updated_at = now
            self._source = source
            snapshot = {
                "updated_at": self._updated_at,
                "source": self._source,
                "penalties": dict(self._penalties),
                "reasons": dict(self._reasons),
            }
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2)
        except Exception as exc:
            logger.warning("[MACRO_MONITOR] Failed to persist cache: %s", exc)

    def get_penalty(self, symbol: str) -> float:
        key = _normalize_symbol(symbol)
        with self._lock:
            return float(self._penalties.get(key, 0.0))

    def get_macro_risk_penalty(self, symbol: str) -> float:
        """Compatibility alias for direct cache usage."""
        return self.get_penalty(symbol)

    def get_penalty_reason(self, symbol: str) -> str:
        key = _normalize_symbol(symbol)
        with self._lock:
            return str(self._reasons.get(key, "No_Macro_Risk"))

    def get_macro_risk_reason(self, symbol: str) -> str:
        """Compatibility alias for direct cache usage."""
        return self.get_penalty_reason(symbol)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            # FIX: Check if cache is older than 60 minutes
            # If so, log warning but still return data (better than nothing)
            if self._updated_at:
                try:
                    updated_at = datetime.fromisoformat(self._updated_at)
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=timezone.utc)
                    age_minutes = (datetime.now(timezone.utc) - updated_at).total_seconds() / 60.0
                    
                    if age_minutes > 60.0:
                        logger.warning(
                            "[MACRO_CACHE_STALE] Cache is %.1f minutes old (>60 min threshold). "
                            "Data may be outdated but still returning last valid values.",
                            age_minutes,
                        )
                    elif age_minutes > 30.0:
                        logger.debug(
                            "[MACRO_CACHE_AGE] Cache is %.1f minutes old. Still within 60-min validity window.",
                            age_minutes,
                        )
                except Exception:
                    pass  # If can't parse timestamp, return data anyway
            
            return {
                "updated_at": self._updated_at,
                "source": self._source,
                "penalties": dict(self._penalties),
                "reasons": dict(self._reasons),
            }


macro_risk_cache = MacroRiskCache()


def get_macro_risk_penalty(symbol: str) -> float:
    """Fast read path for execution/admission code."""
    return macro_risk_cache.get_penalty(symbol)


def get_macro_risk_reason(symbol: str) -> str:
    """Fast read path for macro risk trigger reasons."""
    return macro_risk_cache.get_penalty_reason(symbol)


class AsyncLLMMacroMonitor:
    """
    Background task that periodically asks the LLM for macro risk penalties.
    """

    def __init__(
        self,
        symbols: List[str],
        *,
        interval_seconds: int = 900,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        context_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        calendar_provider: Optional[Callable[[], Any]] = None,
        news_collector: Optional[Any] = None,
    ):
        self.raw_symbols = list(symbols)
        self.symbols = [_normalize_symbol(s) for s in symbols]
        self.interval_seconds = max(300, int(interval_seconds))
        self.model = model
        self.primary_model = PRIMARY_MODEL
        self.fallback_model = FALLBACK_MODEL
        self.timeout_seconds = timeout_seconds
        self.primary_timeout_seconds = PRIMARY_REQUEST_TIMEOUT_SECONDS
        self.fallback_timeout_seconds = FALLBACK_REQUEST_TIMEOUT_SECONDS
        self.max_retries = max(1, int(max_retries))
        self.context_provider = context_provider
        self.calendar_provider = calendar_provider
        self.news_collector = news_collector
        # ✅ NEW: Reference to Finnhub macro manager (set by main.py after creation)
        self.finnhub_manager: Optional[Any] = None
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._consecutive_failures = 0
        self._heartbeat_interval_seconds = 60
        self._last_heartbeat_at: Optional[datetime] = None
        self._ollama_semaphore = asyncio.Semaphore(1)
        self._last_ollama_error: Optional[str] = None
        self._macro_eval_task: Optional[asyncio.Task] = None
        self._next_macro_eval_at: datetime = datetime.now(timezone.utc)
        self.enabled: bool = True
        self._http_disabled_until: Optional[datetime] = None
        self._heuristic_only_until: Optional[datetime] = None
        self.fail_open_after_attempts = max(1, int(os.environ.get("MACRO_FAIL_OPEN_AFTER_ATTEMPTS", "3")))
        self.technical_only_mode_active: bool = False
        self._ollama_reachable: Optional[bool] = None
        self._recovery_check_interval_seconds = 300
        self._last_recovery_check_at: Optional[datetime] = None
        self._macro_age_log_interval_seconds = 300
        self._last_macro_age_log_at: Optional[datetime] = None
        self._force_refresh_age_minutes = float(os.environ.get("MACRO_FORCE_REFRESH_MINUTES", "15"))

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        await self._validate_ollama_model_available()
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="macro-risk-monitor")
        logger.info(
            "[MACRO_MONITOR] Started | symbols=%s | interval=%ss",
            self.symbols,
            self.interval_seconds,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._macro_eval_task and not self._macro_eval_task.done():
            self._macro_eval_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._macro_eval_task
            self._macro_eval_task = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[MACRO_MONITOR] Stopped")

    async def _run_loop(self) -> None:
        try:
            await self._maybe_send_heartbeat(force=True)
            await self._tick_macro_evaluation(force_schedule=True)
            while not self._stop_event.is_set():
                waited = 0
                while waited < self.interval_seconds and not self._stop_event.is_set():
                    step = min(60, self.interval_seconds - waited)
                    await asyncio.sleep(step)
                    waited += step
                    await self._maybe_send_heartbeat()
                    await self._maybe_log_macro_data_age()
                    await self._maybe_force_refresh_stale_macro_data()
                    await self._maybe_probe_ollama_recovery()
                    await self._tick_macro_evaluation()
                await self._tick_macro_evaluation()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("[MACRO_MONITOR] Loop error: %s", exc, exc_info=True)

    async def _tick_macro_evaluation(self, force_schedule: bool = False) -> None:
        """
        Keep macro evaluation non-blocking:
        - schedule work with create_task
        - check task.done() each pulse
        """
        now = datetime.now(timezone.utc)
        if self._macro_eval_task is not None:
            if not self._macro_eval_task.done():
                return
            try:
                self._macro_eval_task.result()
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error("[MACRO_MONITOR] Background eval task failed: %s", exc, exc_info=True)
            finally:
                self._macro_eval_task = None
                self._next_macro_eval_at = now + timedelta(seconds=self.interval_seconds)
            return

        if not force_schedule and now < self._next_macro_eval_at:
            return
        self._macro_eval_task = asyncio.create_task(self._run_once(), name="macro-risk-eval")

    async def _maybe_probe_ollama_recovery(self) -> None:
        if not self.technical_only_mode_active:
            return
        fast_path_state = get_local_llm_fast_path_state()
        if fast_path_state.get("active"):
            return
        now_utc = datetime.now(timezone.utc)
        if (
            self._last_recovery_check_at is not None
            and (now_utc - self._last_recovery_check_at).total_seconds() < self._recovery_check_interval_seconds
        ):
            return
        self._last_recovery_check_at = now_utc
        try:
            await asyncio.to_thread(self._fetch_ollama_models)
            self._ollama_reachable = True
            self.technical_only_mode_active = False
            self._http_disabled_until = None
            self._heuristic_only_until = None
            self._next_macro_eval_at = datetime.now(timezone.utc)
            logger.info("[MACRO_MONITOR] Macro Monitor recovered. TECHNICAL_ONLY_MODE disabled.")
        except Exception as exc:
            self._ollama_reachable = False
            logger.warning("[MACRO_MONITOR] Recovery probe failed. Remaining in TECHNICAL_ONLY_MODE: %s", exc)

    async def _run_once(self) -> None:
        fast_path_state = get_local_llm_fast_path_state()
        fast_path_until = fast_path_state.get("until")
        if fast_path_state.get("active"):
            if not self.technical_only_mode_active:
                self._activate_technical_only_mode(
                    f"LOCAL_LLM_FAST_PATH:{fast_path_state.get('source') or 'unknown'}:{fast_path_state.get('reason') or 'threshold'}"
                )
            logger.warning(
                "[MACRO_MONITOR] Local LLM fast-path active until %s. Running Technical-Only mode to reduce CPU load.",
                fast_path_until.isoformat() if isinstance(fast_path_until, datetime) else "unknown",
            )
            return
        if self.technical_only_mode_active and isinstance(fast_path_until, datetime):
            clear_local_llm_fast_path()
            self._next_macro_eval_at = datetime.now(timezone.utc)
            logger.info("[MACRO_MONITOR] Local LLM fast-path expired. Retrying live Ollama macro analysis.")

        if self._http_disabled_until and datetime.now(timezone.utc) >= self._http_disabled_until:
            self._http_disabled_until = None
            logger.warning("[MACRO_MONITOR] Local HTTP cooldown expired. Retrying Ollama health checks.")

        if self._heuristic_only_until and datetime.now(timezone.utc) < self._heuristic_only_until:
            calendar_context = {}
            if self.calendar_provider:
                try:
                    calendar_context = self.calendar_provider() or {}
                except Exception:
                    calendar_context = {}
            fallback_penalties, _, fallback_reasons = self._build_resilient_fallback_penalties(calendar_context)
            macro_risk_cache.update(fallback_penalties, source="heuristic_only_mode", reasons=fallback_reasons)
            logger.warning(
                "[MACRO_MONITOR] Heuristic-only mode active until %s. HTTP LLM calls skipped.",
                self._heuristic_only_until.isoformat(),
            )
            return
        if self._heuristic_only_until and datetime.now(timezone.utc) >= self._heuristic_only_until:
            self._heuristic_only_until = None
            logger.warning("[MACRO_MONITOR] Heuristic-only window ended. Retrying live Ollama requests.")

        market_context = {}
        if self.context_provider:
            try:
                market_context = self.context_provider() or {}
            except Exception as exc:
                logger.warning("[MACRO_MONITOR] Context provider failed: %s", exc)

        # When news filtering is in Mock Mode (or unavailable), fall back to
        # volatility-aware macro risk instead of blocking every new entry.
        require_live_news = bool(
            getattr(getattr(getattr(self.news_collector, "config", None), "news", None), "require_live_data", False)
        )
        if self._news_filtering_is_mock_mode():
            if require_live_news:
                self._activate_technical_only_mode("LIVE_NEWS_UNAVAILABLE")
                logger.critical(
                    "[MACRO_MONITOR] Live news required but unavailable/mock. Trading must pause until a real news feed is restored."
                )
                return
            fallback_penalties: Dict[str, float] = {}
            fallback_reasons: Dict[str, str] = {}
            elevated_symbols: List[str] = []
            for symbol in self.symbols:
                fallback = self._derive_news_unavailable_fallback(symbol, market_context)
                fallback_penalties[symbol] = float(fallback.get("heuristic_penalty_hint", 0.0) or 0.0)
                fallback_reasons[symbol] = str(fallback.get("trigger_reason", "No_Macro_Risk"))
                if bool(fallback.get("high_impact_news_pending")):
                    elevated_symbols.append(symbol)
            macro_risk_cache.update(
                fallback_penalties,
                source="news_unavailable_volatility_fallback",
                reasons=fallback_reasons,
            )
            if elevated_symbols:
                logger.warning(
                    "[MACRO_MONITOR] News filtering unavailable/mock. Using volatility fallback; extreme-volatility guard remains active for %s.",
                    elevated_symbols,
                )
            else:
                logger.info(
                    "[MACRO_MONITOR] News filtering unavailable/mock. Using volatility fallback with LOW macro risk."
                )
            return

        calendar_context = {}
        if self.calendar_provider:
            try:
                calendar_context = self.calendar_provider() or {}
            except Exception as exc:
                logger.warning("[MACRO_MONITOR] Calendar provider failed: %s", exc)
        elif self.news_collector is not None:
            try:
                news_task = asyncio.create_task(
                    self.news_collector.collect_data(self.raw_symbols, timeframe="4h", allow_live_fetch=True),
                    name="macro-news-fetch",
                )
                news = await news_task
                calendar_context = self._extract_calendar_risk_from_news(news, market_context=market_context)
            except Exception as exc:
                logger.warning("[MACRO_MONITOR] News-based calendar extraction failed: %s", exc)

        # 404 kill-switch / heuristic-only window
        if self._http_disabled_until and datetime.now(timezone.utc) < self._http_disabled_until:
            fallback_penalties, fallback_source, fallback_reasons = self._build_resilient_fallback_penalties(calendar_context)
            macro_risk_cache.update(fallback_penalties, source="internal_heuristic_404_lockout", reasons=fallback_reasons)
            logger.warning(
                "[MACRO_MONITOR] HTTP disabled until %s. Using INTERNAL_HEURISTIC only.",
                self._http_disabled_until.isoformat(),
            )
            return

        prompt = self._build_prompt(market_context, calendar_context)
        raw = await self._call_ollama_with_retries(prompt)
        penalties, reasons = self._parse_penalties(raw)
        if penalties:
            self._consecutive_failures = 0
            self.enabled = True
            self._heuristic_only_until = None
            self._ollama_reachable = True
            if self.technical_only_mode_active:
                logger.info("[MACRO_MONITOR] Fresh macro data restored. Exiting TECHNICAL_ONLY_MODE.")
            self.technical_only_mode_active = False
            macro_risk_cache.update(penalties, source="llm_macro_monitor", reasons=reasons)
            logger.info("[MACRO_MONITOR] Cache updated for %d symbols", len(penalties))
        else:
            self._consecutive_failures += 1
            fallback_penalties, fallback_source, fallback_reasons = self._build_resilient_fallback_penalties(calendar_context)
            if self._consecutive_failures >= self.fail_open_after_attempts:
                self._activate_technical_only_mode(self._last_ollama_error or fallback_source)
            else:
                macro_risk_cache.update(fallback_penalties, source=fallback_source, reasons=fallback_reasons)
            elevated = sum(1 for p in fallback_penalties.values() if p > 0.0)
            logger.warning(
                "[MACRO_MONITOR] No valid penalties after retries (failure streak=%d). "
                "Applied resilient fallback '%s' for %d symbols (%d elevated > 0).",
                self._consecutive_failures,
                fallback_source,
                len(fallback_penalties),
                elevated,
            )

    async def _call_ollama_with_retries(self, prompt: str) -> str:
        """
        Async timeout wrapper with bounded retries.
        If all retries fail, caller falls back to neutral risk state.
        """
        self._last_ollama_error = None
        model_chain = [self.primary_model, self.fallback_model]
        for attempt in range(1, self.max_retries + 1):
            if self._http_disabled_until and datetime.now(timezone.utc) < self._http_disabled_until:
                return ""
            for model_for_attempt in model_chain:
                generation_task: Optional[asyncio.Task] = None
                timeout_for_model = (
                    self.primary_timeout_seconds
                    if model_for_attempt == self.primary_model
                    else self.fallback_timeout_seconds
                )
                try:
                    # Add backoff delay before retry attempts (not on first try)
                    if attempt > 1:
                        await asyncio.sleep(RETRY_BACKOFF_SECONDS)
                    async with self._ollama_semaphore:
                        generation_task = asyncio.create_task(
                            asyncio.to_thread(
                                self._call_ollama_blocking,
                                prompt,
                                model_name=model_for_attempt,
                                num_predict=150,  # Increased from 100 to allow longer responses
                                request_timeout=timeout_for_model,
                            )
                        )
                        raw = await asyncio.wait_for(generation_task, timeout=timeout_for_model)
                    if raw:
                        return raw
                    self._last_ollama_error = self._last_ollama_error or "EMPTY_RESPONSE"
                    stale_log = logger.warning if self._should_warn_on_feed_failure() else logger.info
                    stale_log(
                        "[MACRO_MONITOR] Empty Ollama response on attempt %d/%d (model=%s timeout=%.1fs) - retrying with backoff...",
                        attempt,
                        self.max_retries,
                        model_for_attempt,
                        timeout_for_model,
                    )
                    if model_for_attempt == self.primary_model:
                        fallback_text = await self._run_fallback_model(prompt, attempt)
                        if fallback_text:
                            return fallback_text
                except asyncio.TimeoutError:
                    if generation_task is not None:
                        with contextlib.suppress(Exception):
                            generation_task.cancel()
                            await generation_task
                    self._last_ollama_error = "TIMEOUT"
                    if model_for_attempt == self.primary_model:
                        logger.info(
                            "[MACRO_MONITOR] Primary model timed out on attempt %d/%d"
                            " (model=%s timeout=%.1fs). Falling back to %s.",
                            attempt,
                            self.max_retries,
                            self.primary_model,
                            timeout_for_model,
                            self.fallback_model,
                        )
                        fallback_text = await self._run_fallback_model(prompt, attempt)
                        if fallback_text:
                            return fallback_text
                    else:
                        logger.info(
                            "[MACRO_MONITOR] Ollama timed out on attempt %d/%d (model=%s timeout=%.1fs)",
                            attempt,
                            self.max_retries,
                            model_for_attempt,
                            timeout_for_model,
                        )
                except Exception as exc:
                    self._last_ollama_error = self._last_ollama_error or "REQUEST_EXCEPTION"
                    stale_log = logger.warning if self._should_warn_on_feed_failure() else logger.info
                    stale_log(
                        "[MACRO_MONITOR] Ollama request failed on attempt %d/%d (model=%s timeout=%.1fs): %s",
                        attempt,
                        self.max_retries,
                        model_for_attempt,
                        timeout_for_model,
                        exc,
                    )
                    if model_for_attempt == self.primary_model and self._is_timeout_or_client_error(exc):
                        fallback_text = await self._run_fallback_model(prompt, attempt)
                        if fallback_text:
                            return fallback_text
                    elif model_for_attempt == self.primary_model:
                        logger.warning(
                            "[MACRO_MONITOR] Primary model failed (%s). Falling back to %s.",
                            self.primary_model,
                            self.fallback_model,
                        )

            if attempt < self.max_retries:
                backoff = min(30.0, 1.5 * (2 ** (attempt - 1)))
                jitter = random.uniform(0.0, 0.75)
                await asyncio.sleep(backoff + jitter)
                await asyncio.sleep(1.0)
        self._set_local_http_cooldown(self._last_ollama_error or "OLLAMA_UNAVAILABLE")
        self._enter_heuristic_mode()
        return ""

    async def _run_fallback_model(self, prompt: str, attempt: int) -> str:
        """Run explicit fallback request and return its text for task.result harvesting."""
        timeout_for_model = self.fallback_timeout_seconds
        generation_task: Optional[asyncio.Task] = None
        try:
            # Add backoff before fallback attempt
            await asyncio.sleep(RETRY_BACKOFF_SECONDS)
            async with self._ollama_semaphore:
                generation_task = asyncio.create_task(
                    asyncio.to_thread(
                        self._call_ollama_blocking,
                        prompt,
                        model_name=self.fallback_model,
                        num_predict=150,  # Increased from 100
                        request_timeout=timeout_for_model,
                    )
                )
                text = await asyncio.wait_for(generation_task, timeout=timeout_for_model)
            if text:
                return text
            logger.warning(
                "[MACRO_MONITOR] Empty Ollama response on attempt %d/%d (model=%s timeout=%.1fs)",
                attempt,
                self.max_retries,
                self.fallback_model,
                timeout_for_model,
            )
            return ""
        except asyncio.TimeoutError:
            if generation_task is not None:
                with contextlib.suppress(Exception):
                    generation_task.cancel()
                    await generation_task
            self._last_ollama_error = "TIMEOUT"
            logger.warning(
                "[MACRO_MONITOR] Ollama timed out on attempt %d/%d (model=%s timeout=%.1fs)",
                attempt,
                self.max_retries,
                self.fallback_model,
                timeout_for_model,
            )
            return ""
        except Exception as exc:
            self._last_ollama_error = self._last_ollama_error or "REQUEST_EXCEPTION"
            logger.warning(
                "[MACRO_MONITOR] Ollama request failed on attempt %d/%d (model=%s timeout=%.1fs): %s",
                attempt,
                self.max_retries,
                self.fallback_model,
                timeout_for_model,
                exc,
            )
            return ""

    def _is_timeout_or_client_error(self, exc: Exception) -> bool:
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError, urllib.error.URLError)):
            return True
        if aiohttp is not None:
            try:
                if isinstance(exc, aiohttp.ClientError):
                    return True
            except Exception:
                pass
        return False

    def _enter_heuristic_mode(self) -> None:
        """
        Enable temporary heuristic-only mode with short local cooldown.
        """
        window_seconds = 300
        self._heuristic_only_until = datetime.now(timezone.utc) + timedelta(seconds=window_seconds)
        logger.warning(
            "[MACRO_MONITOR] Entering heuristic-only mode for %ds (failure streak=%d).",
            window_seconds,
            self._consecutive_failures,
        )

    def _set_local_http_cooldown(self, reason: str) -> None:
        cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=5)
        self._http_disabled_until = cooldown_until
        self._ollama_reachable = False
        logger.warning(
            "[MACRO_MONITOR] Local Ollama cooldown (5m) due to %s. HTTP disabled until %s.",
            reason,
            cooldown_until.isoformat(),
        )

    def _activate_technical_only_mode(self, reason: str) -> None:
        self.technical_only_mode_active = True
        self._ollama_reachable = False
        zero_penalties = {symbol: 0.0 for symbol in self.symbols}
        zero_reasons = {symbol: "Technical_Only_Mode" for symbol in self.symbols}
        macro_risk_cache.update(
            zero_penalties,
            source=f"technical_only_mode:{reason}",
            reasons=zero_reasons,
        )
        logger.warning(
            "[TECHNICAL_ONLY_MODE] Ollama unreachable. Switching to Technical-Only Mode. failures=%d reason=%s",
            self._consecutive_failures,
            reason,
        )

    async def _validate_ollama_model_available(self) -> None:
        """
        Startup pre-flight check: verify Ollama is reachable.
        HARDCODED: Uses qwen3.5:0.8b for all macro monitoring (no fallbacks).
        """
        try:
            models = await asyncio.to_thread(self._fetch_ollama_models)
            self._ollama_reachable = True
            if not models:
                logger.warning("[MACRO_MONITOR] Ollama model list is empty.")
                return
            logger.info("[MACRO_MONITOR] Available Ollama models: %s", models)

            # HARDCODED: qwen3.5:0.8b for all macro monitoring tasks
            macro_model = "qwen3.5:0.8b"
            normalized = {str(m).strip().lower() for m in models if str(m).strip()}
            macro_expected = {macro_model, f"{macro_model}:latest"}

            if normalized.isdisjoint(macro_expected):
                logger.warning(
                    "[MACRO_MONITOR] qwen3.5:0.8b not in model list. Available: %s (will use cached data)",
                    sorted(normalized)[:3],
                )
            else:
                logger.info("[MACRO_MONITOR] ✅ qwen3.5:0.8b ready for macro analysis")
        except Exception as exc:
            self._ollama_reachable = False
            logger.warning("[MACRO_MONITOR] Startup check completed: %s", str(exc)[:80])

    async def check_data_health(self) -> Dict[str, Any]:
        snapshot = macro_risk_cache.snapshot()
        now_utc = datetime.now(timezone.utc)
        cache_age_minutes = self._get_macro_data_age_minutes()

        ollama_reachable = bool(self._ollama_reachable)
        if not self._http_disabled_until or now_utc >= self._http_disabled_until:
            try:
                await asyncio.to_thread(self._fetch_ollama_models)
                ollama_reachable = True
                self._ollama_reachable = True
            except Exception as exc:
                ollama_reachable = False
                self._ollama_reachable = False
                self._last_ollama_error = self._last_ollama_error or str(exc)

        max_staleness_minutes = float(
            os.environ.get(
                "MACRO_STALENESS_THRESHOLD",
                os.environ.get("MACRO_NEWS_MAX_STALENESS_MINUTES", "60"),
            )
        )
        news_cache_fresh = bool(cache_age_minutes is not None and cache_age_minutes <= max_staleness_minutes)
        if self.technical_only_mode_active:
            news_cache_fresh = False

        return {
            "ollama_reachable": bool(ollama_reachable),
            "news_cache_fresh": bool(news_cache_fresh),
            "cache_age_minutes": cache_age_minutes,
            "technical_only_mode": bool(self.technical_only_mode_active),
            "last_error": self._last_ollama_error,
            "consecutive_failures": int(self._consecutive_failures),
            "http_disabled_until": self._http_disabled_until.isoformat() if self._http_disabled_until else None,
            "source": snapshot.get("source") if isinstance(snapshot, dict) else None,
        }

    async def CheckDataHealth(self) -> Dict[str, Any]:
        return await self.check_data_health()

    def _fetch_ollama_models(self) -> List[str]:
        req = urllib.request.Request(OLLAMA_TAGS_URL, method="GET")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        models = payload.get("models", []) if isinstance(payload, dict) else []
        names: List[str] = []
        for item in models:
            if isinstance(item, dict):
                name = item.get("name") or item.get("model")
                if name:
                    names.append(str(name))
            elif isinstance(item, str):
                names.append(item)
        return names

    @staticmethod
    def _coerce_float(value: Any) -> float:
        try:
            return float(value)
        except Exception:
            return 0.0

    def _iter_symbol_contexts(self, market_context: Dict[str, Any], symbol: str) -> List[Dict[str, Any]]:
        contexts: List[Dict[str, Any]] = []
        if not isinstance(market_context, dict):
            return contexts

        normalized = _normalize_symbol(symbol)
        variants = {
            symbol,
            normalized,
            normalized.replace("/", ""),
            normalized.replace("/", "_"),
            normalized.replace("/", "-"),
        }

        for key in variants:
            value = market_context.get(key)
            if isinstance(value, dict):
                contexts.append(value)

        for container_key in ("symbols", "markets", "pairs", "symbol_data", "market_context"):
            container = market_context.get(container_key)
            if not isinstance(container, dict):
                continue
            for key in variants:
                value = container.get(key)
                if isinstance(value, dict):
                    contexts.append(value)

        contexts.append(market_context)
        return contexts

    def _derive_news_unavailable_fallback(self, symbol: str, market_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        contexts = self._iter_symbol_contexts(market_context or {}, symbol)
        atr_ratio = 0.0
        volatility_ratio = 0.0
        atr_percentile = 0.0
        volatility_zscore = 0.0
        volatility_regime = ""

        for ctx in contexts:
            atr_ratio = max(
                atr_ratio,
                self._coerce_float(ctx.get("atr_ratio")),
                self._coerce_float(ctx.get("volatility_ratio")),
            )
            atr_percentile = max(
                atr_percentile,
                self._coerce_float(ctx.get("atr_percentile")),
                self._coerce_float(ctx.get("volatility_percentile")),
            )
            volatility_zscore = max(
                volatility_zscore,
                abs(self._coerce_float(ctx.get("volatility_zscore"))),
                abs(self._coerce_float(ctx.get("atr_zscore"))),
            )
            if not volatility_regime:
                volatility_regime = str(ctx.get("volatility_regime") or ctx.get("vol_regime") or "").upper()

            atr = self._coerce_float(ctx.get("atr"))
            atr_mean = self._coerce_float(ctx.get("atr_mean"))
            if atr > 0.0 and atr_mean > 0.0:
                volatility_ratio = max(volatility_ratio, atr / atr_mean)

        ratio = max(atr_ratio, volatility_ratio)
        regime_upper = volatility_regime.upper()
        extreme_volatility = (
            ratio >= 1.35
            or atr_percentile >= 85.0
            or volatility_zscore >= 2.0
            or "EXTREME" in regime_upper
            or "HIGH_VOL" in regime_upper
        )
        elevated_volatility = (
            ratio >= 1.15
            or atr_percentile >= 70.0
            or volatility_zscore >= 1.25
            or "HIGH" in regime_upper
        )

        if extreme_volatility:
            return {
                "heuristic_penalty_hint": 0.28,
                "events": ["VOLATILITY_FALLBACK_EXTREME"],
                "macro_risk": "HIGH",
                "high_impact_news_pending": True,
                "trigger_reason": "EXTREME_VOLATILITY_FALLBACK",
            }

        if elevated_volatility:
            return {
                "heuristic_penalty_hint": 0.10,
                "events": ["VOLATILITY_FALLBACK_ELEVATED"],
                "macro_risk": "MEDIUM",
                "high_impact_news_pending": False,
                "trigger_reason": "ELEVATED_VOLATILITY_FALLBACK",
            }

        return {
            "heuristic_penalty_hint": 0.0,
            "events": ["VOLATILITY_FALLBACK_NORMAL"],
            "macro_risk": "LOW",
            "high_impact_news_pending": False,
            "trigger_reason": "VOLATILITY_NORMAL_FALLBACK",
        }

    def _extract_calendar_risk_from_news(self, news_payload: Any, market_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        high_impact_keywords = ("NFP", "CPI", "FOMC", "INTEREST RATE", "FED", "ECB", "BOJ", "GDP", "NON-FARM")
        out: Dict[str, Any] = {}
        if not isinstance(news_payload, dict):
            return out
        for symbol, items in news_payload.items():
            symbol_key = _normalize_symbol(symbol)
            penalty = 0.0
            events = []
            is_mock = False
            for item in items or []:
                url = str(getattr(item, "url", ""))
                if "example.com" in url or "mock" in url.lower():
                    is_mock = True
                    break

            if is_mock:
                out[symbol_key] = self._derive_news_unavailable_fallback(symbol_key, market_context)
                logger.info(
                    "[MACRO_FALLBACK] %s | Mock news detected. Using volatility-aware fallback (%s).",
                    symbol_key,
                    out[symbol_key].get("trigger_reason", "VOLATILITY_NORMAL_FALLBACK"),
                )
                continue

            for item in items or []:
                title = str(getattr(item, "title", ""))
                content = str(getattr(item, "content", ""))
                text = f"{title} {content}".upper()
                if any(k in text for k in high_impact_keywords):
                    penalty = max(penalty, 0.10)
                    events.append(title[:120])
            out[symbol_key] = {
                "heuristic_penalty_hint": penalty,
                "events": events[:5],
            }
        return out

    def _news_filtering_is_mock_mode(self) -> bool:
        """
        Detect "Mock Mode" for news filtering.
        main.py logs this as DISABLED (Mock Mode) when config.news.enabled is False.
        """
        try:
            if self.news_collector is None:
                return False

            cfg = getattr(self.news_collector, "config", None)
            if cfg is None:
                return False

            news_cfg = getattr(cfg, "news", None)
            if isinstance(news_cfg, dict):
                enabled = news_cfg.get("enabled")
            else:
                enabled = getattr(news_cfg, "enabled", None)

            if enabled is False:
                return True
        except Exception:
            return False

        # Optional env override (fallback)
        env_mode = str(os.environ.get("NEWS_FILTERING_MODE", "")).strip().lower()
        if env_mode == "mock mode" or "mock" in env_mode:
            return True

        env_enabled = str(os.environ.get("NEWS_ENABLED", "")).strip().lower()
        if env_enabled in {"0", "false", "off", "disabled"}:
            return True

        return False

    def _build_prompt(self, market_context: Dict[str, Any], calendar_context: Dict[str, Any]) -> str:
        payload = {
            "symbols": self.symbols,
            "market_context": market_context,
            "calendar_context": calendar_context,
            "instruction": (
                "Return ONLY JSON mapping each symbol to macro_risk_penalty in [0.0,0.4]. "
                "Use higher penalties near major macro events (e.g., NFP/CPI/FOMC). "
                "Include trigger_reason for each symbol."
            ),
            "schema": {
                "penalties": {
                    "EURUSD": {"macro_risk_penalty": 0.0, "trigger_reason": "No_Macro_Risk"},
                    "GBPUSD": {"macro_risk_penalty": 0.0, "trigger_reason": "No_Macro_Risk"},
                }
            },
        }
        return (
            "Act as a raw data server. Return ONLY a single JSON object. No conversation. No markdown. No headers.\n"
            "Assess near-term macro/event risk per symbol.\n"
            "Output JSON with shape: {\"penalties\":{\"SYMBOL\":{\"macro_risk_penalty\":0.0,\"trigger_reason\":\"No_Macro_Risk\"}}}\n"
            f"Input:\n{json.dumps(payload, ensure_ascii=True)}"
        )

    def _call_ollama_blocking(
        self,
        prompt: str,
        *,
        model_name: Optional[str] = None,
        num_predict: int = 100,
        request_timeout: Optional[float] = None,
    ) -> str:
        """
        Synchronous HTTP POST to Ollama API with robust error handling.
        
        IMPROVEMENTS:
        1. ✅ Increased timeout from 15s to 60s (configurable via env)
        2. ✅ Detailed exception handling: HTTP status codes, connection errors, JSON parsing
        3. ✅ Keep-alive parameter to keep model in memory between calls
        4. ✅ Comprehensive logging for debugging
        5. ✅ Handles empty responses gracefully
        
        Returns: raw response text (empty string on any error)
        """
        target_model = model_name or self.model
        # For main generation calls, force model-specific timeout values
        if request_timeout is not None:
            effective_timeout = float(request_timeout)
        elif target_model == self.primary_model:
            effective_timeout = self.primary_timeout_seconds
        elif target_model == self.fallback_model:
            effective_timeout = self.fallback_timeout_seconds
        else:
            effective_timeout = float(self.timeout_seconds or 60.0)
        
        body = json.dumps(
            {
                "model": target_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "keep_alive": "5m",  # Keep model in memory for 5 minutes between requests
                "options": {
                    "num_predict": int(num_predict),
                    "temperature": 0.1,
                    "top_p": 0.85,
                },
            }
        ).encode("utf-8")
        
        req = urllib.request.Request(
            OLLAMA_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Connection": "keep-alive",  # HTTP keep-alive for connection reuse
            },
            method="POST",
        )
        
        try:
            with OLLAMA_REQUEST_LOCK:
                socket_timeout = max(65.0, effective_timeout + 5.0)
                try:
                    with urllib.request.urlopen(req, timeout=socket_timeout) as resp:
                        http_code = resp.getcode()
                        raw = json.loads(resp.read().decode("utf-8"))
                        self._ollama_reachable = True
                        
                        # Extract response: Qwen3.5 puts output in 'thinking' field if 'response' is empty
                        response_text = raw.get("response", "")
                        thinking_text = raw.get("thinking", "")
                        
                        # Fallback to thinking field if response is empty (Qwen3.5 reasoning model behavior)
                        if not response_text.strip() and thinking_text.strip():
                            return thinking_text
                        
                        return response_text or ""
                
                except json.JSONDecodeError as e:
                    # JSON parsing error - log details
                    self._last_ollama_error = "JSON_PARSE_ERROR"
                    logger.warning(
                        "[MACRO_MONITOR_JSON_ERROR] JSON parse failed (model=%s timeout=%.1fs): %s",
                        target_model,
                        effective_timeout,
                        str(e)[:80],
                    )
                    return ""
        
        except urllib.error.HTTPError as exc:
            # HTTP-level errors (4xx, 5xx)
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                error_body = ""
            
            http_code = getattr(exc, "code", None)
            self._last_ollama_error = f"HTTP_{http_code}" if http_code else "HTTP_ERROR"
            
            logger.warning(
                "[MACRO_MONITOR_HTTP_ERROR] Ollama HTTP %s | model=%s | timeout=%.1fs | URL=%s | Body=%s",
                http_code or "ERR",
                target_model,
                effective_timeout,
                OLLAMA_URL,
                error_body or "<empty>",
            )
            
            # Special handling for 404 (likely missing model)
            if http_code == 404:
                self._set_local_http_cooldown("HTTP_404_MODEL_NOT_FOUND")
            
            return ""
        
        except urllib.error.URLError as exc:
            # Connection-level errors (DNS, connection refused, timeout, etc.)
            reason = str(getattr(exc, "reason", exc))
            
            # Detect timeout vs connection error
            if isinstance(exc.reason, OSError):
                errno_val = getattr(exc.reason, "errno", None)
                # errno 110 = ETIMEDOUT, 54/60 = ECONNRESET/ETIMEDOUT on macOS
                is_timeout = errno_val in (110, 54, 60) or "timed out" in reason.lower()
            else:
                is_timeout = "timed out" in reason.lower()
            
            if is_timeout:
                self._last_ollama_error = "TIMEOUT"
                logger.warning(
                    "[MACRO_MONITOR_TIMEOUT] Ollama timeout after %.1fs | model=%s | URL=%s",
                    effective_timeout,
                    target_model,
                    OLLAMA_URL,
                )
                raise TimeoutError(f"Ollama timeout after {effective_timeout}s")
            else:
                self._last_ollama_error = "CONNECTION_REFUSED"
                self._ollama_reachable = False
                logger.warning(
                    "[MACRO_MONITOR_CONNECTION_ERROR] Ollama unreachable | model=%s | URL=%s | Reason=%s",
                    target_model,
                    OLLAMA_URL,
                    reason[:100],
                )
                return ""
        
        except TimeoutError as exc:
            # Re-raise so asyncio.wait_for in the outer wrapper sees the timeout
            # and the fallback model is properly triggered
            self._last_ollama_error = "TIMEOUT"
            raise
        
        except Exception as exc:
            # Catch-all for unexpected errors
            self._last_ollama_error = "REQUEST_EXCEPTION"
            logger.warning(
                "[MACRO_MONITOR_ERROR] Ollama request failed | model=%s | timeout=%.1fs | Error=%s",
                target_model,
                effective_timeout,
                str(exc)[:100],
            )
            return ""

    def _parse_penalties(self, raw: str) -> tuple[Dict[str, float], Dict[str, str]]:
        if not raw:
            return {}, {}
        raw = self._clean_response(raw)
        parsed = None
        try:
            parsed = json.loads(raw)
        except Exception:
            # Try to extract JSON using regex from the raw text
            match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except Exception:
                    pass
            # Fallback: extract from first { to last }
            if parsed is None:
                start = raw.find("{")
                end = raw.rfind("}")
                if start != -1 and end > start:
                    try:
                        parsed = json.loads(raw[start : end + 1])
                    except Exception:
                        return {}, {}
        if not isinstance(parsed, dict):
            return {}, {}
        penalties_section = parsed.get("penalties", parsed)
        if not isinstance(penalties_section, dict):
            return {}, {}

        result: Dict[str, float] = {}
        reasons: Dict[str, str] = {}
        for sym, val in penalties_section.items():
            symbol_key = _normalize_symbol(str(sym))
            if isinstance(val, dict):
                p = val.get("macro_risk_penalty", 0.0)
                reason = str(val.get("trigger_reason", "") or "").strip()
            else:
                p = val
                reason = ""
            try:
                p_val = float(p)
            except Exception:
                continue
            result[symbol_key] = max(0.0, min(0.4, p_val))
            if reason:
                reasons[symbol_key] = reason
            elif p_val > 0.0:
                reasons[symbol_key] = "LLM_Macro_Risk"
            else:
                reasons[symbol_key] = "No_Macro_Risk"
        return result, reasons

    def _clean_response(self, raw: str) -> str:
        """
        Strip auxiliary thinking tags that can break strict JSON parsing.
        """
        cleaned = raw
        cleaned = re.sub(r"<\s*thought\s*>.*?<\s*/\s*thought\s*>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"<\s*think\s*>.*?<\s*/\s*think\s*>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        return cleaned.strip()

    def _select_model_for_attempt(self) -> str:
        """
        Prefer primary model in normal mode, fallback model during failure streaks.
        """
        if self._consecutive_failures > 0:
            return self.fallback_model
        return self.primary_model

    async def _maybe_send_heartbeat(self, force: bool = False) -> None:
        """
        Keep the Ollama model warm to reduce cold-start timeout spikes.
        """
        now = datetime.now(timezone.utc)
        if self._http_disabled_until and now < self._http_disabled_until:
            return
        if not force and self._last_heartbeat_at and (now - self._last_heartbeat_at).total_seconds() < self._heartbeat_interval_seconds:
            return
        heartbeat_model = self._select_model_for_attempt()
        try:
            async with self._ollama_semaphore:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        self._call_ollama_blocking,
                        ".",
                        model_name=heartbeat_model,
                        num_predict=1,
                    ),
                    timeout=5.0,
                )
            self._last_heartbeat_at = now
            if self._heuristic_only_until and now < self._heuristic_only_until:
                self._heuristic_only_until = None
                self.enabled = True
                self._http_disabled_until = None
                logger.warning("[MACRO_MONITOR] Health check recovered. Re-enabling HTTP LLM calls early.")
            logger.debug("[MACRO_MONITOR] Ollama heartbeat sent (model=%s)", heartbeat_model)
        except Exception as exc:
            logger.debug("[MACRO_MONITOR] Heartbeat failed (model=%s): %s", heartbeat_model, exc)

    def _get_macro_data_age_minutes(self) -> float:
        """
        FIX: Return age in minutes, defaulting to 999 if cache is empty or fetch failed.
        This prevents 'age_minutes=unknown' which breaks health monitor logic.
        
        FIX #3: Check Finnhub's last_successful_refresh timestamp to preserve valid cache age
        even when current fetch cycle fails. Don't let age jump to 999 if we have recent data.
        """
        snapshot = macro_risk_cache.snapshot()
        now_utc = datetime.now(timezone.utc)
        updated_at_raw = snapshot.get("updated_at") if isinstance(snapshot, dict) else None
        cache_age_minutes: Optional[float] = None
        if isinstance(updated_at_raw, str) and updated_at_raw:
            try:
                updated_at = datetime.fromisoformat(updated_at_raw)
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                cache_age_minutes = (now_utc - updated_at).total_seconds() / 60.0
            except Exception:
                cache_age_minutes = None

        # FIX #3: Check Finnhub's last successful refresh time
        finnhub_age_minutes: Optional[float] = None
        if self.finnhub_manager is not None:
            try:
                last_refresh = getattr(self.finnhub_manager, '_last_successful_refresh', None)
                if isinstance(last_refresh, datetime):
                    if last_refresh.tzinfo is None:
                        last_refresh = last_refresh.replace(tzinfo=timezone.utc)
                    finnhub_age_minutes = (now_utc - last_refresh).total_seconds() / 60.0
                    logger.debug(
                        "[MACRO_AGE_FINNHUB] Last successful Finnhub refresh: %.1f minutes ago",
                        finnhub_age_minutes,
                    )
            except Exception as exc:
                logger.debug("[MACRO_AGE_FINNHUB] Failed to get Finnhub refresh time: %s", exc)

        news_age_minutes: Optional[float] = None
        if self.raw_symbols:
            news_ages = [
                NewsDataCollector.get_data_age_minutes(symbol)
                for symbol in self.raw_symbols
            ]
            valid_news_ages = [age for age in news_ages if age is not None]
            if valid_news_ages:
                news_age_minutes = min(valid_news_ages)

        # FIX #3: Use the MINIMUM age from all available sources (prefer most recent data)
        freshness_candidates = [
            age for age in (cache_age_minutes, finnhub_age_minutes, news_age_minutes) if age is not None
        ]
        
        # FIX: Return 999 (large number) instead of None to indicate stale/unknown data
        return min(freshness_candidates) if freshness_candidates else 999.0

    async def _maybe_log_macro_data_age(self) -> None:
        now = datetime.now(timezone.utc)
        if (
            self._last_macro_age_log_at is not None
            and (now - self._last_macro_age_log_at).total_seconds() < self._macro_age_log_interval_seconds
        ):
            return
        self._last_macro_age_log_at = now
        age_minutes = self._get_macro_data_age_minutes()
        # FIX: Always show numeric age (999.0 means stale/unknown)
        logger.info(
            "[MACRO_DATA_AGE] age_minutes=%.1f | refresh_limit=%.1f | technical_only_mode=%s",
            age_minutes,
            self._force_refresh_age_minutes,
            self.technical_only_mode_active,
        )

    async def _maybe_force_refresh_stale_macro_data(self) -> None:
        if self.news_collector is None or not self.raw_symbols:
            return
        age_minutes = self._get_macro_data_age_minutes()
        if age_minutes is not None and age_minutes <= self._force_refresh_age_minutes:
            return

        logger.warning(
            "[MACRO_FORCE_REFRESH] Macro/news data age is %s minutes. Forcing refresh for %d symbols.",
            "unknown" if age_minutes is None else f"{age_minutes:.1f}",
            len(self.raw_symbols),
        )
        try:
            await self.news_collector.collect_data(
                self.raw_symbols,
                timeframe="4h",
                force_refresh=True,
                allow_live_fetch=True,
            )
            self._next_macro_eval_at = datetime.now(timezone.utc)
            logger.info("[MACRO_FORCE_REFRESH] News refresh completed. Macro evaluation rescheduled immediately.")
        except Exception as exc:
            logger.warning("[MACRO_FORCE_REFRESH] Forced news refresh failed: %s", exc)

    def _build_resilient_fallback_penalties(self, calendar_context: Dict[str, Any]) -> tuple[Dict[str, float], str, Dict[str, str]]:
        """
        Fallback path when Ollama is unavailable.
        Priority:
        1) Calendar/news heuristic hints.
        2) Decayed last-known cache penalties.
        3) Failsafe baseline penalty after repeated failures (never all-zero blindness).
        """
        penalties = {symbol: 0.0 for symbol in self.symbols}
        reasons = {symbol: "No_Macro_Risk" for symbol in self.symbols}
        source = "resilient_fallback"

        # 1) Calendar/news heuristic hints if available.
        heuristic_applied = False
        if isinstance(calendar_context, dict):
            for symbol in self.symbols:
                ctx = calendar_context.get(symbol)
                if not isinstance(ctx, dict):
                    continue
                hint = ctx.get("heuristic_penalty_hint", 0.0)
                try:
                    hint_val = float(hint)
                except Exception:
                    hint_val = 0.0
                hint_val = max(0.0, min(0.4, hint_val))
                if hint_val > 0.0:
                    penalties[symbol] = max(penalties[symbol], hint_val)
                    reasons[symbol] = "High_Impact_News_Pending"
                    heuristic_applied = True

        # 2) Blend with recent cached penalties (decayed) to preserve risk continuity.
        snap = macro_risk_cache.snapshot()
        cached = snap.get("penalties", {}) if isinstance(snap, dict) else {}
        updated_at_raw = snap.get("updated_at") if isinstance(snap, dict) else None
        updated_at = None
        if isinstance(updated_at_raw, str):
            try:
                updated_at = datetime.fromisoformat(updated_at_raw)
            except Exception:
                updated_at = None

        decay = 1.0
        if isinstance(updated_at, datetime):
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - updated_at
            if age > timedelta(hours=6):
                decay = 0.7
            if age > timedelta(hours=24):
                decay = 0.45
            if age > timedelta(hours=48):
                decay = 0.25

        cache_applied = False
        if isinstance(cached, dict):
            for symbol in self.symbols:
                prev = cached.get(symbol, 0.0)
                try:
                    prev_val = float(prev)
                except Exception:
                    prev_val = 0.0
                prev_val = max(0.0, min(0.4, prev_val))
                if prev_val > 0.0:
                    penalties[symbol] = max(penalties[symbol], prev_val * decay)
                    if reasons[symbol] == "No_Macro_Risk":
                        reasons[symbol] = "Carry_Forward_Macro_Risk"
                    cache_applied = True

        # 3) Last resort: if still all zero and monitor keeps failing, apply conservative baseline.
        if not any(v > 0.0 for v in penalties.values()):
            baseline = 0.0
            if self._consecutive_failures >= 2:
                baseline = 0.06
            if self._consecutive_failures >= 4:
                baseline = 0.10
            if baseline > 0.0:
                penalties = {symbol: baseline for symbol in self.symbols}
                reasons = {symbol: "LLM_Unavailable_Failsafe_Baseline" for symbol in self.symbols}
                source = "failsafe_baseline_fallback"
            else:
                source = "resilient_zero_fallback"
        else:
            if heuristic_applied and cache_applied:
                source = "heuristic_plus_cache_fallback"
            elif heuristic_applied:
                source = "heuristic_calendar_fallback"
            else:
                source = "decayed_cache_fallback"

        # Clamp all values in range.
        if "heuristic" in source:
            penalties = {k: min(float(v), 0.10) for k, v in penalties.items()}
        penalties = {k: max(0.0, min(0.4, float(v))) for k, v in penalties.items()}
        return penalties, source, reasons


class MacroHealthMonitor(threading.Thread):
    """Daemon thread that prevents stale macro/news blindness."""

    def __init__(
        self,
        monitor: AsyncLLMMacroMonitor,
        loop: asyncio.AbstractEventLoop,
        *,
        check_interval_seconds: int = 60,
        stale_limit_minutes: float = 60.0,
        request_timeout_seconds: float = 45.0,
    ):
        super().__init__(name="macro-health-monitor", daemon=True)
        self.monitor = monitor
        self.loop = loop
        self.check_interval_seconds = max(5, int(check_interval_seconds))
        self.stale_limit_minutes = float(stale_limit_minutes)
        self.request_timeout_seconds = float(request_timeout_seconds)
        self._stop_event = threading.Event()
        self._consecutive_recovery_failures = 0
        self._next_recovery_attempt_at: Optional[datetime] = None
        self._news_feed_failures = 0
        self._calendar_feed_failures = 0
        self._feed_warning_threshold = 3

    def stop(self) -> None:
        self._stop_event.set()

    def _reset_recovery_backoff(self) -> None:
        self._consecutive_recovery_failures = 0
        self._next_recovery_attempt_at = None
        self._news_feed_failures = 0
        self._calendar_feed_failures = 0

    def _update_feed_failures(
        self,
        *,
        news_ok: Optional[bool] = None,
        calendar_ok: Optional[bool] = None,
    ) -> None:
        if news_ok is not None:
            self._news_feed_failures = 0 if news_ok else self._news_feed_failures + 1
        if calendar_ok is not None:
            self._calendar_feed_failures = 0 if calendar_ok else self._calendar_feed_failures + 1

    def _should_warn_on_feed_failure(self) -> bool:
        return (
            self._news_feed_failures > self._feed_warning_threshold
            and self._calendar_feed_failures > self._feed_warning_threshold
        )

    def _register_recovery_failure(
        self,
        reason: str,
        *,
        hard_failure: bool = False,
        emit_warning: bool = True,
    ) -> None:
        self._consecutive_recovery_failures += 1
        backoff_seconds = min(300.0, 15.0 * (2 ** max(self._consecutive_recovery_failures - 1, 0)))
        self._next_recovery_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
        log_fn = logger.warning if emit_warning else logger.info
        log_fn(
            "[MACRO_HEALTHMONITOR] Recovery failure #%d | reason=%s | next_attempt_in=%.1fs",
            self._consecutive_recovery_failures,
            reason,
            backoff_seconds,
        )
        if hard_failure and self._consecutive_recovery_failures >= 3 and self._should_warn_on_feed_failure():
            logger.error(
                "[MACRO_HEALTHMONITOR] Recovery exceeded safe retry budget. "
                "Enabling TECHNICAL_ONLY_MODE for safe degraded trading."
            )
            self.monitor._activate_technical_only_mode("MACRO_HEALTHMONITOR_RECOVERY_FAILED")

    def run(self) -> None:
        logger.info(
            "[MACRO_HEALTHMONITOR] ✅ Health monitor thread started | "
            "Check interval: %ds | Stale limit: %.1f minutes",
            self.check_interval_seconds,
            self.stale_limit_minutes,
        )
        
        while not self._stop_event.wait(self.check_interval_seconds):
            try:
                now_utc = datetime.now(timezone.utc)
                if self._next_recovery_attempt_at and now_utc < self._next_recovery_attempt_at:
                    continue

                # Check if Finnhub manager is available
                finnhub_manager = getattr(self.monitor, "finnhub_manager", None)
                if finnhub_manager is None:
                    # Finnhub manager not available yet, fall back to original news fetch logic
                    age_minutes = self.monitor._get_macro_data_age_minutes()
                    if age_minutes is not None and age_minutes <= self.stale_limit_minutes:
                        continue
                    logger.info(
                        "[MACRO_HEALTHMONITOR] age_minutes=%s exceeds %.1f. Attempting NEWS_FETCH restart.",
                        "unknown" if age_minutes is None else f"{age_minutes:.1f}",
                        self.stale_limit_minutes,
                    )
                    news_restart_ok = self._attempt_news_fetch_restart()
                    self._update_feed_failures(news_ok=news_restart_ok)
                    if not news_restart_ok:
                        logger.info(
                            "[MACRO_HEALTHMONITOR] NEWS_FETCH restart failed. Keeping macro subsystem online and retrying with backoff."
                        )
                        self._register_recovery_failure(
                            "NEWS_FETCH_RESTART_FAILED",
                            hard_failure=False,
                            emit_warning=self._should_warn_on_feed_failure(),
                        )
                    else:
                        self._reset_recovery_backoff()
                else:
                    # Finnhub manager available - use new dead task detection
                    # ✅ NEW: Check if Finnhub background task is alive first
                    finnhub_alive = finnhub_manager.is_background_task_alive()
                    heartbeat_age_sec = finnhub_manager.get_heartbeat_age_seconds()
                    age_minutes = self.monitor._get_macro_data_age_minutes()

                    logger.debug(
                        "[MACRO_HEALTHMONITOR] State check | "
                        "Finnhub task alive: %s | Heartbeat age: %.1fs | Cache age: %.1f minutes",
                        finnhub_alive,
                        heartbeat_age_sec,
                        age_minutes if age_minutes is not None else -1,
                    )

                    # If task is dead but we haven't exceeded stale limit, try to restart it
                    if not finnhub_alive and heartbeat_age_sec < (self.stale_limit_minutes * 60):
                        logger.info(
                            "[MACRO_HEALTHMONITOR] ⚠️ DETECTED DEAD TASK: Finnhub background task died "
                            "but heartbeat is recent (%.1fs). Attempting restart...",
                            heartbeat_age_sec,
                        )
                        finnhub_restarted = self._attempt_finnhub_restart_sync()
                        self._update_feed_failures(calendar_ok=finnhub_restarted)
                        if finnhub_restarted:
                            continue  # Task restarted successfully

                    # Check if cache is stale (primary indicator of data staleness)
                    if age_minutes is not None and age_minutes <= self.stale_limit_minutes:
                        continue  # Data is fresh, no action needed

                    # Cache is stale - log and attempt recovery
                    stale_log = logger.warning if self._should_warn_on_feed_failure() else logger.info
                    stale_log(
                        "[MACRO_HEALTHMONITOR] ⚠️ STALE DATA: Cache age=%.1f minutes exceeds limit=%.1f. "
                        "Task alive: %s | Heartbeat age: %.1fs. Attempting recovery...",
                        age_minutes if age_minutes is not None else -1,
                        self.stale_limit_minutes,
                        finnhub_alive,
                        heartbeat_age_sec,
                    )

                    # Attempt both Finnhub restart (if task is dead) and news fetch restart.
                    # A single-symbol news miss must not force the whole macro stack into degraded mode.
                    finnhub_restart_ok = True
                    if not finnhub_alive:
                        finnhub_restart_ok = self._attempt_finnhub_restart_sync()

                    news_restart_ok = self._attempt_news_fetch_restart()
                    self._update_feed_failures(news_ok=news_restart_ok, calendar_ok=finnhub_restart_ok)

                    if finnhub_restart_ok and news_restart_ok:
                        self._reset_recovery_backoff()
                        logger.info("[MACRO_HEALTHMONITOR] Recovery succeeded")
                    elif finnhub_restart_ok and not news_restart_ok:
                        if self._macro_cache_still_usable():
                            logger.info(
                                "[MACRO_HEALTHMONITOR] Finnhub is healthy and cached macro/news state remains usable. "
                                "Suppressing NEWS_FETCH_PARTIAL_FAILURE recovery warning."
                            )
                            self._reset_recovery_backoff()
                        else:
                            partial_log = logger.warning if self._should_warn_on_feed_failure() else logger.info
                            partial_log(
                                "[MACRO_HEALTHMONITOR] Partial recovery only: Finnhub is healthy but news refresh failed. "
                                "Continuing macro service without forcing TECHNICAL_ONLY_MODE."
                            )
                            self._register_recovery_failure(
                                "NEWS_FETCH_PARTIAL_FAILURE",
                                hard_failure=False,
                                emit_warning=self._should_warn_on_feed_failure(),
                            )
                    else:
                        failure_log = logger.warning if self._should_warn_on_feed_failure() else logger.info
                        failure_log(
                            "[MACRO_HEALTHMONITOR] Recovery failure: Finnhub restart=%s | news restart=%s",
                            finnhub_restart_ok,
                            news_restart_ok,
                        )
                        self._register_recovery_failure(
                            "FINNHUB_AND_NEWS_RESTART_FAILED",
                            hard_failure=self._should_warn_on_feed_failure(),
                            emit_warning=self._should_warn_on_feed_failure(),
                        )

            except Exception as exc:
                logger.error("[MACRO_HEALTHMONITOR] Health check failed: %s", exc)

    def _attempt_finnhub_restart_sync(self) -> bool:
        """
        Synchronous wrapper to restart Finnhub background task from daemon thread.
        Uses asyncio.run_coroutine_threadsafe to safely call async restart from thread context.
        
        Returns:
            True if restart succeeded, False if task is still alive or restart failed
        """
        if self.monitor.finnhub_manager is None:
            return False

        try:
            # Use asyncio.run_coroutine_threadsafe to safely call async method from thread
            future = asyncio.run_coroutine_threadsafe(
                self.monitor.finnhub_manager.async_attempt_restart(),
                self.loop,
            )
            success = future.result(timeout=self.request_timeout_seconds)
            if success:
                logger.info("[MACRO_HEALTHMONITOR] ✅ Finnhub background task restarted")
                return True
            else:
                logger.error("[MACRO_HEALTHMONITOR] ❌ Finnhub restart returned False")
                return False
        except asyncio.TimeoutError:
            logger.error("[MACRO_HEALTHMONITOR] ❌ Finnhub restart timeout (%.1fs)", self.request_timeout_seconds)
            return False
        except Exception as exc:
            logger.error("[MACRO_HEALTHMONITOR] Finnhub restart exception: %s", exc)
            return False

    async def _attempt_finnhub_restart(self) -> bool:
        """Async version - kept for potential future use in async context."""
        if self.monitor.finnhub_manager is None:
            return False

        try:
            success = await self.monitor.finnhub_manager.async_attempt_restart()
            if success:
                logger.info("[MACRO_HEALTHMONITOR] ✅ Finnhub background task restarted")
                return True
            else:
                logger.error("[MACRO_HEALTHMONITOR] ❌ Finnhub restart failed")
                return False
        except Exception as exc:
            logger.error("[MACRO_HEALTHMONITOR] Finnhub restart exception: %s", exc)
            return False

    def _attempt_news_fetch_restart(self) -> bool:
        if self.monitor.news_collector is None or not self.monitor.raw_symbols:
            return False
        if self._news_cache_still_fresh():
            logger.info("[MACRO_HEALTHMONITOR] NEWS_FETCH restart skipped because shared news cache is still fresh.")
            return True
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.monitor.news_collector.collect_data(
                    self.monitor.raw_symbols,
                    timeframe="4h",
                    force_refresh=True,
                    allow_live_fetch=True,
                ),
                self.loop,
            )
            future.result(timeout=self.request_timeout_seconds)
            self.monitor.technical_only_mode_active = False
            self.monitor._next_macro_eval_at = datetime.now(timezone.utc)
            logger.info("[MACRO_HEALTHMONITOR] NEWS_FETCH restart succeeded.")
            return True
        except Exception as exc:
            if self._news_cache_still_fresh() or self._macro_cache_still_usable():
                logger.info(
                    "[MACRO_HEALTHMONITOR] NEWS_FETCH restart failed but cached macro/news state is still usable: %s",
                    exc,
                )
                return True
            logger.warning("[MACRO_HEALTHMONITOR] NEWS_FETCH restart attempt failed: %s", exc)
            return False

    def _news_cache_age_minutes(self) -> Optional[float]:
        if not getattr(self.monitor, "raw_symbols", None):
            return None
        ages = [NewsDataCollector.get_data_age_minutes(symbol) for symbol in self.monitor.raw_symbols]
        valid_ages = [age for age in ages if age is not None]
        return min(valid_ages) if valid_ages else None

    def _news_cache_still_fresh(self) -> bool:
        age = self._news_cache_age_minutes()
        return age is not None and age <= self.stale_limit_minutes

    def _macro_cache_still_usable(self) -> bool:
        getter = getattr(self.monitor, "_get_macro_data_age_minutes", None)
        age = getter() if callable(getter) else None
        return age is not None and age <= self.stale_limit_minutes
