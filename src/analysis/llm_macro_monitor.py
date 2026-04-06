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
import contextlib
try:
    import aiohttp  # type: ignore
except Exception:  # pragma: no cover
    aiohttp = None
from src.data.news_data_collector import NewsDataCollector

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("MACRO_MONITOR_OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
# === FIX: Unified Qwen3.5:4B model for all macro monitoring tasks ===
DEFAULT_MODEL = os.environ.get("MACRO_MONITOR_PRIMARY_MODEL", "qwen3.5:0.8b")
PRIMARY_MODEL = os.environ.get("MACRO_MONITOR_PRIMARY_MODEL", "qwen3.5:0.8b")
FALLBACK_MODEL = os.environ.get("MACRO_MONITOR_FALLBACK_MODEL", "qwen3.5:4b")
FAST_FALLBACK_MODEL = os.environ.get("MACRO_MONITOR_FAST_MODEL", "qwen3.5:0.8b")
PRIMARY_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("MACRO_MONITOR_PRIMARY_TIMEOUT_SECONDS", "5.0"))
FALLBACK_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("MACRO_MONITOR_FALLBACK_TIMEOUT_SECONDS", "8.0"))
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
        self._updated_at: Optional[str] = None
        self._source: str = "init"
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        try:
            if not os.path.exists(self.cache_path):
                return
            with open(self.cache_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            penalties = payload.get("penalties", {}) if isinstance(payload, dict) else {}
            reasons = payload.get("reasons", {}) if isinstance(payload, dict) else {}
            with self._lock:
                self._penalties = {
                    _normalize_symbol(k): float(max(0.0, min(0.4, v)))
                    for k, v in penalties.items()
                    if isinstance(v, (int, float))
                }
                self._reasons = {
                    _normalize_symbol(k): str(v)
                    for k, v in reasons.items()
                    if isinstance(v, str) and str(v).strip()
                }
                self._updated_at = payload.get("updated_at")
                self._source = payload.get("source", "disk")
        except Exception as exc:
            logger.warning("[MACRO_MONITOR] Failed to load cache: %s", exc)

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
        self._force_refresh_age_minutes = float(os.environ.get("MACRO_FORCE_REFRESH_MINUTES", "10"))

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
                    self.news_collector.collect_data(self.raw_symbols, timeframe="4h"),
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
                    async with self._ollama_semaphore:
                        generation_task = asyncio.create_task(
                            asyncio.to_thread(
                                self._call_ollama_blocking,
                                prompt,
                                model_name=model_for_attempt,
                                num_predict=100,
                                request_timeout=timeout_for_model,
                            )
                        )
                        raw = await asyncio.wait_for(generation_task, timeout=timeout_for_model)
                    if raw:
                        return raw
                    self._last_ollama_error = self._last_ollama_error or "EMPTY_RESPONSE"
                    logger.warning(
                        "[MACRO_MONITOR] Empty Ollama response on attempt %d/%d (model=%s timeout=%.1fs)",
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
                        logger.warning(
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
                        logger.warning(
                            "[MACRO_MONITOR] Ollama timed out on attempt %d/%d (model=%s timeout=%.1fs)",
                            attempt,
                            self.max_retries,
                            model_for_attempt,
                            timeout_for_model,
                        )
                except Exception as exc:
                    self._last_ollama_error = self._last_ollama_error or "REQUEST_EXCEPTION"
                    logger.warning(
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
            async with self._ollama_semaphore:
                generation_task = asyncio.create_task(
                    asyncio.to_thread(
                        self._call_ollama_blocking,
                        prompt,
                        model_name=self.fallback_model,
                        num_predict=100,
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
        Startup pre-flight check: verify Ollama is reachable and qwen3.5:4b models exist.
        """
        try:
            models = await asyncio.to_thread(self._fetch_ollama_models)
            self._ollama_reachable = True
            if not models:
                logger.warning("[MACRO_MONITOR] Ollama model list is empty.")
                return
            logger.info("[MACRO_MONITOR] Verified installed Ollama models: %s", models)
            normalized = {str(m).strip().lower() for m in models if str(m).strip()}
            qwen_expected = {"qwen3.5:4b"}
            with_latest = {f"{m}:latest" for m in qwen_expected}
            if normalized.isdisjoint(qwen_expected | with_latest):
                logger.critical(
                    "[MACRO_MONITOR] qwen3.5:4b model not found in Ollama model list. Expected %s",
                    sorted(qwen_expected),
                )
        except Exception as exc:
            self._ollama_reachable = False
            logger.warning("[MACRO_MONITOR] Ollama startup validation failed: %s", exc)

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

        max_staleness_minutes = float(os.environ.get("MACRO_NEWS_MAX_STALENESS_MINUTES", "60"))
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
        with urllib.request.urlopen(req, timeout=10.0) as resp:
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
        
        ===== FIX #2: COMPREHENSIVE MOCK MODE DETECTION =====
        Check multiple signals to determine if news provider is truly in mock mode.
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
            pass

        # Optional env override (fallback)
        env_mode = str(os.environ.get("NEWS_FILTERING_MODE", "")).strip().lower()
        if env_mode == "mock mode" or "mock" in env_mode:
            return True

        env_enabled = str(os.environ.get("NEWS_ENABLED", "")).strip().lower()
        if env_enabled in {"0", "false", "off", "disabled"}:
            return True
        
        # ===== FIX #2: ALSO CHECK ENV PROVIDER SETTING =====
        env_provider = str(os.environ.get("NEWS_PROVIDER", "")).strip().lower()
        if env_provider in {"mock", "mock_provider", "disabled"}:
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
            "You are a forex macro risk officer. Assess near-term macro/event risk per symbol.\n"
            "Output ONLY valid JSON with this exact top-level shape:\n"
            '{"penalties":{"SYMBOL":{"macro_risk_penalty":0.0,"trigger_reason":"No_Macro_Risk"}}}\n'
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
        target_model = model_name or self.model
        # For main generation calls, force model-specific timeout values so no legacy/default
        # timeout setting can silently override 300s/180s behavior.
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
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with OLLAMA_REQUEST_LOCK:
                socket_timeout = max(65.0, effective_timeout + 5.0)
                with urllib.request.urlopen(req, timeout=socket_timeout) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                    self._ollama_reachable = True
                    return raw.get("response", "") or ""
        except urllib.error.HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                error_body = ""
            if getattr(exc, "code", None) == 404:
                self._last_ollama_error = "HTTP_404"
                logger.warning(
                    "[MACRO_MONITOR] Ollama HTTP 404 detected at %s | model=%s | body=%s",
                    OLLAMA_URL,
                    target_model,
                    error_body or "<empty>",
                )
                return ""
            self._last_ollama_error = f"HTTP_{getattr(exc, 'code', 'ERR')}"
            logger.warning(
                "[MACRO_MONITOR] Ollama HTTP error: code=%s model=%s body=%s err=%s",
                getattr(exc, "code", "ERR"),
                target_model,
                error_body or "<empty>",
                exc,
            )
            return ""
        except urllib.error.URLError as exc:
            self._last_ollama_error = "CONNECTION_REFUSED"
            self._ollama_reachable = False
            if "timed out" in str(getattr(exc, "reason", exc)).lower():
                raise TimeoutError("timed out")
            logger.warning("[MACRO_MONITOR] Ollama unreachable: %s", exc)
            return ""
        except TimeoutError as exc:
            # Re-raise so asyncio.wait_for in the outer wrapper sees asyncio.TimeoutError
            # and the model-chain fallback (qwen3.5:4b) is properly triggered.
            raise
        except Exception as exc:
            # socket.timeout is a subclass of TimeoutError in Python 3.3+, so it is
            # caught by the branch above and re-raised.  Any other unexpected error
            # is logged and treated as an empty response so the retry loop continues.
            self._last_ollama_error = "REQUEST_EXCEPTION"
            logger.warning("[MACRO_MONITOR] Ollama request failed: %s", exc)
            return ""

    def _parse_penalties(self, raw: str) -> tuple[Dict[str, float], Dict[str, str]]:
        if not raw:
            return {}, {}
        raw = self._clean_response(raw)
        parsed = None
        try:
            parsed = json.loads(raw)
        except Exception:
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
                    timeout=10.0,
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

    def _get_macro_data_age_minutes(self) -> Optional[float]:
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

        news_age_minutes: Optional[float] = None
        if self.raw_symbols:
            news_ages = [
                NewsDataCollector.get_data_age_minutes(symbol)
                for symbol in self.raw_symbols
            ]
            valid_news_ages = [age for age in news_ages if age is not None]
            if valid_news_ages:
                news_age_minutes = min(valid_news_ages)

        freshness_candidates = [
            age for age in (cache_age_minutes, news_age_minutes) if age is not None
        ]
        return min(freshness_candidates) if freshness_candidates else None

    async def _maybe_log_macro_data_age(self) -> None:
        now = datetime.now(timezone.utc)
        if (
            self._last_macro_age_log_at is not None
            and (now - self._last_macro_age_log_at).total_seconds() < self._macro_age_log_interval_seconds
        ):
            return
        self._last_macro_age_log_at = now
        age_minutes = self._get_macro_data_age_minutes()
        logger.info(
            "[MACRO_DATA_AGE] age_minutes=%s | refresh_limit=%.1f | technical_only_mode=%s",
            "unknown" if age_minutes is None else f"{age_minutes:.1f}",
            self._force_refresh_age_minutes,
            self.technical_only_mode_active,
        )

    async def _maybe_force_refresh_stale_macro_data(self) -> None:
        """
        Force-refresh stale macro/news data if age exceeds threshold.
        
        ===== FIX #2: SKIP REFRESH IF NEWS PROVIDER IS IN MOCK MODE =====
        If the news collector is disabled or in mock mode, staleness check becomes meaningless.
        Skip refresh attempt entirely and rely on volatility fallback instead.
        """
        if self.news_collector is None or not self.raw_symbols:
            return
        
        # ===== FIX #2: CHECK IF MOCK MODE IS ACTIVE BEFORE STALENESS CHECK =====
        if self._news_filtering_is_mock_mode():
            # News provider is in mock mode (simulated/disabled)
            # Don't attempt to refresh because the data source isn't live anyway
            # Continue silently using volatility-based fallback
            logger.debug(
                "[MACRO_FORCE_REFRESH] News provider is in Mock Mode. "
                "Skipping staleness check and continuing with volatility fallback."
            )
            return
        
        # Only check staleness if we have a live news provider
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
            )
            self._next_macro_eval_at = datetime.now(timezone.utc)
            logger.info("[MACRO_FORCE_REFRESH] News refresh completed. Macro evaluation rescheduled immediately.")
        except Exception as exc:
            logger.warning("[MACRO_FORCE_REFRESH] Forced news refresh failed: %s", exc)


class MacroHealthMonitor(threading.Thread):
    """Daemon thread that prevents stale macro/news blindness."""

    def __init__(
        self,
        monitor: AsyncLLMMacroMonitor,
        loop: asyncio.AbstractEventLoop,
        *,
        check_interval_seconds: int = 60,
        stale_limit_minutes: float = 10.0,
        request_timeout_seconds: float = 45.0,
    ):
        super().__init__(name="macro-health-monitor", daemon=True)
        self.monitor = monitor
        self.loop = loop
        self.check_interval_seconds = max(5, int(check_interval_seconds))
        self.stale_limit_minutes = float(stale_limit_minutes)
        self.request_timeout_seconds = float(request_timeout_seconds)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.wait(self.check_interval_seconds):
            try:
                age_minutes = self.monitor._get_macro_data_age_minutes()
                if age_minutes is not None and age_minutes <= self.stale_limit_minutes:
                    continue
                logger.warning(
                    "[MACRO_HEALTHMONITOR] age_minutes=%s exceeds %.1f. Attempting NEWS_FETCH restart.",
                    "unknown" if age_minutes is None else f"{age_minutes:.1f}",
                    self.stale_limit_minutes,
                )
                if not self._attempt_news_fetch_restart():
                    logger.warning(
                        "[MACRO_HEALTHMONITOR] NEWS_FETCH restart failed. Enabling TECHNICAL_ONLY_MODE for safe degraded trading."
                    )
                    self.monitor._activate_technical_only_mode("MACRO_HEALTHMONITOR_NEWS_FETCH_RESTART_FAILED")
            except Exception as exc:
                logger.warning("[MACRO_HEALTHMONITOR] Health check failed: %s", exc)

    def _attempt_news_fetch_restart(self) -> bool:
        if self.monitor.news_collector is None or not self.monitor.raw_symbols:
            return False
        future = None
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.monitor.news_collector.collect_data(
                    self.monitor.raw_symbols,
                    timeframe="4h",
                    force_refresh=True,
                ),
                self.loop,
            )
            future.result(timeout=self.request_timeout_seconds)
            self.monitor.technical_only_mode_active = False
            self.monitor._next_macro_eval_at = datetime.now(timezone.utc)
            logger.info("[MACRO_HEALTHMONITOR] NEWS_FETCH restart succeeded.")
            return True
        except Exception as exc:
            try:
                if future is not None:
                    future.cancel()
            except Exception:
                pass
            self._schedule_immediate_news_fetch_retry()
            logger.warning("[MACRO_HEALTHMONITOR] NEWS_FETCH restart attempt failed: %s", exc)
            return False

    def _schedule_immediate_news_fetch_retry(self) -> None:
        if self.monitor.news_collector is None or not self.monitor.raw_symbols:
            return

        async def _retry_once() -> None:
            await self.monitor.news_collector.collect_data(
                self.monitor.raw_symbols,
                timeframe="4h",
                force_refresh=True,
            )
            self.monitor._next_macro_eval_at = datetime.now(timezone.utc)

        retry_future = asyncio.run_coroutine_threadsafe(_retry_once(), self.loop)

        def _log_retry_result(fut) -> None:
            try:
                fut.result()
                logger.info("[MACRO_HEALTHMONITOR] Immediate NEWS_FETCH retry completed.")
            except Exception as retry_exc:
                logger.warning("[MACRO_HEALTHMONITOR] Immediate NEWS_FETCH retry failed: %s", retry_exc)

        retry_future.add_done_callback(_log_retry_result)

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
