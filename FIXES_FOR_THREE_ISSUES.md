# FIXES FOR THREE CRITICAL TRADING BOT ISSUES

## Issue #1: Forced Learning Deadlock - Override Time-Based Cooldown

### Problem
The training module checks if a model is "too fresh" (recently trained) and skips retraining. When the forced learning window is triggered, the bot needs to retrain regardless of model age, but the training module refuses.

### Solution
Add a `forced_learning` flag to the training decision logic that bypasses the "model is too fresh" check.

### File: `src/strategies/base_strategy.py` (or wherever model training is checked)

Add this before any training cooldown check:

```python
# ===== ISSUE #1 FIX: Override model freshness check during forced learning =====

def should_skip_training_due_to_freshness(
    model_timestamp: Optional[datetime],
    minimum_age_hours: float = 4.0,
    force_training_active: bool = False,  # NEW PARAMETER
) -> bool:
    """
    Check if model is too fresh to retrain.
    
    When forced_learning is active, ALWAYS allow retraining regardless of age.
    This breaks the deadlock where forced learning triggers but training is skipped.
    
    Args:
        model_timestamp: When model was last trained
        minimum_age_hours: Minimum hours before retraining allowed (default 4 hours)
        force_training_active: If True, BYPASS freshness check entirely
    
    Returns:
        True if training should be skipped due to freshness, False otherwise
    """
    
    # ===== CRITICAL: If forced learning is active, ignore freshness check =====
    if force_training_active:
        logger.critical(
            "[FORCED_LEARNING_OVERRIDE] Forced retraining active. "
            "Bypassing standard model freshness check (Age: %s). "
            "Model will retrain immediately.",
            _format_model_age(model_timestamp) if model_timestamp else "Unknown",
        )
        return False  # DO NOT SKIP - FORCE RETRAINING
    
    # Standard freshness check
    if model_timestamp is None:
        return False  # No model exists, allow training
    
    try:
        model_age_hours = (datetime.now(timezone.utc) - model_timestamp).total_seconds() / 3600.0
        if model_age_hours < minimum_age_hours:
            logger.info(
                "[TRAINING_SKIPPED] Model is still fresh (Age: %.0fm). "
                "Minimum age: %.1fh. Skipping retrain.",
                model_age_hours * 60, minimum_age_hours
            )
            return True  # SKIP - MODEL TOO FRESH
    except Exception as e:
        logger.warning(f"[TRAINING_FRESHNESS_CHECK] Error checking model age: {e}")
    
    return False  # Allow training


# Helper to format model age for logging
def _format_model_age(model_timestamp: Optional[datetime]) -> str:
    """Format model age as human-readable string."""
    if model_timestamp is None:
        return "Unknown"
    try:
        age = datetime.now(timezone.utc) - model_timestamp
        hours = age.total_seconds() / 3600.0
        minutes = (age.total_seconds() % 3600) / 60.0
        if hours >= 1:
            return f"{int(hours)}h {int(minutes)}m"
        return f"{int(minutes)}m"
    except Exception:
        return "Unknown"
```

### Integration Point: In Your Training Loop

Wherever you call `should_skip_training_due_to_freshness()`, pass the `force_training_active` flag:

```python
# In your main trading cycle, when evaluating a symbol for retraining:

# Step 1: Check if forced learning window is active
is_in_forced_learning_window = admission_controller.is_in_forced_learning_window(symbol)
learning_status = admission_controller.update_accuracy_tracking(symbol, ml_accuracy)

# Step 2: If learning window was JUST TRIGGERED, set flag
force_training_active = (learning_status == "LEARNING_WINDOW_TRIGGERED")

# Step 3: Check if training should be skipped
should_skip = should_skip_training_due_to_freshness(
    model_timestamp=model_timestamp,
    minimum_age_hours=4.0,
    force_training_active=force_training_active,  # PASS THE FLAG!
)

if not should_skip:
    # Proceed with training
    train_model(symbol, training_data)
    logger.critical(
        "[FORCED_TRAINING_COMPLETE] %s | Model retrained successfully. "
        "Accuracy: %.1f%% | Ready to resume trading.",
        symbol,
        new_accuracy,
    )
```

### Configuration (Optional)

Add to your `.env` or `config.yaml`:

```yaml
# ML Model Training
ml_training:
  minimum_age_hours: 4.0  # Standard cooldown (4 hours)
  forced_learning_override: true  # Allow forced learning to bypass cooldown
  forced_learning_immediate: true  # Retrain immediately when window triggers

# Or in .env:
ML_TRAINING_MINIMUM_AGE_HOURS=4.0
ML_TRAINING_FORCE_OVERRIDE_ENABLED=true
```

---

## Issue #2: LLM Governance Timeout Too Short

### Problem
The LLM inference timeout is set to 2.5 seconds, but Ollama sometimes needs 2.5-5 seconds. When it times out, it "fails open" and approves trades it shouldn't. Need to increase timeout to 10 seconds.

### File: `src/llm_governance.py`

**Current Code (Lines 78-79):**
```python
LLM_TIMEOUT_SECONDS: float     = float(os.environ.get("OLLAMA_FAST_TIMEOUT_SECONDS", "2.5"))  # HC-ADAPTIVE: reduced from 5.0 → 2.5s
LLM_HEAVY_TIMEOUT_SECONDS: float = float(os.environ.get("OLLAMA_HEAVY_TIMEOUT_SECONDS", "8.0"))
```

**FIXED CODE:**
```python
# ===== ISSUE #2 FIX: Increase LLM timeout to prevent false approvals =====
LLM_TIMEOUT_SECONDS: float     = float(os.environ.get("OLLAMA_FAST_TIMEOUT_SECONDS", "10.0"))  # FIXED: increased from 2.5s → 10s
LLM_HEAVY_TIMEOUT_SECONDS: float = float(os.environ.get("OLLAMA_HEAVY_TIMEOUT_SECONDS", "15.0"))  # FIXED: increased from 8.0s → 15s
```

**Also update the retry timeout in `_ollama_request_blocking()` (Line ~810):**

Current:
```python
with urllib.request.urlopen(req, timeout=timeout_seconds + 2.0) as resp:
```

Fixed:
```python
# Add buffer for network + LLM inference
socket_timeout = max(timeout_seconds + 5.0, 15.0)  # At least 15 seconds total
with urllib.request.urlopen(req, timeout=socket_timeout) as resp:
```

### Configuration Options

Add to your `.env`:

```bash
# LLM Governance Timeout Settings
OLLAMA_FAST_TIMEOUT_SECONDS=10.0      # Fast model timeout (was 2.5s, now 10s)
OLLAMA_HEAVY_TIMEOUT_SECONDS=15.0     # Heavy model timeout (was 8.0s, now 15s)
```

Or in `config.yaml`:

```yaml
llm:
  ollama:
    fast_timeout_seconds: 10.0
    heavy_timeout_seconds: 15.0
    socket_timeout_buffer: 5.0
```

### Updated Timeout Handling Code

Replace lines 1030-1050 in `src/llm_governance.py`:

```python
# ===== ISSUE #2 FIX: Better timeout handling with increased defaults =====

# Determine timeout based on model tier
if not is_escalated:
    target_timeout = LLM_TIMEOUT_SECONDS  # 10 seconds for fast model
    logger.debug(
        "[LLM_TIMEOUT_SETUP] Using FAST model timeout: %.1fs",
        target_timeout
    )
else:
    target_timeout = LLM_HEAVY_TIMEOUT_SECONDS  # 15 seconds for heavy model
    logger.debug(
        "[LLM_TIMEOUT_SETUP] Using HEAVY model timeout: %.1fs",
        target_timeout
    )

t_start = time.perf_counter()

try:
    raw_response = _call_ollama_with_timeout(
        prompt, 
        model_name=target_model, 
        timeout=target_timeout
    )
except urllib.error.URLError as exc:
    return self._record_bypass(
        inputs, f"Ollama unreachable: {exc}",
        latency_ms=(time.perf_counter() - t_start) * 1000,
        cycle=cycle,
    )
except Exception as exc:
    return self._record_bypass(
        inputs, f"HTTP error: {exc}",
        latency_ms=(time.perf_counter() - t_start) * 1000,
        cycle=cycle,
    )

latency_ms = (time.perf_counter() - t_start) * 1000

# ===== ISSUE #2 FIX: Changed timeout threshold from 2500ms to 10000ms =====
if latency_ms > (target_timeout * 1000):
    logger.warning(
        "[LLM_GOVERNANCE_TIMEOUT_EXCEEDED] %s | Latency %.0fms exceeds timeout %.0fms",
        inputs.symbol, latency_ms, target_timeout * 1000
    )

# Only treat as timeout if we actually timed out (response is None)
if raw_response is None:
    logger.warning(
        "[LLM_GOVERNANCE_TIMEOUT] %s | %.0fms elapsed. "
        "Returning PASS_NEUTRAL (approve) to avoid blocking queue.",
        inputs.symbol, latency_ms,
    )
    # ... rest of timeout handling
```

---

## Issue #3: News Feed Falling Back to Mock Mode

### Problem
The news provider isn't configured or API key is missing, so it falls back to mock mode. Need to set up real news provider (NewsAPI).

### Solution A: Configure NewsAPI (Recommended)

**File: `config.yaml`**

```yaml
# ===== ISSUE #3 FIX: Configure live news provider =====
news:
  provider: "newsapi"  # Changed from: mock or unset
  api_key: "${NEWS_API_KEY}"  # Will load from environment variable
  enabled: true
  mock_mode: false  # Explicitly disable mock mode
  require_live_data: false  # Set to true if you REQUIRE live news
  min_impact: "HIGH"
```

**File: `.env`**

```bash
# ===== ISSUE #3 FIX: NewsAPI Configuration =====
NEWS_API_KEY=your_newsapi_key_here  # Get free API key from https://newsapi.org
NEWS_PROVIDER=newsapi
NEWS_ENABLED=true
NEWS_MOCK_MODE=false
MACRO_NEWS_MAX_STALENESS_MINUTES=60
```

### Solution B: Initialize Real News Provider in Code

**File: `main.py` (Around line 1375 where NewsDataCollector is initialized)**

Current Code:
```python
# 7. Initialize News Collector
logger.info("[INIT] Initializing News Collector...")
news_collector = NewsDataCollector(config)
```

**Fixed Code:**

```python
# ===== ISSUE #3 FIX: Configure and validate live news provider =====
# 7. Initialize News Collector
logger.info("[INIT] Initializing News Collector...")
news_collector = NewsDataCollector(config)

# Validate news provider setup
news_config = getattr(config, "news", None)
news_provider = str(getattr(news_config, "provider", "") or "").strip().lower()
news_api_key = str(os.environ.get("NEWS_API_KEY", "") or "").strip()

if news_provider in {"", "unset", "none", "disabled"}:
    news_provider = "newsapi"  # Default to NewsAPI
    
if news_provider == "newsapi" and not news_api_key:
    logger.critical(
        "[NEWS_CONFIG_ERROR] NewsAPI provider selected but NEWS_API_KEY not set. "
        "Get free API key from https://newsapi.org/docs | Set: export NEWS_API_KEY=your_key"
    )
    logger.warning(
        "[NEWS_FALLBACK] Falling back to mock mode. "
        "Live news filtering disabled until API key is configured."
    )
else:
    logger.info(
        "[NEWS_CONFIGURED] Live news provider: %s | Key available: %s",
        news_provider, "YES" if news_api_key else "NO"
    )

live_news_ready = bool(getattr(news_collector, "is_live_feed_ready", lambda: False)())
require_live_news = bool(getattr(getattr(config, "news", None), "require_live_data", False))

if require_live_news and not live_news_ready:
    logger.critical(
        "[LIVE_NEWS_REQUIRED] Live news is REQUIRED but not ready. "
        "Bot cannot start trading without live news data."
    )
    # Either exit or wait for news to be configured
    if not news_api_key:
        raise RuntimeError(
            "LIVE_NEWS_REQUIRED=true but NEWS_API_KEY not configured. "
            "Get API key from https://newsapi.org and set NEWS_API_KEY environment variable."
        )
elif not live_news_ready:
    logger.warning(
        "[NEWS_FALLBACK_MODE] Provider=%s | Live news unavailable. "
        "Bot will continue with price volatility fallback.",
        news_provider,
    )
else:
    logger.info(
        "[NEWS_LIVE_READY] Provider=%s | Live news filtering ENABLED and ready.",
        news_provider,
    )
```

### Alternative: Use Different News Provider

If you prefer a different news source, implement a custom provider:

**File: `src/data/custom_news_provider.py`**

```python
# ===== ISSUE #3 FIX: Alternative news provider implementation =====

import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import feedparser  # pip install feedparser

logger = logging.getLogger(__name__)


class ForexFactoryNewsProvider:
    """Forex Factory economic calendar integration"""
    
    def __init__(self, cache_minutes: int = 15):
        self.cache_minutes = cache_minutes
        self.cache: Dict[str, Any] = {}
        self.cache_time: Optional[datetime] = None
    
    async def fetch_economic_calendar(self) -> List[Dict[str, Any]]:
        """Fetch economic calendar from Forex Factory RSS"""
        
        # Check cache first
        if self.cache_time and (datetime.now() - self.cache_time).total_seconds() < (self.cache_minutes * 60):
            return self.cache.get("events", [])
        
        try:
            # Forex Factory RSS feed
            feed = feedparser.parse("https://www.forexfactory.com/calendar.php?format=xml")
            
            events = []
            for entry in feed.entries[:10]:  # Get latest 10 events
                events.append({
                    "title": entry.get("title", ""),
                    "description": entry.get("summary", ""),
                    "source": "Forex Factory",
                    "published_at": datetime.now(timezone.utc),
                    "url": entry.get("link", ""),
                })
            
            # Cache result
            self.cache = {"events": events}
            self.cache_time = datetime.now()
            
            logger.info(f"[FOREX_FACTORY_NEWS] Fetched {len(events)} economic events")
            return events
            
        except Exception as e:
            logger.error(f"[FOREX_FACTORY_ERROR] Failed to fetch calendar: {e}")
            return []


class AlternativeNewsProvider:
    """Generic news provider for alternative sources (Investing.com, Bloomberg, etc.)"""
    
    SOURCES = {
        "investing_com": "https://www.investing.com/news/",
        "bloomberg": "https://www.bloomberg.com/feed/podcast/etf-report.xml",
        "cnbc": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    }
    
    async def fetch_from_source(self, source_name: str) -> List[Dict[str, Any]]:
        """Fetch news from alternative source"""
        
        if source_name not in self.SOURCES:
            logger.warning(f"[NEWS_PROVIDER] Unknown source: {source_name}")
            return []
        
        try:
            url = self.SOURCES[source_name]
            feed = feedparser.parse(url)
            
            events = []
            for entry in feed.entries[:5]:
                events.append({
                    "title": entry.get("title", ""),
                    "description": entry.get("summary", ""),
                    "source": source_name.replace("_", " ").title(),
                    "published_at": datetime.now(timezone.utc),
                    "url": entry.get("link", ""),
                })
            
            logger.info(f"[{source_name.upper()}] Fetched {len(events)} articles")
            return events
            
        except Exception as e:
            logger.error(f"[{source_name.upper()}_ERROR] {e}")
            return []
```

### Configuration Summary

**To use LiveNewsAPI (Recommended):**

```bash
export NEWS_API_KEY="your-key-from-newsapi.org"
export NEWS_PROVIDER="newsapi"
export NEWS_ENABLED="true"
export NEWS_MOCK_MODE="false"
```

**To use Forex Factory:**

```yaml
news:
  provider: "forex_factory"
  enabled: true
  mock_mode: false
```

**To use Alternative Feed:**

```yaml
news:
  provider: "investing_com"  # or bloomberg, cnbc
  enabled: true
  mock_mode: false
```

---

## Summary of Changes

| Issue | Fix | Impact |
|-------|-----|--------|
| #1: Forced Learning Deadlock | Add `force_training_active` flag to bypass freshness check | Retraining happens immediately when accuracy < 45% for 20 cycles |
| #2: LLM Timeout Too Short | Increase from 2.5s → 10s, socket timeout to 15s | LLM governance has enough time to process complex trades |
| #3: News Mock Mode | Configure NewsAPI with API key, or use alternative provider | Live news filtering enables macro-aware trading |

---

## Testing

After implementing these fixes:

```python
# Test 1: Verify forced learning override works
assert should_skip_training_due_to_freshness(
    model_timestamp=datetime.now(timezone.utc),
    minimum_age_hours=4.0,
    force_training_active=True  # Should return False (don't skip)
) == False

# Test 2: Verify LLM timeout increased
assert LLM_TIMEOUT_SECONDS >= 10.0, "LLM timeout too short"

# Test 3: Verify news provider is not mock
assert news_collector.provider != "mock", "News provider still in mock mode"
assert news_collector.is_live_feed_ready(), "News feed not ready"
```

